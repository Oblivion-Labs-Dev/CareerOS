"""The one place CareerOS talks to Gemini.

Nothing else in the codebase may hold a Gemini HTTP client. Every enrichment
goes through `gateway.submit()`, and the gateway owns the parts that are easy
to get wrong once and impossible to get right in five places: rate limiting,
priority, retries, the circuit breaker, the cache, request dedupe, schema
validation and telemetry.

The contract the rest of CareerOS relies on is narrow and absolute:

    submit() always returns a GeminiResult, and never raises.

A result with `ok=False` is not an error condition to be handled specially - it
is the normal, expected outcome whenever Gemini is rate limited, down,
misconfigured, disabled, or simply not worth waiting for. Every caller has a
deterministic path, and `ok=False` means "take it". That is what keeps Gemini an
enhancement rather than a dependency.

## Priority

Work is ordered, not just queued. An application that is open in an employer's
form right now outranks a resume tailoring job, which outranks a speculative
match clarification, which outranks offline benchmark labelling. Without this,
a MatchLab run enqueuing three hundred postings would put an interactive
application behind twenty minutes of rate-limited batch work.

## Failure handling

The three failures actually observed against this API are handled differently,
because they mean different things:

* **429** is "you are going too fast" - back off, honour `Retry-After`, retry.
* **503** is "try again shortly" - back off, retry, and give up sooner.
* **404** is "this model or endpoint does not exist" - a configuration problem
  that no amount of retrying will fix. Retrying it is how you turn a typo into a
  retry storm, so it fails immediately and opens the circuit for a long cooldown.

Anything else in the 4xx range (bad request, bad key, forbidden) fails fast with
the reason logged. Malformed output is its own case: it is not an availability
problem, so it costs one retry but never counts toward opening the circuit.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

from app.services.gemini import config as gemini_config
from app.services.gemini.telemetry import read_circuit, telemetry, write_circuit
from app.services.gemini.validation import validate

logger = logging.getLogger("careeros.gemini")

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "gemini_cache"


class Priority(IntEnum):
    """Lower runs first. The ordering is the user-facing promise of this layer.

    ACTIVE_APPLICATION is for work blocking a form that is open right now;
    BENCHMARK_LABEL is offline work that may wait indefinitely and must never
    delay anything above it.
    """

    ACTIVE_APPLICATION = 0
    APPLICATION_QUESTION = 1
    RESUME_TAILORING = 2
    AMBIGUOUS_MATCH = 3
    BENCHMARK_LABEL = 4


class Outcome(str, Enum):
    OK = "ok"
    CACHED = "cached"
    DISABLED = "disabled"            # no key, or switched off
    CIRCUIT_OPEN = "circuit_open"
    RATE_LIMITED = "rate_limited"    # 429, retries exhausted
    TRANSIENT = "transient"          # 5xx, retries exhausted
    TIMEOUT = "timeout"
    CONFIG_ERROR = "config_error"    # 404: wrong model or endpoint
    PERMANENT = "permanent"          # other 4xx
    MALFORMED = "malformed"          # parsed, but did not match the schema
    QUEUE_FULL = "queue_full"


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


#: Availability failures. Only these move the circuit breaker - a malformed
#: reply means Gemini answered, which is the opposite of being down.
_AVAILABILITY_FAILURES = {
    Outcome.RATE_LIMITED,
    Outcome.TRANSIENT,
    Outcome.TIMEOUT,
    Outcome.CONFIG_ERROR,
}


@dataclass
class GeminiRequest:
    """One unit of work. `task` groups telemetry; `cache_parts` decides identity."""

    task: str
    system: str
    prompt: str
    schema: dict[str, Any]
    priority: Priority = Priority.AMBIGUOUS_MATCH
    schema_name: str = "structured_response"
    #: Bumped by the caller when the prompt or schema changes, so a cached answer
    #: to a different question is never silently reused.
    prompt_version: str = "v1"
    #: Extra identity beyond the prompt text: resume version, evidence version,
    #: normalised JD hash. Anything that should invalidate the cache when it
    #: changes but does not appear verbatim in the prompt.
    cache_parts: tuple[str, ...] = ()
    temperature: float = 0.0
    max_tokens: int = 900
    #: Offline work may wait for the circuit to close instead of failing. Never
    #: set this for anything a user or an application is waiting on.
    wait_for_circuit: bool = False
    #: Give up entirely after this long, queue time included.
    deadline_seconds: float = 180.0


@dataclass
class GeminiResult:
    ok: bool
    outcome: Outcome
    data: dict[str, Any] | None = None
    detail: str = ""
    cached: bool = False
    latency_ms: float = 0.0
    attempts: int = 0
    queued_ms: float = 0.0

    @property
    def unavailable(self) -> bool:
        """True when Gemini did not answer, for any reason. The fallback signal."""
        return not self.ok


@dataclass
class RawReply:
    """What the transport saw. Deliberately not an httpx type, so tests can fake it."""

    status: int = 0
    body: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    timed_out: bool = False


Transport = Callable[[dict[str, Any], float], Awaitable[RawReply]]


async def _httpx_transport(payload: dict[str, Any], timeout: float) -> RawReply:
    import httpx

    config = gemini_config.load()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {gemini_config.api_key()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        body: dict[str, Any] | None
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - an error page is not JSON
            body = None
        return RawReply(
            status=response.status_code,
            body=body,
            headers={k.lower(): v for k, v in response.headers.items()},
        )
    except httpx.TimeoutException as exc:
        return RawReply(error=f"{type(exc).__name__}", timed_out=True)
    except Exception as exc:  # noqa: BLE001 - connection errors are transient
        return RawReply(error=f"{type(exc).__name__}: {str(exc)[:120]}")


class CircuitBreaker:
    """Open after repeated availability failures; probe once before restoring.

    State is mirrored to disk so the API process and the Playwright worker
    process share one view. Without that, each process would have to discover
    an outage independently, which is exactly the redundant traffic the breaker
    exists to prevent.
    """

    def __init__(self, config: gemini_config.GeminiConfig) -> None:
        self._config = config
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = 0.0
        self._cooldown = config.cooldown_seconds
        self._reason = ""
        self._probe_in_flight = False
        self._last_disk_read = 0.0

    # ── shared state ─────────────────────────────────────────────────────────

    def _sync_from_disk(self) -> None:
        from app.services.gemini.telemetry import CIRCUIT_REFRESH_SECONDS

        now = time.time()
        if now - self._last_disk_read < CIRCUIT_REFRESH_SECONDS:
            return
        self._last_disk_read = now
        state = read_circuit()
        if not state:
            return
        opened_at = float(state.get("openedAt") or 0.0)
        # Only adopt a *newer* outage than the one this process knows about.
        # Adopting an older record would reopen a circuit this process has
        # already probed back to healthy.
        if state.get("state") == CircuitState.OPEN.value and opened_at > self._opened_at:
            self._state = CircuitState.OPEN
            self._opened_at = opened_at
            self._cooldown = float(state.get("cooldown") or self._config.cooldown_seconds)
            self._reason = str(state.get("reason") or "")
            self._failures = int(state.get("failures") or self._config.failure_threshold)

    def _publish(self) -> None:
        write_circuit({
            "state": self._state.value,
            "openedAt": self._opened_at,
            "cooldown": self._cooldown,
            "reason": self._reason,
            "failures": self._failures,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    # ── decisions ────────────────────────────────────────────────────────────

    def allows(self) -> bool:
        """May a call go out now? Moves OPEN to HALF_OPEN when the cooldown ends."""
        self._sync_from_disk()
        if self._state is CircuitState.CLOSED:
            return True
        if self._state is CircuitState.OPEN:
            if time.time() - self._opened_at < self._cooldown:
                return False
            # Cooldown elapsed: let exactly one request through to find out
            # whether the far side has recovered.
            self._state = CircuitState.HALF_OPEN
            self._probe_in_flight = False
            self._publish()
            logger.info("Gemini circuit half-open; probing")
        if self._state is CircuitState.HALF_OPEN:
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True
        return True

    @property
    def consecutive_failures(self) -> int:
        return self._failures

    def seconds_until_retry(self) -> float:
        if self._state is not CircuitState.OPEN:
            return 0.0
        return max(0.0, self._cooldown - (time.time() - self._opened_at))

    def record_success(self) -> None:
        was = self._state
        self._failures = 0
        self._probe_in_flight = False
        self._cooldown = self._config.cooldown_seconds
        self._state = CircuitState.CLOSED
        self._reason = ""
        if was is not CircuitState.CLOSED:
            logger.info("Gemini circuit closed after a successful probe")
            self._publish()

    def record_failure(self, outcome: Outcome, detail: str) -> None:
        if outcome not in _AVAILABILITY_FAILURES:
            return
        self._failures += 1
        self._probe_in_flight = False

        # A 404 is a configuration fault, not an outage. Retrying it on a timer
        # is a retry storm against a URL that will never work, so it opens the
        # circuit immediately and for the longest cooldown available.
        immediate = outcome is Outcome.CONFIG_ERROR
        reopening = self._state is CircuitState.HALF_OPEN

        if immediate or reopening or self._failures >= self._config.failure_threshold:
            if reopening:
                # The probe failed: wait longer before the next one.
                self._cooldown = min(self._cooldown * 2, self._config.max_cooldown_seconds)
            elif immediate:
                self._cooldown = self._config.max_cooldown_seconds
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
            self._reason = f"{outcome.value}: {detail}"[:200]
            self._publish()
            logger.warning(
                "Gemini circuit OPEN for %.0fs after %d failure(s): %s",
                self._cooldown, self._failures, self._reason,
            )

    def snapshot(self) -> dict[str, Any]:
        self._sync_from_disk()
        state = self._state
        if state is CircuitState.OPEN and time.time() - self._opened_at >= self._cooldown:
            state = CircuitState.HALF_OPEN
        return {
            "state": state.value,
            "consecutiveFailures": self._failures,
            "cooldownSeconds": round(self._cooldown, 1),
            "secondsUntilRetry": round(self.seconds_until_retry(), 1),
            "reason": self._reason,
        }


@dataclass(order=True)
class _QueueItem:
    priority: int
    sequence: int
    request: GeminiRequest = field(compare=False)
    future: asyncio.Future = field(compare=False)
    enqueued_at: float = field(compare=False, default_factory=time.monotonic)


class GeminiGateway:
    """Single entry point. One instance per process; see `get_gateway()`."""

    def __init__(self, config: gemini_config.GeminiConfig | None = None) -> None:
        self.config = config or gemini_config.load()
        self.breaker = CircuitBreaker(self.config)
        self.transport: Transport = _httpx_transport
        self._queue: asyncio.PriorityQueue[_QueueItem] | None = None
        self._workers: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sequence = itertools.count()
        self._last_call_at = 0.0
        self._pace_lock: asyncio.Lock | None = None
        self._inflight: dict[str, asyncio.Future] = {}
        self._depth_by_priority: dict[int, int] = {}

    # ── availability ─────────────────────────────────────────────────────────

    @property
    def configured(self) -> bool:
        return bool(gemini_config.api_key())

    @property
    def enabled(self) -> bool:
        return self.config.enabled and self.configured

    def health(self) -> str:
        """One word for the diagnostics header."""
        if not self.enabled:
            return "DISABLED"
        state = self.breaker.snapshot()["state"]
        if state == CircuitState.OPEN.value:
            return "CIRCUIT OPEN"
        if telemetry.rate_limited and self.breaker.consecutive_failures:
            return "RATE LIMITED"
        return "HEALTHY"

    # ── submission ───────────────────────────────────────────────────────────

    async def submit(self, request: GeminiRequest) -> GeminiResult:
        """Run one enrichment. Never raises; `ok=False` means "use your fallback"."""
        telemetry.record_request(request.task)

        if not self.enabled:
            reason = "GEMINI_API_KEY is not configured" if not self.configured else "Gemini is switched off"
            return GeminiResult(ok=False, outcome=Outcome.DISABLED, detail=reason)

        key = self._cache_key(request)
        cached = self._read_cache(key)
        if cached is not None:
            telemetry.record_cache_hit(request.task)
            return GeminiResult(ok=True, outcome=Outcome.CACHED, data=cached, cached=True)

        self._ensure_workers()
        assert self._queue is not None

        # Request dedupe: two callers asking the identical question at the same
        # moment share one API call. Without this, a batch that re-enqueues the
        # same posting twice pays twice before either writes the cache.
        existing = self._inflight.get(key)
        if existing is not None:
            telemetry.record_cache_hit(request.task, deduped=True)
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(existing), timeout=request.deadline_seconds
                )
                return GeminiResult(
                    ok=result.ok, outcome=result.outcome, data=result.data,
                    detail=result.detail, cached=True,
                )
            except (TimeoutError, asyncio.CancelledError):
                return GeminiResult(ok=False, outcome=Outcome.TIMEOUT, detail="deduped request timed out")

        if self._queue.qsize() >= self.config.queue_max:
            telemetry.record_failure(request.task, "queue_full", "queue is at capacity")
            return GeminiResult(ok=False, outcome=Outcome.QUEUE_FULL, detail="Gemini queue is full")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[GeminiResult] = loop.create_future()
        self._inflight[key] = future
        # Clear the dedupe slot when the work finishes, whoever is still
        # waiting. Doing it only in the caller's `finally` leaked an entry
        # every time a caller hit its deadline before the worker was done.
        future.add_done_callback(
            lambda _f, k=key: self._inflight.pop(k, None)
            if self._inflight.get(k) is _f else None
        )
        item = _QueueItem(int(request.priority), next(self._sequence), request, future)
        self._depth_by_priority[item.priority] = self._depth_by_priority.get(item.priority, 0) + 1
        await self._queue.put(item)

        try:
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=request.deadline_seconds
            )
        except TimeoutError:
            telemetry.record_failure(request.task, "timeout", "deadline exceeded in queue")
            return GeminiResult(ok=False, outcome=Outcome.TIMEOUT, detail="deadline exceeded")


    def submit_sync(self, request: GeminiRequest) -> GeminiResult:
        """For scripts and worker threads with no running event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.submit(request))
        raise RuntimeError("submit_sync() called from inside an event loop; await submit() instead")

    # ── workers ──────────────────────────────────────────────────────────────

    def _ensure_workers(self) -> None:
        """Start (or restart) the worker pool on the loop that is running now.

        The gateway is a process-wide singleton but an asyncio queue belongs to
        one loop, and tests, uvicorn reloads and the MatchLab scripts (which
        drive one `asyncio.run()` per posting) all create new ones. Rebinding
        here keeps the singleton usable instead of failing on a stale loop, and
        keeps the parts that must survive a rebind - the pacing clock and the
        circuit breaker - on the instance rather than in the loop.
        """
        loop = asyncio.get_running_loop()
        alive = [task for task in self._workers if not task.done()]
        if self._loop is loop and alive:
            self._workers = alive
            return
        for task in alive:
            # A task belonging to a loop that has since been closed cannot be
            # cancelled - `cancel()` schedules onto that loop and raises. Those
            # tasks died with their loop anyway, so dropping them is correct.
            try:
                task.cancel()
            except RuntimeError:
                pass
        self._loop = loop
        self._queue = asyncio.PriorityQueue()
        self._pace_lock = asyncio.Lock()
        self._depth_by_priority = {}
        self._workers = [
            loop.create_task(self._worker(index), name=f"gemini-worker-{index}")
            for index in range(self.config.concurrency)
        ]

    async def _worker(self, index: int) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            self._depth_by_priority[item.priority] = max(
                0, self._depth_by_priority.get(item.priority, 1) - 1
            )
            try:
                if item.future.done():  # the caller gave up while it waited
                    continue
                await self._dispatch(item)
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.set_result(
                        GeminiResult(ok=False, outcome=Outcome.TRANSIENT, detail="worker cancelled")
                    )
                raise
            except Exception as exc:  # noqa: BLE001 - a worker must never die
                logger.exception("Gemini worker %d failed", index)
                if not item.future.done():
                    item.future.set_result(
                        GeminiResult(ok=False, outcome=Outcome.TRANSIENT, detail=str(exc)[:160])
                    )
            finally:
                self._queue.task_done()

    async def _dispatch(self, item: _QueueItem) -> None:
        request = item.request
        queued_ms = (time.monotonic() - item.enqueued_at) * 1000

        if not self.breaker.allows():
            if request.wait_for_circuit and queued_ms / 1000 < request.deadline_seconds:
                # Offline work waits rather than failing. Re-queueing instead of
                # sleeping in place keeps the worker free, so an interactive
                # request arriving during the cooldown is still served the
                # moment the circuit closes.
                await asyncio.sleep(min(1.0, max(0.1, self.breaker.seconds_until_retry())))
                assert self._queue is not None
                self._depth_by_priority[item.priority] = self._depth_by_priority.get(item.priority, 0) + 1
                await self._queue.put(item)
                return
            telemetry.record_failure(request.task, Outcome.CIRCUIT_OPEN.value, self.breaker.snapshot()["reason"])
            item.future.set_result(GeminiResult(
                ok=False, outcome=Outcome.CIRCUIT_OPEN, queued_ms=queued_ms,
                detail=f"circuit open for another {self.breaker.seconds_until_retry():.0f}s",
            ))
            return

        # A second caller may have filled the cache while this one queued.
        key = self._cache_key(request)
        cached = self._read_cache(key)
        if cached is not None:
            telemetry.record_cache_hit(request.task)
            item.future.set_result(GeminiResult(
                ok=True, outcome=Outcome.CACHED, data=cached, cached=True, queued_ms=queued_ms
            ))
            return

        result = await self._execute(request)
        result.queued_ms = queued_ms
        if result.ok and result.data is not None:
            self._write_cache(key, request, result.data)
        item.future.set_result(result)

    # ── the call itself ──────────────────────────────────────────────────────

    async def _pace(self) -> None:
        """Keep at least `min_interval_seconds` between outbound calls."""
        assert self._pace_lock is not None
        async with self._pace_lock:
            wait = self.config.min_interval_seconds - (time.monotonic() - self._last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_at = time.monotonic()

    async def _execute(self, request: GeminiRequest) -> GeminiResult:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.schema,
                },
            },
        }

        backoff = 2.0
        malformed_retries = 0
        last_outcome = Outcome.TRANSIENT
        last_detail = "no attempt was made"

        for attempt in range(1, self.config.max_attempts + 1):
            await self._pace()
            started = time.perf_counter()
            reply = await self.transport(payload, self.config.timeout_seconds)
            elapsed_ms = (time.perf_counter() - started) * 1000

            outcome, detail = self._classify(reply)

            if outcome is Outcome.OK:
                parsed, problems = self._parse_and_validate(reply, request)
                if parsed is not None:
                    usage = (reply.body or {}).get("usage") or {}
                    telemetry.record_success(
                        request.task, elapsed_ms,
                        prompt_tokens=int(usage.get("prompt_tokens") or 0),
                        completion_tokens=int(usage.get("completion_tokens") or 0),
                    )
                    self.breaker.record_success()
                    return GeminiResult(
                        ok=True, outcome=Outcome.OK, data=parsed,
                        latency_ms=round(elapsed_ms, 1), attempts=attempt,
                    )
                # Gemini answered, so the service is up: the breaker is not
                # touched. One retry, because a reshuffled reply often parses
                # the second time; more than that is just burning quota.
                last_outcome, last_detail = Outcome.MALFORMED, "; ".join(problems)[:200]
                self.breaker.record_success()
                if malformed_retries < 1 and attempt < self.config.max_attempts:
                    malformed_retries += 1
                    telemetry.record_retry()
                    logger.warning("Gemini reply failed schema validation (%s); retrying", last_detail)
                    continue
                break

            last_outcome, last_detail = outcome, detail

            if outcome in (Outcome.CONFIG_ERROR, Outcome.PERMANENT):
                # Nothing to retry: the request itself is wrong.
                logger.error("Gemini %s: %s", outcome.value, detail)
                break

            if attempt >= self.config.max_attempts:
                break

            wait = self._retry_delay(reply, outcome, backoff)
            telemetry.record_retry()
            logger.info(
                "Gemini %s on %s (attempt %d/%d); retrying in %.1fs",
                outcome.value, request.task, attempt, self.config.max_attempts, wait,
            )
            await asyncio.sleep(wait)
            backoff = min(backoff * 2, 60.0)

        telemetry.record_failure(request.task, last_outcome.value, last_detail)
        self.breaker.record_failure(last_outcome, last_detail)
        return GeminiResult(
            ok=False, outcome=last_outcome, detail=last_detail,
            attempts=min(attempt, self.config.max_attempts),
        )

    def _retry_delay(self, reply: RawReply, outcome: Outcome, backoff: float) -> float:
        """Exponential backoff with jitter, overridden by Retry-After when sent.

        The jitter matters even at concurrency 1: the Playwright worker process
        runs its own gateway, and two processes backing off on identical timers
        retry in lockstep and hit the same limit together.
        """
        hinted = reply.headers.get("retry-after", "")
        if hinted:
            try:
                return min(float(hinted), 120.0)
            except ValueError:
                pass
        if outcome is Outcome.RATE_LIMITED:
            backoff = max(backoff, self.config.min_interval_seconds * 2)
        return backoff * (0.75 + random.random() * 0.5)

    @staticmethod
    def _classify(reply: RawReply) -> tuple[Outcome, str]:
        if reply.timed_out:
            return Outcome.TIMEOUT, reply.error or "request timed out"
        if reply.error:
            return Outcome.TRANSIENT, reply.error
        status = reply.status
        if 200 <= status < 300:
            return Outcome.OK, ""
        message = ""
        if isinstance(reply.body, dict):
            error = reply.body.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")[:200]
            elif error:
                message = str(error)[:200]
        if status == 429:
            return Outcome.RATE_LIMITED, message or "rate limited"
        if status == 404:
            return Outcome.CONFIG_ERROR, message or f"model {gemini_config.load().model!r} or endpoint not found"
        if status in (500, 502, 503, 504):
            return Outcome.TRANSIENT, message or f"HTTP {status}"
        if 400 <= status < 500:
            return Outcome.PERMANENT, message or f"HTTP {status}"
        return Outcome.TRANSIENT, message or f"HTTP {status}"

    def _parse_and_validate(
        self, reply: RawReply, request: GeminiRequest
    ) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            content = reply.body["choices"][0]["message"]["content"]  # type: ignore[index]
        except Exception:  # noqa: BLE001
            return None, ["reply had no message content"]
        parsed = _extract_json(str(content or ""))
        if parsed is None:
            return None, ["reply was not JSON"]
        problems = validate(parsed, request.schema)
        if problems:
            return None, problems
        return parsed, []

    # ── cache ────────────────────────────────────────────────────────────────

    def _cache_key(self, request: GeminiRequest) -> str:
        """Stable identity for a unit of work.

        Everything that changes the answer is in the key: the task, the model,
        the prompt and schema versions, the decoding settings, and whatever the
        caller declared through `cache_parts` (resume version, evidence version,
        normalised JD hash). Change any of them and the old answer is not
        reused - which is the point, because a cached answer to a superseded
        prompt is worse than no cache at all.
        """
        digest = hashlib.sha256()
        for part in (
            request.task,
            self.config.model,
            request.prompt_version,
            json.dumps(request.schema, sort_keys=True),
            f"{request.temperature}",
            request.system,
            request.prompt,
            *request.cache_parts,
        ):
            digest.update(part.encode("utf-8", "ignore"))
            digest.update(b"\x1f")
        return digest.hexdigest()[:40]

    def _cache_path(self, key: str) -> Path:
        return CACHE_DIR / key[:2] / f"{key}.json"

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        if not self.config.cache_enabled:
            return None
        try:
            payload = json.loads(self._cache_path(key).read_text(encoding="utf-8"))
            data = payload.get("data")
            return data if isinstance(data, dict) else None
        except Exception:  # noqa: BLE001 - a missing or corrupt entry is a miss
            return None

    def _write_cache(self, key: str, request: GeminiRequest, data: dict[str, Any]) -> None:
        if not self.config.cache_enabled:
            return
        try:
            path = self._cache_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "task": request.task,
                "model": self.config.model,
                "promptVersion": request.prompt_version,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "data": data,
            }, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001 - a cache write must never fail a call
            logger.debug("Could not write Gemini cache entry", exc_info=True)

    # ── diagnostics ──────────────────────────────────────────────────────────

    def queue_snapshot(self) -> dict[str, Any]:
        depth = self._queue.qsize() if self._queue is not None else 0
        by_priority = {
            Priority(level).name: count
            for level, count in sorted(self._depth_by_priority.items())
            if count > 0
        }
        return {
            "depth": depth,
            "byPriority": by_priority,
            "inFlight": len(self._inflight),
            "workers": len([task for task in self._workers if not task.done()]),
            "concurrency": self.config.concurrency,
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "health": self.health(),
            "enabled": self.config.enabled,
            "configured": self.configured,
            "model": self.config.model,
            "baseUrl": self.config.base_url,
            "limits": {
                "concurrency": self.config.concurrency,
                "minIntervalSeconds": self.config.min_interval_seconds,
                "maxAttempts": self.config.max_attempts,
                "failureThreshold": self.config.failure_threshold,
                "cooldownSeconds": self.config.cooldown_seconds,
                "timeoutSeconds": self.config.timeout_seconds,
            },
            "circuit": self.breaker.snapshot(),
            "queue": self.queue_snapshot(),
            "metrics": telemetry.to_dict(self.config),
        }


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def _extract_json(content: str) -> dict[str, Any] | None:
    """Parse a reply, tolerating a markdown fence or trailing prose around it."""
    text = _FENCE.sub("", content.strip()).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


_gateway: GeminiGateway | None = None


def get_gateway() -> GeminiGateway:
    """The process-wide gateway. Built on first use so config/env are read late."""
    global _gateway
    if _gateway is None:
        _gateway = GeminiGateway()
    return _gateway


def reset_gateway() -> None:
    """Drop the singleton. For tests, and for a config change that needs a rebuild."""
    global _gateway
    _gateway = None
