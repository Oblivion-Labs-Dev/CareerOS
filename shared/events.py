"""A tiny in-process pub/sub bus for inter-service communication.

Services that must react to something another service did subscribe with
``@on("event.name")`` and the publisher calls ``await emit("event.name",
payload)``. This keeps the two services decoupled: the publisher never imports
the subscriber. When a service is later lifted into its own process the bus is
swapped for a real message queue and nothing else changes.

Handlers may be sync or async. ``emit`` awaits async handlers and calls sync
ones directly. A failing handler is logged and skipped so one bad subscriber
cannot break the publisher or the other subscribers.
"""

import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

_logger = logging.getLogger("shared.events")

Handler = Callable[[dict[str, Any]], Awaitable[None] | None]

_handlers: dict[str, list[Handler]] = defaultdict(list)


def on(event: str) -> Callable[[Handler], Handler]:
    """Register ``handler`` as a subscriber for ``event``. Usable as a decorator."""

    def _register(handler: Handler) -> Handler:
        _handlers[event].append(handler)
        return handler

    return _register


def subscribe(event: str, handler: Handler) -> None:
    """Imperative form of :func:`on` for non-decorator call sites."""
    _handlers[event].append(handler)


async def emit(event: str, payload: dict[str, Any] | None = None) -> None:
    """Deliver ``payload`` to every handler registered for ``event``."""
    data = payload or {}
    for handler in list(_handlers.get(event, ())):
        try:
            result = handler(data)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - one bad subscriber must not break the publisher
            _logger.exception("Event handler for %r failed", event)


def clear() -> None:
    """Drop every subscription. Intended for tests."""
    _handlers.clear()
