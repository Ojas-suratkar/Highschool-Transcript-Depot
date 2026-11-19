"""App-wide notification feed.

A single place any backend code (sync pipeline, async router, background watcher)
can post a notification that shows up in the user's notification sidebar.

Backed by a tiny `app_notifications` table created on first use (no migration
needed). Writes go through a sync psycopg engine so it's callable from anywhere
without an async context; posting never raises — a notification failure must
never break the work that triggered it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from sqlalchemy import create_engine, text

LEVELS = {"info", "success", "warning", "error", "progress"}

_engine = None
_table_ready = False


def _get_engine():
    global _engine
    if _engine is None:
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/transcripts",
        )
        _engine = create_engine(
            url.replace("+asyncpg", "+psycopg"),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
        )
    return _engine


def ensure_table() -> None:
    """Create the notifications table + index if they don't exist (idempotent)."""
    global _table_ready
    if _table_ready:
        return
    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_notifications (
                    id          BIGSERIAL PRIMARY KEY,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    level       VARCHAR(20) NOT NULL DEFAULT 'info',
                    category    VARCHAR(50) NOT NULL DEFAULT 'general',
                    title       TEXT NOT NULL,
                    message     TEXT,
                    read        BOOLEAN NOT NULL DEFAULT false,
                    dedup_key   VARCHAR(200),
                    meta        JSONB
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_app_notifications_created "
                "ON app_notifications (created_at DESC)"
            )
        )
    _table_ready = True


def notify(
    title: str,
    message: str | None = None,
    *,
    level: str = "info",
    category: str = "general",
    meta: dict[str, Any] | None = None,
    dedup_key: str | None = None,
    dedup_window_seconds: int = 0,
) -> None:
    """Post a notification. Safe to call from anywhere; never raises.

    `dedup_key` + `dedup_window_seconds`: if a notification with the same key was
    posted within the window, skip — avoids spamming the feed from a polling loop.
    """
    try:
        ensure_table()
        if level not in LEVELS:
            level = "info"
        with _get_engine().begin() as conn:
            if dedup_key and dedup_window_seconds > 0:
                existing = conn.execute(
                    text(
                        "SELECT 1 FROM app_notifications WHERE dedup_key = :k "
                        "AND created_at > now() - (:w || ' seconds')::interval LIMIT 1"
                    ),
                    {"k": dedup_key, "w": str(dedup_window_seconds)},
                ).first()
                if existing:
                    return
            conn.execute(
                text(
                    "INSERT INTO app_notifications (level, category, title, message, dedup_key, meta) "
                    "VALUES (:l, :c, :t, :m, :k, CAST(:meta AS JSONB))"
                ),
                {
                    "l": level,
                    "c": category,
                    "t": str(title)[:500],
                    "m": (str(message) if message is not None else None),
                    "k": dedup_key,
                    "meta": json.dumps(meta) if meta else None,
                },
            )
    except Exception:  # noqa: BLE001 — never break the caller
        pass
