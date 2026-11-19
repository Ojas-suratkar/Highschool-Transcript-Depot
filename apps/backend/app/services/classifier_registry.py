"""Shared registry of runtime-integrated transcript-type classifiers.

This module gives the routing pipeline one place to ask:

1. Which transcript labels are already known/existing?
2. Which labels have extractor processors from classifier_type?
3. Which labels were promoted through the new transcript_classifier_routes table?

Important:
- classifier_type is the old/runtime extractor processor registry.
- transcript_classifier_routes is the new "Ready -> Existing" route registry.
- A label in transcript_classifier_routes should be treated as an existing
  transcript type, even if it has 0 files in the selected semester.

The key is normalized by sanitize_classifier_key():

    classifier label -> folder key -> route lookup key

Examples:
    Cypress High School -> cypress_high_school
    cypress_high_school -> cypress_high_school
    Mayfair High School -> mayfair_high_school
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from sqlalchemy import create_engine, text

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


# Built-in types matched by hardcoded rules elsewhere.
HARDCODED_CLASSIFIERS = {
    "lbusd",
    "mayfair_high_school",
    "st_anthony_high_school",
    "others",
}

_TTL_SECONDS = 60.0

_ENGINE = None

_EXTRACTOR_PROCESSOR_CACHE: dict[str, str] = {}
_EXTRACTOR_PROCESSOR_CACHE_TS: float = 0.0

_ACTIVE_ROUTE_CACHE: dict[str, dict[str, str]] = {}
_ACTIVE_ROUTE_CACHE_TS: float = 0.0

_ROUTABLE_CACHE: dict[str, str] = {}
_ROUTABLE_CACHE_TS: float = 0.0


def _load_env_files() -> None:
    if load_dotenv is None:
        return

    for path in ("env", ".env", "apps/backend/env", "apps/backend/.env"):
        if os.path.exists(path):
            load_dotenv(path, override=False)


def sanitize_classifier_key(value: str) -> str:
    """Normalize a classifier label/type name into the canonical routing key."""
    name = str(value or "").strip().lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _sync_database_url(url: str) -> str:
    """Convert common async URL forms to a sync SQLAlchemy URL."""
    clean_url = str(url or "").strip()

    if not clean_url:
        return ""

    if "+asyncpg" in clean_url:
        return clean_url.replace("+asyncpg", "+psycopg")

    if clean_url.startswith("postgresql://"):
        return clean_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return clean_url


def _get_database_url() -> str:
    _load_env_files()

    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("SQLALCHEMY_DATABASE_URL")
        or ""
    )

    return _sync_database_url(url)


def _get_engine():
    global _ENGINE

    if _ENGINE is not None:
        return _ENGINE

    url = _get_database_url()

    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Cannot load classifier registry."
        )

    _ENGINE = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )

    return _ENGINE


def invalidate_classifier_cache() -> None:
    """Force all classifier registry lookups to reload from DB."""
    global _EXTRACTOR_PROCESSOR_CACHE_TS
    global _ACTIVE_ROUTE_CACHE_TS
    global _ROUTABLE_CACHE_TS

    _EXTRACTOR_PROCESSOR_CACHE_TS = 0.0
    _ACTIVE_ROUTE_CACHE_TS = 0.0
    _ROUTABLE_CACHE_TS = 0.0


def get_extractor_processor_classifiers() -> dict[str, str]:
    """
    Return old extractor processor registry:

        {classifier_key -> processor_id}

    Source:
        classifier_type

    This is the real Document AI extractor processor mapping.
    """
    global _EXTRACTOR_PROCESSOR_CACHE
    global _EXTRACTOR_PROCESSOR_CACHE_TS

    now = time.time()

    if (
        _EXTRACTOR_PROCESSOR_CACHE
        and now - _EXTRACTOR_PROCESSOR_CACHE_TS < _TTL_SECONDS
    ):
        return _EXTRACTOR_PROCESSOR_CACHE

    try:
        with _get_engine().connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        classifier_name,
                        processor_id
                    FROM classifier_type
                    WHERE classifier_name IS NOT NULL
                    AND processor_id IS NOT NULL
                    """
                )
            ).all()

        _EXTRACTOR_PROCESSOR_CACHE = {
            sanitize_classifier_key(name): str(processor_id).strip()
            for name, processor_id in rows
            if str(name or "").strip() and str(processor_id or "").strip()
        }
        _EXTRACTOR_PROCESSOR_CACHE_TS = now

    except Exception:
        # Best effort: keep previous cache so hardcoded routing still works.
        pass

    return _EXTRACTOR_PROCESSOR_CACHE


def get_active_classifier_routes() -> dict[str, dict[str, str]]:
    """
    Return new active Existing Transcript Type routes:

        {
          classifier_key: {
            "classifier_label": "...",
            "display_name": "...",
            "extractor_profile": "...",
            "status": "active",
          }
        }

    Source:
        transcript_classifier_routes

    This is what makes Cypress / promoted schools count as existing transcript
    types after Ready -> Move to Existing.
    """
    global _ACTIVE_ROUTE_CACHE
    global _ACTIVE_ROUTE_CACHE_TS

    now = time.time()

    if _ACTIVE_ROUTE_CACHE and now - _ACTIVE_ROUTE_CACHE_TS < _TTL_SECONDS:
        return _ACTIVE_ROUTE_CACHE

    try:
        with _get_engine().connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        classifier_label,
                        display_name,
                        extractor_profile,
                        status
                    FROM transcript_classifier_routes
                    WHERE status = 'active'
                    """
                )
            ).mappings().all()

        routes: dict[str, dict[str, str]] = {}

        for row in rows:
            classifier_label = str(row.get("classifier_label") or "").strip()
            display_name = str(row.get("display_name") or "").strip()
            extractor_profile = str(row.get("extractor_profile") or "").strip()
            status = str(row.get("status") or "").strip()

            key = sanitize_classifier_key(classifier_label or display_name)

            if not key:
                continue

            routes[key] = {
                "classifier_label": classifier_label or key,
                "display_name": display_name or classifier_label or key,
                "extractor_profile": extractor_profile or "generic_transcript",
                "status": status or "active",
            }

        _ACTIVE_ROUTE_CACHE = routes
        _ACTIVE_ROUTE_CACHE_TS = now

    except Exception:
        # Best effort: keep previous cache.
        pass

    return _ACTIVE_ROUTE_CACHE


def get_routable_existing_classifier_keys() -> set[str]:
    """
    Return every classifier key that should be treated as Existing.

    Includes:
    - hardcoded built-ins
    - classifier_type rows
    - transcript_classifier_routes active rows
    """
    keys: set[str] = set()

    keys.update(HARDCODED_CLASSIFIERS)
    keys.update(get_extractor_processor_classifiers().keys())
    keys.update(get_active_classifier_routes().keys())

    return keys


def is_existing_classifier_key(value: str) -> bool:
    """
    True when a classifier label should route to Existing Transcript Type
    instead of New Transcript Type / Others.
    """
    key = sanitize_classifier_key(value)
    return key in get_routable_existing_classifier_keys()


def get_existing_route_for_label(value: str) -> dict[str, str] | None:
    """
    Return route metadata for a classifier label if it was promoted through
    transcript_classifier_routes.
    """
    key = sanitize_classifier_key(value)
    return get_active_classifier_routes().get(key)


def get_existing_folder_name_for_label(value: str) -> str:
    """
    Convert a predicted label to the folder key used under:

        02_Library_Categorized_HS_Transcripts/<semester>/transcript/<folder>/

    For promoted routes, use classifier_label as folder key.
    For old labels, use sanitized key.
    """
    key = sanitize_classifier_key(value)
    route = get_active_classifier_routes().get(key)

    if route:
        return sanitize_classifier_key(route.get("classifier_label") or key)

    return key


def get_integrated_classifiers() -> dict[str, str]:
    """
    Backward-compatible function used by older routing code.

    Historically returned:
        {classifier_key -> processor_id}

    Now it returns a routable registry:
        - classifier_type entries keep their processor_id value.
        - transcript_classifier_routes entries use extractor_profile as value.

    This keeps older code that checks membership like:

        if key in get_integrated_classifiers():

    working for newly promoted routes such as cypress_high_school.
    """
    global _ROUTABLE_CACHE
    global _ROUTABLE_CACHE_TS

    now = time.time()

    if _ROUTABLE_CACHE and now - _ROUTABLE_CACHE_TS < _TTL_SECONDS:
        return _ROUTABLE_CACHE

    merged: dict[str, str] = {}

    # Old real extractor processor map.
    merged.update(get_extractor_processor_classifiers())

    # New promoted Existing routes.
    for key, route in get_active_classifier_routes().items():
        if key not in merged:
            merged[key] = route.get("extractor_profile") or "generic_transcript"

    _ROUTABLE_CACHE = merged
    _ROUTABLE_CACHE_TS = now

    return _ROUTABLE_CACHE


def debug_classifier_registry() -> dict[str, Any]:
    """
    Helpful for temporary backend debugging.
    """
    extractor_processors = get_extractor_processor_classifiers()
    active_routes = get_active_classifier_routes()
    routable_keys = sorted(get_routable_existing_classifier_keys())

    return {
        "hardcoded": sorted(HARDCODED_CLASSIFIERS),
        "extractor_processors": extractor_processors,
        "active_routes": active_routes,
        "routable_keys": routable_keys,
    }
