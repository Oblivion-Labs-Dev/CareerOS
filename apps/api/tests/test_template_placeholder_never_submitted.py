"""A saved answer with an unfilled "[Company]" placeholder is never filled in verbatim.

The profile keeps a "Why do you want to work at [Company]?" template whose answer
reads "What interests me about [Company] is ...". The saved-answer match ran
before the answer library, so the template beat Chainguard's own approved answer
and "[Company]" was submitted literally (Chainguard 2026-10-30; Discord 15 times
10-22..10-26). The resolver has no company name to substitute, so the template
is skipped; with no company-specific approval the question goes to review.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

TEMPLATE = "What interests me about [Company] is the opportunity to build something meaningful."
PROFILE = {
    "screeningAnswers": [
        {
            "id": "why_company_template",
            "question": "Why do you want to work at [Company]?",
            "answer": TEMPLATE,
            "matchPatterns": [r"why\s+(?:do\s+you\s+)?want\s+to\s+work\s+at", r"why\s+(?:are\s+you\s+)?interested\s+in"],
            "source": "user_approved",
        },
    ]
}
QUESTION = "Why are you interested in this role at Chainguard?"


def test_company_specific_approval_wins_over_the_template():
    lib = [{
        "normalizedKey": "why are you interested in this role at chainguard?",
        "questionVariants": [QUESTION],
        "value": "What interests me about Chainguard is the opportunity to build something meaningful.",
        "verificationStatus": "verified",
    }]
    res = resolve_answer(QUESTION, PROFILE, answer_lib=lib)
    assert res.answer == "What interests me about Chainguard is the opportunity to build something meaningful."


def test_template_alone_is_not_submitted():
    res = resolve_answer(QUESTION, PROFILE)
    assert not res.answer or "[Company]" not in res.answer


def test_placeholder_from_any_source_is_cleared():
    lib = [{"normalizedKey": QUESTION.lower(), "questionVariants": [QUESTION], "value": TEMPLATE, "verificationStatus": "verified"}]
    res = resolve_answer(QUESTION, {}, answer_lib=lib)
    assert not res.answer
