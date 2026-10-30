"""The review-question model call must not hold the Auto Apply worker slot.

It is the one model call on by default inside the application pipeline: one
serial completion per blocking issue, uncached, each allowed a minute. The same
screening question recurs across many postings, so identical issues are now
classified once, and a job's classification has a total time budget past which
the deterministic fallback is used.
"""

import asyncio

import pytest

from app.services.application_assistant import error_normalizer as normalizer
from app.services.application_assistant import llm_client


class _FakeClient:
    def __init__(self, delay: float = 0.0):
        self.calls = 0
        self.delay = delay

    async def complete(self, prompt, system=None):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return {"success": True, "data": '{"category": "WORK_AUTHORIZATION", "question": "Do you need sponsorship?"}'}


@pytest.fixture(autouse=True)
def empty_cache():
    normalizer._CLASSIFICATION_CACHE.clear()
    yield
    normalizer._CLASSIFICATION_CACHE.clear()


def _issue(label: str) -> dict:
    return {"gate": "SUBMIT_VALIDATION", "label": label, "issueType": "MISSING_REQUIRED",
            "reason": f"Required field '{label}' was rejected as empty on submit."}


def test_an_identical_issue_is_classified_by_the_model_once(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(llm_client, "create_llm_client", lambda *a, **k: client)
    issue = _issue("Will you require sponsorship?")

    first = asyncio.run(normalizer.build_pending_questions([issue]))
    second = asyncio.run(normalizer.build_pending_questions([dict(issue)]))

    assert client.calls == 1
    assert first == second
    assert first[0]["category"] == "WORK_AUTHORIZATION"


def test_a_failed_model_answer_is_not_cached(monkeypatch):
    class Down(_FakeClient):
        async def complete(self, prompt, system=None):
            self.calls += 1
            return {"success": False}

    client = Down()
    monkeypatch.setattr(llm_client, "create_llm_client", lambda *a, **k: client)
    issue = _issue("Earliest start date?")

    asyncio.run(normalizer.build_pending_questions([issue]))
    asyncio.run(normalizer.build_pending_questions([issue]))

    assert client.calls == 2


def test_a_slow_model_is_cut_off_at_the_budget(monkeypatch):
    client = _FakeClient(delay=5.0)
    monkeypatch.setattr(llm_client, "create_llm_client", lambda *a, **k: client)
    monkeypatch.setattr(normalizer, "REVIEW_CLASSIFY_BUDGET_SECONDS", 0.2)
    issues = [_issue(f"Custom question number {n}?") for n in range(4)]

    async def timed():
        loop = asyncio.get_running_loop()
        start = loop.time()
        questions = await normalizer.build_pending_questions(issues)
        return questions, loop.time() - start

    questions, elapsed = asyncio.run(timed())

    assert elapsed < 1.5
    # Every issue still becomes an answerable question via the fallback.
    assert [q["rawLabel"] for q in questions] == [i["label"] for i in issues]
    assert all(q["category"] == "MISSING_FIELD" for q in questions)
