"""The Gemini layer must make CareerOS better when it works and invisible when it does not.

Every failure mode here is faked. Deliberately: proving that sustained 429
handling works by actually exhausting a rate limit would burn the free-tier
quota the whole feature exists to exploit, and would prove it once on one day's
limits. A fake transport proves the behaviour every run, in milliseconds.

The tests are grouped by the promise they defend:

* the gateway calls Gemini correctly when it is healthy;
* each failure class is handled the way that failure deserves - a 404 is not
  retried like a 429, and a malformed reply is not treated as an outage;
* CareerOS keeps working regardless, which is the whole point.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.gemini import ambiguity, enrichment, grounding, match_gate
from app.services.gemini import config as gemini_config
from app.services.gemini.gateway import (
    CircuitState,
    GeminiGateway,
    GeminiRequest,
    Outcome,
    Priority,
    RawReply,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPLY", "REVIEW", "SKIP"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["decision", "confidence"],
}


def reply_ok(payload: str = '{"decision": "APPLY", "confidence": 0.9}') -> RawReply:
    return RawReply(
        status=200,
        body={
            "choices": [{"message": {"content": payload}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
    )


def reply_error(status: int, message: str = "nope", headers: dict | None = None) -> RawReply:
    return RawReply(status=status, body={"error": {"message": message}}, headers=headers or {})


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    """A gateway with no real network, no real sleeps and no shared state."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    # Isolate the on-disk cache and the cross-process circuit file: the real
    # ones live under data/ and a test must never read or write them.
    from app.services.gemini import gateway as gateway_module
    from app.services.gemini import telemetry as telemetry_module

    monkeypatch.setattr(gateway_module, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(telemetry_module, "CIRCUIT_FILE", tmp_path / "circuit.json")
    telemetry_module.telemetry.reset()

    config = gemini_config.load()
    config = type(config)(
        **{
            **config.__dict__,
            # The suite disables Gemini globally (see conftest) so that no test
            # can reach the real API by accident. These tests are about the
            # gateway itself, so this one instance is switched back on against
            # a fake transport.
            "enabled": True,
            # No waiting. Pacing and backoff are behaviours under test elsewhere;
            # here they would only make the suite slow.
            "min_interval_seconds": 0.0,
            "max_attempts": 3,
            "failure_threshold": 3,
            "cooldown_seconds": 0.2,
            "max_cooldown_seconds": 0.4,
            "timeout_seconds": 1.0,
        }
    )
    instance = GeminiGateway(config)
    # Backoff sleeps are real asyncio sleeps of seconds. Collapse them so a
    # retry test costs microseconds without changing the retry logic itself.
    monkeypatch.setattr(instance, "_retry_delay", lambda *_args, **_kwargs: 0.0)
    return instance


def request(**overrides) -> GeminiRequest:
    base = dict(
        task="test_task",
        system="system",
        prompt="prompt",
        schema=SCHEMA,
        deadline_seconds=5.0,
    )
    base.update(overrides)
    return GeminiRequest(**base)


class Recorder:
    """A fake transport that plays a script and counts how often it was called."""

    def __init__(self, *replies: RawReply, repeat_last: bool = True) -> None:
        self.replies = list(replies)
        self.repeat_last = repeat_last
        self.calls = 0
        self.payloads: list[dict] = []

    async def __call__(self, payload, timeout):
        self.payloads.append(payload)
        index = min(self.calls, len(self.replies) - 1) if self.repeat_last else self.calls
        self.calls += 1
        return self.replies[index]


# ── 1. healthy ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_healthy_gemini_returns_validated_enrichment(gateway):
    transport = Recorder(reply_ok())
    gateway.transport = transport

    result = await gateway.submit(request())

    assert result.ok
    assert result.outcome is Outcome.OK
    assert result.data == {"decision": "APPLY", "confidence": 0.9}
    assert transport.calls == 1
    # The schema must actually reach Gemini, not merely be checked afterwards.
    sent = transport.payloads[0]["response_format"]["json_schema"]
    assert sent["strict"] is True
    assert sent["schema"] == SCHEMA


# ── 2/3. 429 ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_429_is_retried_and_then_succeeds(gateway):
    transport = Recorder(reply_error(429, "quota"), reply_ok(), repeat_last=False)
    gateway.transport = transport

    result = await gateway.submit(request())

    assert result.ok, result.detail
    assert transport.calls == 2
    assert result.attempts == 2


@pytest.mark.anyio
async def test_retry_after_header_is_honoured_over_the_backoff_guess(gateway):
    # _retry_delay is stubbed in the fixture, so check the real one directly:
    # the server knows its own limits better than an exponential guess does.
    real = GeminiGateway.__dict__["_retry_delay"]
    delay = real(gateway, reply_error(429, headers={"retry-after": "17"}), Outcome.RATE_LIMITED, 2.0)
    assert delay == 17.0


@pytest.mark.anyio
async def test_sustained_429_opens_the_circuit(gateway):
    gateway.transport = Recorder(reply_error(429, "quota exhausted"))

    # failure_threshold is 3, and each submit exhausts its own retry budget.
    for _ in range(gateway.config.failure_threshold):
        result = await gateway.submit(request(prompt=f"prompt-{_}"))
        assert not result.ok

    assert gateway.breaker.snapshot()["state"] == CircuitState.OPEN.value
    assert gateway.health() in ("CIRCUIT OPEN", "RATE LIMITED")


# ── 4. 503 ───────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_503_is_retried_then_gives_up_without_raising(gateway):
    transport = Recorder(reply_error(503, "service unavailable"))
    gateway.transport = transport

    result = await gateway.submit(request())

    assert not result.ok
    assert result.outcome is Outcome.TRANSIENT
    assert transport.calls == gateway.config.max_attempts


@pytest.mark.anyio
async def test_repeated_503_opens_the_circuit(gateway):
    gateway.transport = Recorder(reply_error(503))
    for index in range(gateway.config.failure_threshold):
        await gateway.submit(request(prompt=f"p{index}"))
    assert gateway.breaker.snapshot()["state"] == CircuitState.OPEN.value


# ── 5. 404 ───────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_404_is_not_retried(gateway):
    """A wrong model name is a config bug. Retrying it is how a typo becomes a storm."""
    transport = Recorder(reply_error(404, "model not found"))
    gateway.transport = transport

    result = await gateway.submit(request())

    assert not result.ok
    assert result.outcome is Outcome.CONFIG_ERROR
    assert transport.calls == 1, "a 404 must cost exactly one call"
    # And it stops further traffic immediately rather than after N failures.
    assert gateway.breaker.snapshot()["state"] == CircuitState.OPEN.value


@pytest.mark.anyio
async def test_404_blocks_the_next_request_without_calling_the_api(gateway):
    transport = Recorder(reply_error(404, "model not found"))
    gateway.transport = transport

    await gateway.submit(request(prompt="first"))
    calls_after_first = transport.calls
    second = await gateway.submit(request(prompt="second"))

    assert second.outcome is Outcome.CIRCUIT_OPEN
    assert transport.calls == calls_after_first, "the circuit must prevent a second call"


@pytest.mark.anyio
async def test_other_4xx_fails_fast(gateway):
    transport = Recorder(reply_error(401, "invalid api key"))
    gateway.transport = transport

    result = await gateway.submit(request())

    assert result.outcome is Outcome.PERMANENT
    assert transport.calls == 1


# ── 6. circuit open, CareerOS continues ──────────────────────────────────────

@pytest.mark.anyio
async def test_open_circuit_returns_promptly_and_never_raises(gateway):
    gateway.transport = Recorder(reply_error(503))
    for index in range(gateway.config.failure_threshold):
        await gateway.submit(request(prompt=f"p{index}"))

    calls_before = gateway.transport.calls
    result = await asyncio.wait_for(gateway.submit(request(prompt="while-open")), timeout=2.0)

    assert not result.ok
    assert result.outcome is Outcome.CIRCUIT_OPEN
    assert gateway.transport.calls == calls_before


@pytest.mark.anyio
async def test_circuit_half_opens_and_closes_after_a_successful_probe(gateway):
    gateway.transport = Recorder(reply_error(503))
    for index in range(gateway.config.failure_threshold):
        await gateway.submit(request(prompt=f"p{index}"))
    assert gateway.breaker.snapshot()["state"] == CircuitState.OPEN.value

    await asyncio.sleep(gateway.config.cooldown_seconds + 0.05)
    gateway.transport = Recorder(reply_ok())

    result = await gateway.submit(request(prompt="probe"))

    assert result.ok
    assert gateway.breaker.snapshot()["state"] == CircuitState.CLOSED.value


# ── 7/8. application behaviour around an ambiguous match ─────────────────────

AMBIGUOUS_JOB = {
    "title": "Software Engineer",
    "company": "Example",
    "description": (
        "We are hiring an engineer to work across our systems. "
        "The team ships services and also owns data pipelines, spark jobs and "
        "the etl that feeds them, alongside backend microservice work and api "
        "development. This role requires an active security clearance. "
    ) * 4,
}

CLEAR_JOB = {
    "title": "Senior Backend Engineer",
    "company": "Example",
    "description": (
        "Build and operate backend microservice systems. You will own api "
        "development for a distributed system serving millions of requests, "
        "working server-side in a backend team on back-end infrastructure. "
    ) * 6,
}


@pytest.mark.anyio
async def test_unavailable_gemini_on_an_ambiguous_match_stages_for_review(gateway, monkeypatch):
    monkeypatch.setattr("app.services.gemini.gateway.get_gateway", lambda: gateway)
    monkeypatch.setattr("app.services.gemini.enrichment.get_gateway", lambda: gateway)
    gateway.transport = Recorder(reply_error(503))

    decision = await match_gate.evaluate(
        AMBIGUOUS_JOB, score=79.0, profile={"summary": "Backend engineer"},
    )

    assert decision.action == match_gate.REVIEW
    assert "no second opinion" in decision.reason.lower()
    # Review, not failure: the posting is still workable by hand.
    assert decision.uncertainty["ambiguous"] is True


@pytest.mark.anyio
async def test_confident_deterministic_match_never_calls_gemini(gateway, monkeypatch):
    monkeypatch.setattr("app.services.gemini.enrichment.get_gateway", lambda: gateway)
    transport = Recorder(reply_ok())
    gateway.transport = transport

    decision = await match_gate.evaluate(CLEAR_JOB, score=94.0)

    assert decision.proceed
    assert decision.consulted is False
    assert transport.calls == 0, "a confident match must not reach Gemini at all"


@pytest.mark.anyio
async def test_gemini_can_divert_to_review_but_never_forces_an_apply(gateway, monkeypatch):
    monkeypatch.setattr("app.services.gemini.enrichment.get_gateway", lambda: gateway)
    gateway.transport = Recorder(reply_ok(
        '{"decision": "SKIP", "primary_role_family": "data", "secondary_role_family": "",'
        ' "seniority_match": true, "critical_mismatch": true,'
        ' "critical_requirements": ["security clearance"], "confidence": 0.91,'
        ' "reason": "Requires a clearance the candidate does not hold."}'
    ))

    decision = await match_gate.evaluate(AMBIGUOUS_JOB, score=81.0, profile={"summary": "x"})

    assert decision.action == match_gate.REVIEW
    assert decision.gemini is not None
    assert decision.gemini["source"] == "gemini"


@pytest.mark.anyio
async def test_an_unsure_gemini_does_not_override_the_deterministic_result(gateway, monkeypatch):
    monkeypatch.setattr("app.services.gemini.enrichment.get_gateway", lambda: gateway)
    gateway.transport = Recorder(reply_ok(
        '{"decision": "SKIP", "primary_role_family": "data", "secondary_role_family": "",'
        ' "seniority_match": true, "critical_mismatch": true, "critical_requirements": [],'
        ' "confidence": 0.2, "reason": "Not sure."}'
    ))

    decision = await match_gate.evaluate(AMBIGUOUS_JOB, score=81.0, profile={"summary": "x"})

    assert decision.proceed
    assert "too unsure" in decision.reason.lower()


# ── 9. cache and dedupe ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_an_identical_request_is_served_from_cache(gateway):
    transport = Recorder(reply_ok())
    gateway.transport = transport

    first = await gateway.submit(request())
    second = await gateway.submit(request())

    assert first.ok and second.ok
    assert second.cached
    assert second.data == first.data
    assert transport.calls == 1, "the second identical request must not reach the API"


@pytest.mark.anyio
async def test_concurrent_identical_requests_share_one_api_call(gateway):
    transport = Recorder(reply_ok())
    gateway.transport = transport

    results = await asyncio.gather(*(gateway.submit(request()) for _ in range(4)))

    assert all(r.ok for r in results)
    assert transport.calls == 1


@pytest.mark.anyio
async def test_a_changed_prompt_version_invalidates_the_cache(gateway):
    transport = Recorder(reply_ok())
    gateway.transport = transport

    await gateway.submit(request(prompt_version="v1"))
    await gateway.submit(request(prompt_version="v2"))

    assert transport.calls == 2, "a new prompt version must not reuse the old answer"


@pytest.mark.anyio
async def test_changed_source_data_invalidates_the_cache(gateway):
    transport = Recorder(reply_ok())
    gateway.transport = transport

    await gateway.submit(request(cache_parts=("resume-v1",)))
    await gateway.submit(request(cache_parts=("resume-v2",)))

    assert transport.calls == 2


# ── 10. malformed output ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_unparseable_output_is_retried_once_then_falls_back(gateway):
    transport = Recorder(reply_ok("this is not json at all"))
    gateway.transport = transport

    result = await gateway.submit(request())

    assert not result.ok
    assert result.outcome is Outcome.MALFORMED
    assert transport.calls == 2, "one retry, not a storm"


@pytest.mark.anyio
async def test_output_that_violates_the_schema_is_rejected(gateway):
    # Valid JSON, wrong shape: `decision` is not in the enum and `confidence`
    # is a string. This is the failure that silently poisons a consumer.
    transport = Recorder(reply_ok('{"decision": "MAYBE", "confidence": "high"}'))
    gateway.transport = transport

    result = await gateway.submit(request())

    assert not result.ok
    assert result.outcome is Outcome.MALFORMED
    assert "decision" in result.detail or "confidence" in result.detail


@pytest.mark.anyio
async def test_a_malformed_reply_does_not_open_the_circuit(gateway):
    """Gemini answering badly is not Gemini being down. Only outages open the circuit."""
    gateway.transport = Recorder(reply_ok("not json"))
    for index in range(gateway.config.failure_threshold + 1):
        await gateway.submit(request(prompt=f"p{index}"))

    assert gateway.breaker.snapshot()["state"] == CircuitState.CLOSED.value


@pytest.mark.anyio
async def test_a_fenced_json_reply_is_still_accepted(gateway):
    gateway.transport = Recorder(reply_ok('```json\n{"decision": "APPLY", "confidence": 0.5}\n```'))
    result = await gateway.submit(request())
    assert result.ok


# ── 11. priority ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_benchmark_traffic_cannot_starve_an_application(gateway):
    """The ordering promise: interactive work jumps a backlog of offline work."""
    order: list[str] = []
    release = asyncio.Event()

    async def transport(payload, timeout):
        # The first call holds the single worker until the queue has filled, so
        # everything after it is genuinely ordered by priority rather than by
        # arrival.
        order.append(payload["messages"][1]["content"])
        if payload["messages"][1]["content"] == "blocker":
            await release.wait()
        return reply_ok()

    gateway.transport = transport

    blocker = asyncio.create_task(gateway.submit(request(
        prompt="blocker", priority=Priority.BENCHMARK_LABEL, deadline_seconds=10
    )))
    await asyncio.sleep(0.05)  # let the blocker occupy the worker

    labels = [
        asyncio.create_task(gateway.submit(request(
            prompt=f"label-{index}", priority=Priority.BENCHMARK_LABEL, deadline_seconds=10
        )))
        for index in range(5)
    ]
    await asyncio.sleep(0.05)
    application = asyncio.create_task(gateway.submit(request(
        prompt="application", priority=Priority.ACTIVE_APPLICATION, deadline_seconds=10
    )))
    await asyncio.sleep(0.05)

    release.set()
    await asyncio.gather(blocker, application, *labels)

    served = [item for item in order if item != "blocker"]
    assert served[0] == "application", (
        f"the application waited behind offline labelling work: {served}"
    )


# ── 12. grounding ────────────────────────────────────────────────────────────

RESUME = (
    "Akshay Borse. Senior Software Engineer at Amazon. Built distributed "
    "services in Java and Python on AWS, using DynamoDB and Kubernetes. "
    "Reduced latency by 40% across a fleet handling 100K requests per second."
)


def _corpus() -> grounding.Corpus:
    return grounding.build_corpus({}, resume_text=RESUME)


def test_grounding_accepts_an_answer_built_from_the_resume():
    verdict = grounding.check(
        "I built distributed services in Java on AWS, and cut latency by 40%.",
        _corpus(),
    )
    assert verdict.ok, verdict.reason


def test_grounding_rejects_a_technology_the_candidate_never_used():
    verdict = grounding.check(
        "I have shipped production Rust services and used Terraform extensively.",
        _corpus(),
    )
    assert not verdict.ok
    assert verdict.unsupported_technologies


def test_grounding_rejects_an_invented_metric():
    verdict = grounding.check(
        "I cut latency by 90% on a fleet serving 5M requests per second.",
        _corpus(),
    )
    assert not verdict.ok
    assert verdict.invented_figures


def test_grounding_does_not_trip_on_a_calendar_year():
    verdict = grounding.check("I joined Amazon in 2019 and worked in Java.", _corpus())
    assert verdict.ok, verdict.reason


def test_grounding_refuses_when_there_is_no_corpus_at_all():
    assert not grounding.check("I did lots of things.", grounding.Corpus()).ok


@pytest.mark.anyio
async def test_an_ungrounded_gemini_answer_is_discarded_not_submitted(gateway, monkeypatch):
    monkeypatch.setattr("app.services.gemini.enrichment.get_gateway", lambda: gateway)
    gateway.transport = Recorder(reply_ok(
        '{"answer": "I have six years of production Rust and Terraform experience.",'
        ' "evidence": ["fabricated"], "supported": true, "confidence": 0.95,'
        ' "reason": "Strong match."}'
    ))

    result = await enrichment.answer_application_question(
        "Describe your relevant experience for this role.",
        resume_text=RESUME,
        company="Example",
    )

    assert not result.available
    assert result.outcome == "ungrounded"
    assert result.answer == ""


@pytest.mark.anyio
async def test_a_grounded_gemini_answer_is_accepted(gateway, monkeypatch):
    monkeypatch.setattr("app.services.gemini.enrichment.get_gateway", lambda: gateway)
    gateway.transport = Recorder(reply_ok(
        '{"answer": "At Amazon I built distributed services in Java on AWS.",'
        ' "evidence": ["Built distributed services in Java and Python on AWS"],'
        ' "supported": true, "confidence": 0.88, "reason": "Directly evidenced."}'
    ))

    result = await enrichment.answer_application_question(
        "Describe your relevant experience for this role.",
        resume_text=RESUME,
    )

    assert result.available, result.reason
    assert result.grounded
    assert "Amazon" in result.answer


# ── 13. deterministic fields never reach Gemini ──────────────────────────────

DETERMINISTIC_QUESTIONS = [
    "First name",
    "Email address",
    "Phone number",
    "Are you legally authorized to work in the United States?",
    "Will you now or in the future require sponsorship?",
    "What is your current city?",
    "LinkedIn profile URL",
    "Are you Hispanic or Latino?",
    "What is your gender?",
    "Veteran status",
    "Do you have an active security clearance?",
]


@pytest.mark.parametrize("question", DETERMINISTIC_QUESTIONS)
def test_deterministic_fields_are_refused_before_any_request_is_built(question):
    eligible, why_not = enrichment.question_is_eligible(question)
    assert not eligible, f"{question!r} must never be sent to a language model"
    assert why_not


def test_a_question_with_fixed_options_is_answered_deterministically():
    eligible, _ = enrichment.question_is_eligible(
        "Why do you want to work here?", options=["Yes", "No"]
    )
    assert not eligible


def test_a_canonical_key_short_circuits_the_gate():
    eligible, why_not = enrichment.question_is_eligible(
        "Tell us about yourself", canonical_key="first_name"
    )
    assert not eligible
    assert "first_name" in why_not


@pytest.mark.parametrize("question", [
    "Why are you interested in this role?",
    "Describe your relevant experience.",
    "Why are you a good fit for this position?",
])
def test_open_ended_questions_are_eligible(question):
    eligible, why_not = enrichment.question_is_eligible(question)
    assert eligible, why_not


@pytest.mark.anyio
async def test_a_deterministic_field_makes_no_api_call_at_all(gateway, monkeypatch):
    monkeypatch.setattr("app.services.gemini.enrichment.get_gateway", lambda: gateway)
    transport = Recorder(reply_ok())
    gateway.transport = transport

    result = await enrichment.answer_application_question(
        "What is your email address?", resume_text=RESUME
    )

    assert not result.available
    assert transport.calls == 0


# ── disabled / unconfigured ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_an_unconfigured_gemini_is_simply_unavailable(gateway, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gemini_config, "api_key", lambda: "")
    transport = Recorder(reply_ok())
    gateway.transport = transport

    result = await gateway.submit(request())

    assert result.outcome is Outcome.DISABLED
    assert transport.calls == 0
    assert gateway.health() == "DISABLED"


# ── ambiguity detection ──────────────────────────────────────────────────────

def test_a_score_near_the_auto_apply_boundary_is_ambiguous():
    verdict = ambiguity.assess(CLEAR_JOB, score=79.0)
    assert verdict.ambiguous
    assert any("boundary" in reason for reason in verdict.reasons)


def test_a_clearly_scored_posting_is_not_ambiguous():
    assert not ambiguity.assess(CLEAR_JOB, score=95.0).ambiguous


def test_an_unscored_posting_is_ambiguous_rather_than_dropped():
    verdict = ambiguity.assess(CLEAR_JOB, score=None)
    assert verdict.ambiguous
    assert any("no deterministic match score" in reason for reason in verdict.reasons)


def test_a_hedged_clearance_requirement_is_flagged():
    """"Ability to obtain a clearance" is a judgement call - worth asking about."""
    job = dict(CLEAR_JOB)
    job["description"] += (
        " Candidates must be eligible to obtain a security clearance, or equivalent."
    )

    verdict = ambiguity.assess(job, score=95.0)

    assert verdict.ambiguous
    assert "security clearance" in verdict.critical_requirements


def test_a_flatly_stated_requirement_is_not_worth_an_api_call():
    """"Requires an active clearance" needs no second opinion: the candidate
    either evidences it or does not, and CareerOS can decide that itself."""
    job = dict(CLEAR_JOB)
    job["description"] += " This role requires an active security clearance."

    assert "security clearance" not in ambiguity.assess(job, score=95.0).critical_requirements
    # It is still visible to anything that wants the full picture.
    assert "security clearance" in ambiguity.find_critical_requirements(
        job["description"], hedged_only=False
    )


def test_military_in_a_job_description_is_not_an_export_control_requirement():
    """The token ITAR sits inside the word "military". Without word boundaries
    that flagged 95 of 400 real postings as export-controlled."""
    assert ambiguity.find_critical_requirements(
        "Build software for military logistics customers. Clearance preferred.",
        hedged_only=False,
    ) == []


def test_a_posting_too_short_to_judge_is_not_worth_a_call():
    verdict = ambiguity.assess({"title": "Engineer", "description": "Come work here."}, score=None)
    assert not verdict.ambiguous


# ── title redaction for benchmark labels ─────────────────────────────────────

def test_the_job_title_is_removed_from_the_body_before_labelling():
    from app.services.gemini.title_redaction import strip_title

    body = (
        "Senior Platform Engineer\n"
        "About the Senior Platform Engineer role: you will own our build system.\n"
        "Requirements: five years of experience."
    )
    redacted, count = strip_title("Senior Platform Engineer", body)

    assert count >= 1
    assert "Senior Platform Engineer" not in redacted
    assert "build system" in redacted, "redaction must not eat the description"


# ── safe application behaviour when nothing can answer ───────────────────────

@pytest.mark.anyio
async def test_no_answer_source_stages_for_review_rather_than_inventing(monkeypatch):
    """The rule that matters most: never fabricate to keep Autopilot moving."""
    from app.services.application_assistant import structured_answer_engine as engine

    monkeypatch.setattr(engine, "LOCAL_LLM_ENABLED", False)

    result = await engine.resolve_level_3_llm(
        "Why are you interested in this role?", None, {"fullName": "A B"},
    )

    assert result["supported"] is False
    assert result["needsUserInput"] is True
    assert result["answer"] == ""


@pytest.mark.anyio
async def test_gemini_level_returns_none_when_the_layer_is_off():
    """The suite runs with Gemini disabled, so this is the real production shape
    of "no key configured": the hierarchy simply moves on to the next level."""
    from app.services.application_assistant import structured_answer_engine as engine

    assert await engine.resolve_level_3_gemini(
        "Describe your relevant experience.", None, {}, resume_text=RESUME,
    ) is None


@pytest.mark.anyio
async def test_the_question_hierarchy_still_answers_deterministic_fields(monkeypatch):
    """Level 1 must still win outright, with or without Gemini in the picture."""
    from app.services.application_assistant import structured_answer_engine as engine

    result = await engine.resolve_application_question(
        db=[], question_text="Email address", canonical_key="email",
        profile={"email": "someone@example.com"},
    )

    assert result["level"] == 1
    # CareerOS tags outgoing addresses so replies can be traced back to an
    # application, so the answer is derived from the profile rather than equal
    # to it. What matters here is that it came from the profile at level 1.
    assert result["answer"].endswith("@example.com")
    assert result["answer"].startswith("someone")
    assert result["needsUserInput"] is False


# ── the MatchLab shape: one asyncio.run() per posting, one shared gateway ────

def test_the_gateway_survives_repeated_private_event_loops(gateway):
    """MatchLab is synchronous and drives one `asyncio.run()` per posting.

    The gateway is a process-wide singleton, so its worker pool has to rebind to
    each new loop. Cancelling a task whose loop has already closed raises, which
    would have broken every posting after the first.
    """
    gateway.transport = Recorder(reply_ok())

    outcomes = [
        asyncio.run(gateway.submit(request(prompt=f"posting-{index}")))
        for index in range(3)
    ]

    assert all(result.ok for result in outcomes), [r.detail for r in outcomes]
    # Pacing and the circuit live on the instance, so they survive the rebind.
    assert gateway.breaker.snapshot()["state"] == CircuitState.CLOSED.value


# ── resume tailoring goes through the same guards as the local model ─────────

@pytest.mark.anyio
async def test_gemini_tailoring_returns_bullets_in_the_local_models_shape(gateway, monkeypatch):
    import json as _json

    from app.services.application_assistant import resume_diff_service as tailoring

    monkeypatch.setattr("app.services.gemini.gateway.get_gateway", lambda: gateway)
    monkeypatch.setattr(tailoring, "_GEMINI_TAILORING", True)
    # Gemini is off for the application path by default, and per-application
    # tailoring is part of that path; this test is about what the Gemini route
    # returns when it does run, so both switches go on for it. The conftest
    # turns CAREEROS_GEMINI_ENABLED off for the suite at large, and that master
    # switch also gates the application path.
    monkeypatch.setenv("CAREEROS_GEMINI_ENABLED", "1")
    monkeypatch.setenv("CAREEROS_GEMINI_APPLICATIONS", "on")
    gateway.transport = Recorder(reply_ok(_json.dumps({
        "bullets": ["<b>Led migration</b> of the service.", "<b>Built</b> the pipeline."]
    })))

    result = await tailoring._complete_batch_via_gemini("prompt", 2)

    assert result is not None
    assert result["provider"] == "gemini"
    # The same `{"success", "data"}` envelope the local client returns, so every
    # downstream guard (echo check, length clamp, fabrication guard) applies
    # unchanged.
    assert result["success"] is True
    assert len(_json.loads(result["data"])) == 2


@pytest.mark.anyio
async def test_a_wrong_bullet_count_falls_back_instead_of_misaligning(gateway, monkeypatch):
    """A short list silently mapped onto the slots is how bullet 3's text once
    ended up in slot 1. Treat it as no answer, not a partial one."""
    import json as _json

    from app.services.application_assistant import resume_diff_service as tailoring

    monkeypatch.setattr("app.services.gemini.gateway.get_gateway", lambda: gateway)
    monkeypatch.setattr(tailoring, "_GEMINI_TAILORING", True)
    # Gemini is off for the application path by default, and per-application
    # tailoring is part of that path; this test is about what the Gemini route
    # returns when it does run, so both switches go on for it. The conftest
    # turns CAREEROS_GEMINI_ENABLED off for the suite at large, and that master
    # switch also gates the application path.
    monkeypatch.setenv("CAREEROS_GEMINI_ENABLED", "1")
    monkeypatch.setenv("CAREEROS_GEMINI_APPLICATIONS", "on")
    gateway.transport = Recorder(reply_ok(_json.dumps({"bullets": ["only one"]})))

    assert await tailoring._complete_batch_via_gemini("prompt", 3) is None


@pytest.mark.anyio
async def test_tailoring_can_be_switched_off_independently(gateway, monkeypatch):
    from app.services.application_assistant import resume_diff_service as tailoring

    monkeypatch.setattr(tailoring, "_GEMINI_TAILORING", False)
    transport = Recorder(reply_ok())
    gateway.transport = transport

    assert await tailoring._complete_batch_via_gemini("prompt", 2) is None
    assert transport.calls == 0
