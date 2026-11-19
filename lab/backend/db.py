"""Tiny SQLite store for the extraction lab. Fully isolated from the main app."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "lab.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                status TEXT NOT NULL,
                page_count INTEGER DEFAULT 0,
                model TEXT,
                vlm_status TEXT,
                latency_ms INTEGER,
                error TEXT,
                result_json TEXT
            )
            """
        )


def create_run(filename: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO runs (filename, uploaded_at, status) VALUES (?,?,?)",
            (filename, datetime.now(timezone.utc).isoformat(), "uploaded"),
        )
        return int(cur.lastrowid)


def update_run(run_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [run_id]
    with _conn() as c:
        c.execute(f"UPDATE runs SET {cols} WHERE id = ?", vals)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("result_json"):
        try:
            d["result"] = json.loads(d["result_json"])
        except Exception:
            d["result"] = None
    else:
        d["result"] = None
    d.pop("result_json", None)
    return d


def get_run(run_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_dict(row) if row else None


def list_runs() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, filename, uploaded_at, status, page_count, model, vlm_status, latency_ms "
            "FROM runs ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
