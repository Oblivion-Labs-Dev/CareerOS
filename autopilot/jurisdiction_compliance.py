"""Jurisdiction-aware compliance warnings on the *employer's own* question.

Adapted from career-ops's `apply` mode (Steps 5c/5d): before an answer is
drafted, judge whether the form question itself is one worth a second look —
not because CareerOS cannot answer it safely (that is `blocking_errors`'s
job), but because the question crosses a line some jurisdictions restrict.
Two categories, matching what career-ops distinguishes:

* **Immigration-status screening.** "Are you authorized to work in the US?"
  and "will you now or in the future require sponsorship?" are the lawful
  questions this project already answers correctly from the candidate's
  profile — they never warn. This fires only when a question asks about
  *status* instead: citizenship, permanent-resident status, or an
  authorization question qualified by permanence ("...on a permanent
  basis?"), which several jurisdictions treat as a proxy for citizenship
  screening. Citizenship-status discrimination in hiring is restricted under
  federal law for most US employers, so this check does not need the
  candidate's state to fire.
* **Salary-history requests.** A number of US states restrict employers from
  asking what a candidate previously earned. A *salary-expectation* question
  ("what are you looking for?") is a different question and never matches.
  Unlike the status check, this genuinely varies by state, so it only fires
  when the candidate's own profile state is one of the representative set
  below — an unknown state skips silently rather than guessing.

**This is warn-only, and not a source of legal truth.** It flags a question
for the candidate's attention; it never blocks an application, never
auto-answers, and never asserts that a specific employer is breaking the law.
The state list below is a representative starting set assembled from public
reporting, not an exhaustive legal survey — treat every hit as "worth a
second look," not a verified legal conclusion, and always review before
answering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ComplianceWarning:
    category: str  # "immigration_status_screening" | "salary_history"
    message: str


_STATUS_PATTERNS = [
    re.compile(r"\bare you a\b.{0,15}\bcitizen\b", re.I),
    re.compile(r"\bcitizen(ship)? status\b", re.I),
    re.compile(r"\b(permanent resident|green card)\b.{0,25}\b(status|only|required)\b", re.I),
    re.compile(r"\bauthoriz(ed|ation)\b.{0,45}\bon a permanent basis\b", re.I),
]

_LAWFUL_AUTHORIZATION_PATTERN = re.compile(
    r"\bauthoriz(ed|ation)\b.{0,25}\bwork\b|\bsponsorship\b|\brequire.{0,20}visa\b",
    re.I,
)

_SALARY_HISTORY_PATTERNS = [
    re.compile(r"\b(current|previous|prior|past)\b.{0,20}\bsalary\b", re.I),
    re.compile(r"\bsalary history\b", re.I),
    re.compile(r"\bwhat (do|did) you (currently )?(make|earn)\b", re.I),
    re.compile(r"\bcompensation history\b", re.I),
]

_SALARY_EXPECTATION_PATTERN = re.compile(
    r"\bexpect(ed|ation)?\b|\bdesired\b|\btarget\b|\brequirement\b|\brange\b|\blooking for\b",
    re.I,
)

# States with some form of salary-history-inquiry restriction, per general
# public reporting. Not exhaustive, not a substitute for legal research — see
# the module docstring.
_SALARY_HISTORY_BAN_STATES = frozenset({
    "california", "colorado", "connecticut", "delaware", "hawaii", "illinois",
    "maine", "maryland", "massachusetts", "nevada", "new jersey", "new york",
    "oregon", "rhode island", "vermont", "washington",
})


def check_immigration_status_screening(question_text: str) -> ComplianceWarning | None:
    """None unless `question_text` screens for immigration *status* rather
    than plain work *authorization* — see the module docstring for the line
    between them."""
    text = (question_text or "").strip()
    if not text:
        return None

    status_hit = next((p for p in _STATUS_PATTERNS if p.search(text)), None)
    if status_hit is None:
        return None

    # A permanence-qualified authorization question is the one status pattern
    # that overlaps lawful phrasing ("authorized to work... on a permanent
    # basis") — everything else in _STATUS_PATTERNS is unambiguous on its own.
    if _LAWFUL_AUTHORIZATION_PATTERN.search(text) and "permanent basis" not in text.lower():
        return None

    return ComplianceWarning(
        category="immigration_status_screening",
        message=(
            f'This question ("{text}") screens for a specific immigration status '
            "rather than work authorization. Citizenship/status-based screening in "
            "hiring is restricted under federal law for most US employers, separate "
            'from the lawful question "are you authorized to work in the US?" '
            "This is informational only, not legal advice — review before answering."
        ),
    )


def check_salary_history_request(question_text: str, profile: dict) -> ComplianceWarning | None:
    """None unless `question_text` asks for past pay (not a *desired* salary)
    and the candidate's own profile state is one of the representative set
    that restricts asking it. An unknown state skips silently rather than
    guessing whether the question is restricted."""
    text = (question_text or "").strip()
    if not text or not any(p.search(text) for p in _SALARY_HISTORY_PATTERNS):
        return None
    if _SALARY_EXPECTATION_PATTERN.search(text):
        return None

    state = str((profile or {}).get("state") or "").strip().lower()
    if not state or state not in _SALARY_HISTORY_BAN_STATES:
        return None

    return ComplianceWarning(
        category="salary_history",
        message=(
            f'This question ("{text}") asks for your salary history. A number of US '
            "states restrict employers from asking what a candidate previously "
            "earned. This is informational only, not legal advice — review before "
            "answering."
        ),
    )


def collect_job_compliance_warnings(resolutions: Iterable[Any]) -> list[dict[str, str]]:
    """De-duplicated `{question, message, fieldId}` rows for one run's
    `AnswerResolution`s, in the shape a job record stores under
    `complianceWarnings`. Duck-typed on `.question`, `.field_id` and
    `.compliance_warnings` rather than importing `AnswerResolution`, so this
    stays a leaf module callers can import from either direction."""
    warnings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for res in resolutions:
        question = getattr(res, "question", "") or ""
        for message in getattr(res, "compliance_warnings", None) or []:
            key = (question, message)
            if key in seen:
                continue
            seen.add(key)
            warnings.append({
                "question": question,
                "message": message,
                "fieldId": getattr(res, "field_id", "") or "",
            })
    return warnings
