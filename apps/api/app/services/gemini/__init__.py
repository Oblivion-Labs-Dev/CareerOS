"""Gemini as an optional intelligence layer over CareerOS's deterministic core.

CareerOS decides everything it can deterministically: profile fields are looked
up, job postings are scored by code, resumes are assembled from a verified
corpus. That path runs in milliseconds, needs no model resident, and works with
no network at all. Gemini sits beside it and is consulted only where a language
model genuinely knows something the deterministic path does not - open-ended
application prose, wording a bullet toward a posting, and the postings the
matcher itself reports it cannot classify.

The layer is built around one invariant:

    Gemini being unavailable can never take CareerOS down.

Every call goes through `gateway.submit()`, which never raises and returns
`ok=False` for every kind of failure. Every caller treats `ok=False` as the
normal path and continues deterministically. Nothing here is load-bearing.
"""

from app.services.gemini.gateway import (  # noqa: F401
    GeminiRequest,
    GeminiResult,
    Outcome,
    Priority,
    get_gateway,
    reset_gateway,
)

# The telemetry *object* is deliberately not re-exported here. Binding the name
# `telemetry` in the package namespace would shadow the `telemetry` submodule,
# so `from app.services.gemini import telemetry` would hand back the counters
# object instead of the module. Import it from its own module.

__all__ = [
    "GeminiRequest",
    "GeminiResult",
    "Outcome",
    "Priority",
    "get_gateway",
    "reset_gateway",
]
