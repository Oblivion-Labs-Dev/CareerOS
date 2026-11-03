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
from collections import OrderedDict
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

    def __init__(self, max_workers: int = 2, max_entries: int = 128) -> None:
        # Bounded, least-recently-used. Entries were previously never evicted,
        # so every distinct key held its value for the life of the process -
        # fine for the handful of dashboard aggregates in use today, but an
        # unbounded dict keyed by anything request-derived is a slow leak.
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._max_entries = max_entries
        self._guard = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="read-cache")
        # One creation lock per key, so a burst of concurrent cold-start callers for the
        # same key (the common case right after a restart, when every entry is empty and
        # several requests land before any of them finishes populating it) serializes on
        # the first one actually running the loader instead of each paying the full cost
        # independently. Small, fixed key set (a handful of dashboard aggregates) so this
        # dict is never cleaned up - same tradeoff the module docstring already accepts.
        self._creation_locks: dict[str, threading.Lock] = {}

    def _get_creation_lock(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._creation_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._creation_locks[key] = lock
            return lock

    def get(self, key: str, ttl_seconds: float, loader: Callable[[], Any]) -> Any:
        """Return the cached value, refreshing in the background when stale."""
        with self._guard:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)

        if entry is None:
            # Cold start: serialize on a per-key lock so only the first concurrent
            # caller actually runs the (expensive) loader; everyone else blocks
            # briefly and then finds the entry already populated.
            with self._get_creation_lock(key):
                with self._guard:
                    entry = self._entries.get(key)
                if entry is not None:
                    return entry.value
                value = loader()
                with self._guard:
                    self._entries[key] = _Entry(value=value, refreshed_at=time.monotonic())
                    self._entries.move_to_end(key)
                    self._evict_locked()
                return value

        if time.monotonic() - entry.refreshed_at > ttl_seconds:
            self._schedule_refresh(key, entry, loader)
        return entry.value

    def _evict_locked(self) -> None:
        """Drop least-recently-used entries. Caller must hold the guard."""
        while len(self._entries) > self._max_entries:
            evicted_key, _ = self._entries.popitem(last=False)
            logger.debug("read cache evicted %r", evicted_key)

    def invalidate(self, key: str) -> None:
        """Drop an entry so the next read rebuilds it synchronously."""
        with self._guard:
            self._entries.pop(key, None)

    def touch(self, key: str, loader: Callable[[], Any] | None = None) -> None:
        """Mark an entry stale without evicting it.

        Unlike ``invalidate``, the next ``get()`` still returns the last-known
        value immediately (a background refresh is kicked off, same as an
        ordinary TTL expiry) instead of blocking on a synchronous rebuild.
        Use this for invalidations that fire at high frequency from a
        background process (e.g. a batch loop saving a row every few
        seconds) — evicting on every one of those turns the cache cold for
        every viewer, not just the writer, which is what a plain
        ``invalidate`` is for. If a ``loader`` is given and the key is
        already cached, the refresh is scheduled right away rather than
        waiting for the next ``get()`` to notice it is stale, so a request
        landing shortly after almost always finds a warm value.
        A key with no existing entry is a no-op: there is nothing to keep
        warm, and the next ``get()`` will populate it normally.
        """
        with self._guard:
            entry = self._entries.get(key)
        if entry is None:
            return
        entry.refreshed_at = 0.0
        if loader is not None:
            self._schedule_refresh(key, entry, loader)

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
                    self._entries.move_to_end(key)
                    self._evict_locked()
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
