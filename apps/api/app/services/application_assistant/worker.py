"""Background worker for long-running Application Assistant operations."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Coroutine

from sqlalchemy.orm import Session

from app.db.store import session_scope

_tasks: dict[str, asyncio.Task] = {}
_locks: dict[str, asyncio.Lock] = {}

MAX_CONCURRENT_PREP = max(1, int(os.getenv("AA_MAX_CONCURRENT_PREP", "10")))
MAX_PREP_QUEUE = max(MAX_CONCURRENT_PREP, int(os.getenv("AA_MAX_PREP_QUEUE", "20")))

_prep_semaphore: asyncio.Semaphore | None = None
_prep_slots: set[str] = set()
_prep_active: set[str] = set()
_prep_admission_lock: asyncio.Lock | None = None


def _get_prep_semaphore() -> asyncio.Semaphore:
    global _prep_semaphore
    if _prep_semaphore is None:
        _prep_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PREP)
    return _prep_semaphore


def _get_prep_admission_lock() -> asyncio.Lock:
    global _prep_admission_lock
    if _prep_admission_lock is None:
        _prep_admission_lock = asyncio.Lock()
    return _prep_admission_lock


def is_prep_task_running(app_id: str) -> bool:
    return task_status(f"qwen_prep_{app_id}") == "running"


def prep_queue_status() -> dict[str, Any]:
    from app.services.application_assistant.browser_runner import list_active_session_ids

    queued = len(_prep_slots)
    running = len(_prep_active)
    open_browsers = list_active_session_ids()
    return {
        "maxConcurrent": MAX_CONCURRENT_PREP,
        "maxQueue": MAX_PREP_QUEUE,
        "running": running,
        "waiting": max(0, queued - running),
        "queued": queued,
        "available": max(0, MAX_PREP_QUEUE - queued),
        "activeApplicationIds": sorted(_prep_active),
        "queuedApplicationIds": sorted(_prep_slots),
        "openBrowserCount": len(open_browsers),
        "openBrowserApplicationIds": open_browsers,
    }


async def try_admit_prep(app_id: str) -> bool:
    lock = _get_prep_admission_lock()
    async with lock:
        if app_id in _prep_slots:
            return True
        if len(_prep_slots) >= MAX_PREP_QUEUE:
            return False
        _prep_slots.add(app_id)
        return True


async def release_prep_slot(app_id: str) -> None:
    lock = _get_prep_admission_lock()
    async with lock:
        _prep_slots.discard(app_id)
        _prep_active.discard(app_id)


async def run_queued_prep(app_id: str, coro: Coroutine[Any, Any, Any]) -> None:
    try:
        async with _get_prep_semaphore():
            _prep_active.add(app_id)
            try:
                await coro
            finally:
                _prep_active.discard(app_id)
    finally:
        await release_prep_slot(app_id)


def get_app_lock(app_id: str) -> asyncio.Lock:
    if app_id not in _locks:
        _locks[app_id] = asyncio.Lock()
    return _locks[app_id]


def is_app_locked(app_id: str) -> bool:
    lock = _locks.get(app_id)
    return lock is not None and lock.locked()


async def run_in_background(
    task_id: str,
    coro: Coroutine[Any, Any, Any],
) -> None:
    """Run a coroutine in the background, tracking by task_id."""
    if task_id in _tasks and not _tasks[task_id].done():
        return  # Prevent duplicate runs

    async def _wrapper() -> None:
        try:
            await coro
        except Exception as exc:
            from app.services.application_assistant.qwen_activity import log_activity_event

            log_activity_event(
                event_type="agent_error",
                summary=f"Background task failed: {exc}",
                success=False,
                error=str(exc),
                metadata={"taskId": task_id},
            )
        finally:
            _tasks.pop(task_id, None)

    _tasks[task_id] = asyncio.create_task(_wrapper())


def cancel_task(task_id: str) -> bool:
    task = _tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def task_status(task_id: str) -> str:
    task = _tasks.get(task_id)
    if not task:
        return "not_found"
    if task.done():
        if task.cancelled():
            return "cancelled"
        if task.exception():
            return "failed"
        return "completed"
    return "running"


async def with_app_lock(app_id: str, fn: Callable[[Session], Coroutine[Any, Any, Any]]) -> Any:
    """Execute function with application-level lock to prevent concurrent mutation."""
    lock = get_app_lock(app_id)
    async with lock:
        with session_scope() as db:
            return await fn(db)
