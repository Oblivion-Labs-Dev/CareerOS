"""Settings for the Gemini enrichment layer.

Deliberately conservative. Gemini is an optional intelligence layer bolted onto
a system that already works without it, so every default is chosen so that
turning Gemini on cannot make CareerOS worse: one request at a time, generous
spacing between calls, a short retry budget, and a circuit that opens quickly.

Every value is overridable by environment variable, because the right numbers
depend on which Gemini tier the key is on and that is not knowable from here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "off", "false", "no")


#: OpenAI-compatible surface. The native Gemini API differs in how structured
#: output is requested, and CareerOS already speaks the OpenAI dialect
#: everywhere else, so there is nothing to gain from the native one.
BASE_URL = os.environ.get(
    "CAREEROS_GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai",
)

#: flash-lite rather than flash: the free tier's daily quota on
#: `gemini-flash-latest` was exhausted part way through a 140-posting labelling
#: run, while flash-lite has a separate and much larger allowance. Every task
#: here has a fixed schema and a short output, which is what lite is good at.
MODEL = os.environ.get("CAREEROS_GEMINI_MODEL", "gemini-flash-lite-latest")


def api_key() -> str:
    """The key, from the environment or the app settings, or "" when unset.

    Read on every call rather than captured at import, so a key added to
    `.env` and picked up by a reload takes effect without a restart.
    """
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if key:
        return key
    try:
        from app.config import settings

        return (settings.gemini_api_key or "").strip()
    except Exception:  # noqa: BLE001 - config import must never break a call site
        return ""


def applications_enabled() -> bool:
    """Whether Gemini may be used while applying to a job.

    The job-application path - answering screening questions, the match gate
    that decides whether a posting is worth submitting, and per-application
    resume tailoring - is deliberately separated from the job-discovery
    enrichment layer. Discovery is offline, batched and cheap to retry, so a
    wrong or missing answer there costs nothing. An application is sent once to
    a real employer, so the user wants that path answered from their own
    recorded profile and evidence, not from a hosted model.

    Off unless ``CAREEROS_GEMINI_APPLICATIONS`` explicitly turns it on.
    ``CAREEROS_GEMINI_ENABLED`` still governs discovery enrichment, and turning
    that off disables both.
    """
    return _env_flag("CAREEROS_GEMINI_ENABLED", True) and _env_flag(
        "CAREEROS_GEMINI_APPLICATIONS", False
    )


@dataclass(frozen=True)
class GeminiConfig:
    enabled: bool
    model: str
    base_url: str
    concurrency: int
    min_interval_seconds: float
    timeout_seconds: float
    max_attempts: int
    failure_threshold: int
    cooldown_seconds: float
    max_cooldown_seconds: float
    queue_max: int
    cache_enabled: bool
    #: USD per million tokens, for the estimate shown in diagnostics. The free
    #: tier bills nothing; these are the paid-tier rates so the number means
    #: "what this would have cost" rather than nothing at all.
    price_in_per_mtok: float
    price_out_per_mtok: float

    @property
    def configured(self) -> bool:
        return bool(api_key())


def load() -> GeminiConfig:
    return GeminiConfig(
        enabled=_env_flag("CAREEROS_GEMINI_ENABLED", True),
        model=MODEL,
        base_url=BASE_URL,
        # One in flight. The free tier rate-limits on requests per minute, and a
        # second concurrent request buys nothing but a faster path to a 429.
        concurrency=max(1, _env_int("CAREEROS_GEMINI_CONCURRENCY", 1)),
        min_interval_seconds=_env_float("CAREEROS_GEMINI_MIN_INTERVAL_SECONDS", 2.5),
        timeout_seconds=_env_float("CAREEROS_GEMINI_TIMEOUT_SECONDS", 45.0),
        # Four attempts at 2s/4s/8s spans about fifteen seconds of backoff,
        # which clears a burst limit without making an interactive caller wait
        # minutes for an answer it has a deterministic fallback for.
        max_attempts=max(1, _env_int("CAREEROS_GEMINI_MAX_ATTEMPTS", 4)),
        failure_threshold=max(1, _env_int("CAREEROS_GEMINI_FAILURE_THRESHOLD", 4)),
        cooldown_seconds=_env_float("CAREEROS_GEMINI_COOLDOWN_SECONDS", 300.0),
        max_cooldown_seconds=_env_float("CAREEROS_GEMINI_MAX_COOLDOWN_SECONDS", 900.0),
        queue_max=_env_int("CAREEROS_GEMINI_QUEUE_MAX", 2000),
        cache_enabled=_env_flag("CAREEROS_GEMINI_CACHE", True),
        price_in_per_mtok=_env_float("CAREEROS_GEMINI_PRICE_IN", 0.10),
        price_out_per_mtok=_env_float("CAREEROS_GEMINI_PRICE_OUT", 0.40),
    )
