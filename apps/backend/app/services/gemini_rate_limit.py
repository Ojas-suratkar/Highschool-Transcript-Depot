"""
Process-wide rate limiting for Gemini API calls.

Block-chunked extraction + per-row crop verification make many small Gemini calls
per transcript (~60), and several transcripts run concurrently. Without a cap that
bursts past Gemini's requests-per-minute quota and returns 429 / RESOURCE_EXHAUSTED.

Every generate_content call is funnelled through:
  1. a process-wide concurrency cap (BoundedSemaphore) so the instantaneous request
     rate stays bounded no matter how many files/threads are active; and
  2. automatic exponential-backoff retry on 429 / RESOURCE_EXHAUSTED, so a brief
     burst is absorbed silently instead of surfacing as an error.

All Gemini callers use generate_content_limited() instead of calling
client.models.generate_content() directly.
"""

from __future__ import annotations

import os
import random
import threading
import time
from typing import Any


def _max_concurrent_calls() -> int:
    try:
        return max(1, int(os.getenv("GEMINI_MAX_CONCURRENT_CALLS", "12")))
    except (TypeError, ValueError):
        return 12


def _max_retries() -> int:
    try:
        return max(0, int(os.getenv("GEMINI_RATE_LIMIT_MAX_RETRIES", "10")))
    except (TypeError, ValueError):
        return 10


def _max_rpm() -> int:
    # Proactive requests-per-minute cap. 0 = disabled (reactive backoff only).
    # Set this to ~80-90% of the project's Vertex Gemini quota to avoid 429s.
    try:
        return max(0, int(os.getenv("GEMINI_MAX_RPM", "0")))
    except (TypeError, ValueError):
        return 0


def _backoff_max_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("GEMINI_BACKOFF_MAX_SECONDS", "15")))
    except (TypeError, ValueError):
        return 15.0


# Sized once at import. Tune via GEMINI_MAX_CONCURRENT_CALLS (needs a restart).
_SEMAPHORE = threading.BoundedSemaphore(_max_concurrent_calls())


class _TokenBucket:
    """Process-wide requests-per-minute gate. Smooths bursts so the instantaneous
    request rate stays under the Vertex Gemini quota — avoiding 429s (and the
    multi-minute reactive backoff they cause) instead of just absorbing them."""

    def __init__(self, rpm: int) -> None:
        self.rpm = rpm
        self.capacity = float(rpm)
        self.tokens = float(rpm)
        self.refill_per_sec = rpm / 60.0 if rpm > 0 else 0.0
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        if self.rpm <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity, self.tokens + (now - self.last) * self.refill_per_sec
                )
                self.last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.refill_per_sec
            time.sleep(min(max(wait, 0.01), 2.0))


_RATE_BUCKET = _TokenBucket(_max_rpm())


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(
        marker in text
        for marker in (
            "429",
            "resource_exhausted",
            "resourceexhausted",
            "rate limit",
            "ratelimit",
            "too many requests",
            "quota",
        )
    )


def generate_content_limited(
    client: Any,
    *,
    model: str,
    contents: Any,
    config: Any,
) -> Any:
    """Run client.models.generate_content under a process-wide concurrency cap,
    retrying on 429 / RESOURCE_EXHAUSTED with exponential backoff + jitter so a
    burst never surfaces as an error."""
    retries = _max_retries()
    backoff_max = _backoff_max_seconds()
    last_exc: BaseException | None = None

    for attempt in range(retries + 1):
        # Proactively pace to stay under the per-minute quota before we even
        # take a concurrency slot (no-op when GEMINI_MAX_RPM is unset).
        _RATE_BUCKET.acquire()
        with _SEMAPHORE:
            try:
                return client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _is_rate_limit_error(exc) or attempt >= retries:
                    raise
        # Back off OUTSIDE the semaphore so the slot is free while we wait.
        delay = min(backoff_max, 1.5 * (2 ** attempt)) + random.uniform(0.0, 1.0)
        print(
            f"[GEMINI] rate limited (attempt {attempt + 1}/{retries}); "
            f"backing off {delay:.1f}s",
            flush=True,
        )
        time.sleep(delay)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("generate_content_limited: exhausted retries")
