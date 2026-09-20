"""Application answers may draw on the recorded experience corpus.

The corpus already fed resume tailoring, but nothing fed it to the code that
answers application questions. So a long-form prompt like Canonical's "Describe
your Python software development experience" had only the resume and the flat
profile to work from and declined for want of evidence that was sitting in the
corpus all along.

Handing over recorded stories is grounding, not invention — it gives the model
more of what it is *allowed* to say. The constraints that ride along with a
story have to survive the trip, which is what most of this file checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.application_assistant import llm_answer_generator as gen


@dataclass
class _Story:
    id: str
    title: str = ""
    company: str = ""
    headline: str = ""
    body: str = ""
    metrics: list = field(default_factory=list)
    do_not_claim: list = field(default_factory=list)


@dataclass
class _Match:
    story: _Story
    score: float = 1.0
    matched: list = field(default_factory=list)


class _Index:
    def __init__(self, matches):
        self._matches = matches
        self.seen: list[str] = []

    def rank(self, job_text, *, title="", limit=6):
        self.seen.append(job_text)
        return self._matches


@pytest.fixture
def stub_index(monkeypatch):
    """Install a fake story index and hand the test its match list."""
    def _install(matches):
        index = _Index(matches)
        import app.services.story_index as story_index

        monkeypatch.setattr(story_index, "get_index", lambda: index)
        return index

    return _install


def test_recorded_stories_become_evidence(stub_index):
    stub_index([
        _Match(_Story(
            id="s1", headline="Built an order-state platform", company="Amazon",
            body="Introduced an Aging Order state that ended duplicate notifications.",
            metrics=["cut duplicate emails by 98%"],
        )),
    ])

    out = gen.story_evidence_for("Describe your Python experience", role="Senior Software Engineer")

    assert "Built an order-state platform" in out
    assert "(Amazon)" in out
    assert "Aging Order" in out
    assert "cut duplicate emails by 98%" in out


def test_do_not_claim_constraints_survive(stub_index):
    """The regression that matters most.

    A story records what happened *and* what must not be read into it. Passing
    the narrative while dropping the prohibition is how an application ends up
    overstating the candidate.
    """
    stub_index([
        _Match(_Story(
            id="s1", headline="Ran the migration", body="Moved the service across.",
            do_not_claim=["did not lead the team", "was not the architect"],
        )),
    ])

    out = gen.story_evidence_for("Tell us about your leadership")

    assert "Must NOT be claimed" in out
    assert "did not lead the team" in out
    assert "was not the architect" in out


def test_at_most_three_stories_are_handed_over(stub_index):
    """A prompt budget is finite; the corpus is not."""
    stub_index([
        _Match(_Story(id=f"s{i}", headline=f"Distinct story {i}", body="x" * 50))
        for i in range(10)
    ])

    out = gen.story_evidence_for("distributed systems")

    assert out.count("Distinct story") == 3


def test_near_duplicate_stories_are_collapsed(stub_index):
    """`rank` scores several accounts of one subject highly together — its own
    docstring says so. Three near-identical stories crowd out the variety the
    answer needs."""
    stub_index([
        _Match(_Story(id="a", headline="Built an operational platform", body="first account")),
        _Match(_Story(id="b", headline="built an OPERATIONAL platform", body="second account")),
        _Match(_Story(id="c", headline="Shipped a CNN classifier", body="third account")),
    ])

    out = gen.story_evidence_for("platform work")

    assert out.count("first account") == 1
    assert "second account" not in out, "same headline, should have been collapsed"
    assert "third account" in out, "a genuinely different story must still get through"


def test_a_question_the_corpus_cannot_answer_yields_nothing(stub_index):
    """No evidence must stay no evidence.

    Canonical asks how the candidate performed in high-school mathematics. The
    corpus holds no such fact, and inventing one states a falsehood to an
    employer.
    """
    stub_index([])

    assert gen.story_evidence_for("How did you perform in mathematics at high school?") == ""


def test_an_empty_question_retrieves_nothing(stub_index):
    index = stub_index([_Match(_Story(id="s1", headline="anything"))])

    assert gen.story_evidence_for("   ", role="") == ""
    assert index.seen == [], "no lookup should even be attempted"


def test_a_broken_corpus_never_breaks_the_answer(monkeypatch):
    """Evidence is an enrichment. If it fails, the answer still gets written."""
    import app.services.story_index as story_index

    def _boom():
        raise RuntimeError("corpus file is unreadable")

    monkeypatch.setattr(story_index, "get_index", _boom)

    assert gen.story_evidence_for("Describe your Python experience") == ""


def test_the_role_sharpens_retrieval(stub_index):
    index = stub_index([_Match(_Story(id="s1", headline="h"))])

    gen.story_evidence_for("Describe your experience", role="Senior Software Engineer")

    assert "Senior Software Engineer" in index.seen[0]
