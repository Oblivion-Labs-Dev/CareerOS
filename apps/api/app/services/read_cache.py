"""Stale-while-revalidate cache for expensive read endpoints.

CareerOS's dashboard reads are aggregates over large blobs and whole tables.
Recomputing them on the request path made switching pages take about a second.
None of these numbers has to be exact at the instant it is rendered, so they are
served from here instead: a cached value is returned immediately, and when it is
older than its TTL a refresh is kicked off in the background. The request never
waits for that refresh.

Only the very first call for a key is synchronous, because there is nothing to
serve yet. Everything after that is a dictionary lookup.

Loaders run on a background thread and must therefore open their own database
session — a SQLAlchemy Session belongs to the thread that created it.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("career_os.read_cache")


@dataclass
class _Entry:
    value: Any
    refreshed_at: float
    refreshing: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class ReadCache:
    """Process-local cache. Not shared between workers, which is fine: every
    entry is derived state that any worker can rebuild from the database."""

    def __init__(self, max_workers: int = 2) -> None:
        self._entries: dict[str, _Entry] = {}
        self._guard = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="read-cache")

    def get(self, key: str, ttl_seconds: float, loader: Callable[[], Any]) -> Any:
        """Return the cached value, refreshing in the background when stale."""
        with self._guard:
            entry = self._entries.get(key)

        if entry is None:
            # Cold start: nothing to serve, so this one call pays the cost.
            value = loader()
            with self._guard:
                self._entries[key] = _Entry(value=value, refreshed_at=time.monotonic())
            return value

        if time.monotonic() - entry.refreshed_at > ttl_seconds:
            self._schedule_refresh(key, entry, loader)
        return entry.value

    def invalidate(self, key: str) -> None:
        """Drop an entry so the next read rebuilds it synchronously."""
        with self._guard:
            self._entries.pop(key, None)

    def _schedule_refresh(self, key: str, entry: _Entry, loader: Callable[[], Any]) -> None:
        # One refresh at a time per key: a burst of page loads must not queue up
        # a dozen identical rebuilds of the same expensive aggregate.
        with entry.lock:
            if entry.refreshing:
                return
            entry.refreshing = True

        def _run() -> None:
            try:
                value = loader()
                with self._guard:
                    self._entries[key] = _Entry(value=value, refreshed_at=time.monotonic())
            except Exception:
                # A failed refresh must never take out the endpoint. Keep serving
                # the previous value and let the next request try again; only mark
                # it stale so the retry is not suppressed.
                logger.warning("Background refresh failed for %r; serving stale value", key, exc_info=True)
                entry.refreshed_at = time.monotonic()
            finally:
                entry.refreshing = False

        self._pool.submit(_run)


read_cache = ReadCache()
