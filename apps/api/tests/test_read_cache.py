"""Regression test for a real production incident (2026-09-15): right after every dev
server restart, a burst of concurrent requests for the same cold cache key each ran the
expensive loader independently instead of sharing one result — under real load this
saturated the DB connection pool and starved the Autopilot batch loop's own heartbeat/job
claiming for several minutes, twice in a row.
"""

from __future__ import annotations

import threading
import time

from app.services.read_cache import ReadCache


def test_concurrent_cold_start_calls_loader_once() -> None:
    call_count = 0
    lock = threading.Lock()

    def expensive_loader() -> str:
        nonlocal call_count
        with lock:
            call_count += 1
        time.sleep(0.05)
        return "value"

    cache = ReadCache()
    threads = [threading.Thread(target=lambda: cache.get("k", 60.0, expensive_loader)) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count == 1


def test_cold_start_all_threads_get_the_same_value() -> None:
    cache = ReadCache()
    results: list[str] = []
    results_lock = threading.Lock()

    def loader() -> str:
        time.sleep(0.05)
        return "the-value"

    def worker() -> None:
        value = cache.get("k2", 60.0, loader)
        with results_lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["the-value"] * 10


def test_different_keys_do_not_serialize_on_the_same_lock() -> None:
    cache = ReadCache()
    started = threading.Event()

    def slow_loader_a() -> str:
        started.set()
        time.sleep(0.3)
        return "a"

    def loader_b() -> str:
        # Must not have to wait for the slow key-"a" loader to finish.
        return "b"

    t = threading.Thread(target=lambda: cache.get("a", 60.0, slow_loader_a))
    t.start()
    started.wait(timeout=1)

    start = time.monotonic()
    value = cache.get("b", 60.0, loader_b)
    elapsed = time.monotonic() - start

    assert value == "b"
    assert elapsed < 0.2
    t.join()


def test_touch_keeps_serving_last_value_without_blocking() -> None:
    """`touch` (unlike `invalidate`) must never make the next `get()` pay a
    synchronous rebuild — that regression is exactly what made every
    Autopilot dashboard click slow while a batch loop was writing every few
    seconds (2026-09-16)."""
    cache = ReadCache()
    cache.get("k3", 60.0, lambda: "v1")

    cache.touch("k3")

    start = time.monotonic()
    value = cache.get("k3", 60.0, lambda: "v2")
    elapsed = time.monotonic() - start

    assert value == "v1"  # last-known value, served instantly
    assert elapsed < 0.05


def test_touch_on_missing_key_is_a_safe_no_op() -> None:
    cache = ReadCache()
    cache.touch("never-cached")  # must not raise
    assert cache.get("never-cached", 60.0, lambda: "fresh") == "fresh"


def test_touch_with_loader_refreshes_in_background() -> None:
    cache = ReadCache()
    cache.get("k4", 60.0, lambda: "v1")

    done = threading.Event()

    def slow_loader() -> str:
        time.sleep(0.05)
        done.set()
        return "v2"

    cache.touch("k4", slow_loader)
    assert cache.get("k4", 60.0, lambda: "unused") == "v1"  # not blocked

    assert done.wait(timeout=1)
    assert cache.get("k4", 60.0, lambda: "unused") == "v2"
