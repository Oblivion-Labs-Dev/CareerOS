"""What the profile is missing, before any form has been seen.

CareerOS already has a readiness check, but it is **application-scoped**:
``field_answers.sync_application_readiness`` needs a scraped form to reason
about, so it can only speak once a browser has opened the posting. That is too
late to be useful as a gate — by then the attempt has already been spent, and
the job lands in review.

This module answers the same question one step earlier and without a form: given
only the candidate's profile, which answers will an application ask for that
nothing can supply? That is cheap enough to run before a batch starts, which is
the whole point — 872 jobs currently sit in review, 484 of them blocked on a
field no resolver could answer, and each one cost a real browser run to discover.

**The required set is derived from the resolvers that already decline.** Every
entry below corresponds to a branch in ``profile_answer_resolver`` that appends
to ``blocking_errors`` or returns without an answer. Keeping the list tied to
those branches is deliberate: a gap here that no resolver actually blocks on
would nag the user for nothing, and a resolver that blocks without a gap here is
exactly the mid-application surprise this exists to prevent.

Two severities, because they are not the same problem:

* **blocking** — a resolver refuses, so the application cannot complete. Worth
  stopping a run for.
* **soft** — the resolver produces nothing but the application may still finish,
  or the field only appears on some boards. Worth showing, never worth blocking.

Entries are shaped like ``error_normalizer.build_pending_questions`` output so
the review UI can render a profile gap and a per-application pending question
with the same component.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.application_assistant.profile_answer_resolver import (
    _education_entries,
    _get_work_auth,
    _prior_employers,
    candidate_timezone,
)

#: Mirrors error_normalizer's categories closely enough that one component can
#: render both. A profile gap is always something the candidate supplies.
CATEGORY_PROFILE = "profile_data"


@dataclass(frozen=True)
class ReadinessGap:
    """One answer the profile cannot supply."""

    profile_key: str
    question: str
    raw_label: str
    field_type: str = "text"
    options: list[str] = field(default_factory=list)
    #: Where in the dashboard the user fixes it, so the UI can deep-link rather
    #: than saying "go and find this somewhere in your profile".
    fix_at: str = "/profile"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "rawLabel": self.raw_label,
            "category": CATEGORY_PROFILE,
            "fieldType": self.field_type,
            "options": list(self.options),
            "profileKey": self.profile_key,
            "fixAt": self.fix_at,
        }


@dataclass
class ReadinessReport:
    blocking: list[ReadinessGap] = field(default_factory=list)
    soft: list[ReadinessGap] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blocking": [gap.to_dict() for gap in self.blocking],
            "soft": [gap.to_dict() for gap in self.soft],
            "blockingCount": len(self.blocking),
            "softCount": len(self.soft),
        }

    def summary(self) -> str:
        """One line naming what is missing, for a refusal message."""
        if self.ready:
            return "Profile has every answer this run needs."
        names = ", ".join(gap.raw_label for gap in self.blocking[:4])
        more = f" (and {len(self.blocking) - 4} more)" if len(self.blocking) > 4 else ""
        count = len(self.blocking)
        noun = "answer is" if count == 1 else "answers are"
        return f"{count} {noun} missing from your profile: {names}{more}."


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


# ── Individual checks ────────────────────────────────────────────────────────
#
# Each returns a gap when the profile cannot answer, or None. Split out one per
# check so the mapping back to the declining resolver stays legible.


def _check_english_level(profile: dict[str, Any]) -> ReadinessGap | None:
    """_resolve_english_proficiency declines without a recorded level."""
    if _has_text(profile.get("englishLevel") or profile.get("englishProficiency")):
        return None
    return ReadinessGap(
        profile_key="englishLevel",
        raw_label="English proficiency",
        question="What is your English level?",
        options=["Basic", "Conversational", "Proficient", "Fluent", "Native"],
    )


def _check_citizenship_country(profile: dict[str, Any]) -> ReadinessGap | None:
    """_resolve_export_control declines on the "which country" form."""
    if _has_text(profile.get("citizenshipCountry") or profile.get("citizenship")):
        return None
    return ReadinessGap(
        profile_key="citizenshipCountry",
        raw_label="Country of citizenship",
        question="In which country did you obtain citizenship, nationality, or permanent residency?",
    )


def _check_timezone(profile: dict[str, Any]) -> ReadinessGap | None:
    """_resolve_timezone_location declines when no zone is derivable.

    Derivation from the recorded location counts, so a profile with a US state
    is already answerable and must not be nagged.
    """
    if candidate_timezone(profile) is not None:
        return None
    return ReadinessGap(
        profile_key="timezone",
        raw_label="Time zone",
        question="What time zone are you in?",
    )


def _check_work_history(profile: dict[str, Any]) -> ReadinessGap | None:
    """_resolve_employer_count declines with no employers to count.

    Employment-row fills on Greenhouse depend on the same data, so an empty work
    history blocks considerably more than the count question alone.
    """
    if _prior_employers(profile):
        return None
    return ReadinessGap(
        profile_key="workExperience",
        raw_label="Work history",
        question="Which companies have you worked for?",
    )


def _check_years_experience(profile: dict[str, Any]) -> ReadinessGap | None:
    """Years of experience, which must never be guessed.

    The resolver defaulted this to 8 when unset — a fabricated fact about the
    candidate, stated to an employer with no basis. It now declines, so the
    number has to come from here.
    """
    if _has_text(profile.get("yearsExperience") or profile.get("yearsOfExperience")):
        return None
    return ReadinessGap(
        profile_key="yearsExperience",
        raw_label="Years of experience",
        question="How many years of relevant experience do you have?",
        field_type="number",
    )


def _check_education(profile: dict[str, Any]) -> ReadinessGap | None:
    """_resolve_education_history answers nothing without an entry."""
    if _education_entries(profile):
        return None
    return ReadinessGap(
        profile_key="education",
        raw_label="Education",
        question="What is your highest degree, and where did you earn it?",
    )


def _check_work_authorization(profile: dict[str, Any]) -> ReadinessGap | None:
    """Sponsorship must be explicit, never inferred.

    _get_work_auth defaults `requiresSponsorshipNowOrFuture` from a flat
    `sponsorship` string, and silently False when neither exists. Answering "no
    sponsorship needed" for a candidate who needs it misrepresents them to an
    employer, so an unrecorded value is a gap rather than a default.
    """
    work_auth = profile.get("workAuth") or {}
    if "requiresSponsorshipNowOrFuture" in work_auth or _has_text(profile.get("sponsorship")):
        return None
    return ReadinessGap(
        profile_key="sponsorship",
        raw_label="Visa sponsorship",
        question="Do you now or in the future require visa sponsorship?",
        field_type="boolean",
        options=["Yes", "No"],
    )


# ── Soft checks ──────────────────────────────────────────────────────────────


def _check_gpa(profile: dict[str, Any]) -> ReadinessGap | None:
    """_resolve_gpa declines without one, but few boards require it."""
    if _has_text(profile.get("gpa") or profile.get("undergraduateGpa")):
        return None
    return ReadinessGap(profile_key="gpa", raw_label="GPA", question="What was your GPA?")


def _check_education_dates(profile: dict[str, Any]) -> ReadinessGap | None:
    """Greenhouse renders education start/end as separate required selects."""
    missing = [
        entry for entry in _education_entries(profile)
        if not _has_text(entry.get("startDate")) or not _has_text(entry.get("endDate"))
    ]
    if not missing:
        return None
    return ReadinessGap(
        profile_key="education",
        raw_label="Education dates",
        question=(
            f"{len(missing)} education entr{'y is' if len(missing) == 1 else 'ies are'} "
            "missing a start or end date."
        ),
    )


def _check_salary(profile: dict[str, Any]) -> ReadinessGap | None:
    if _has_text(profile.get("salaryExpectations")):
        return None
    return ReadinessGap(
        profile_key="salaryExpectations",
        raw_label="Salary expectations",
        question="What are your salary expectations?",
    )


def _check_demographics(profile: dict[str, Any]) -> ReadinessGap | None:
    """EEO questions are voluntary, so never blocking — but an unset value means
    every such form stops for a human, which is worth surfacing."""
    unset = [
        key for key in ("gender", "raceEthnicity", "veteran", "disability")
        if not _has_text(profile.get(key))
    ]
    if not unset:
        return None
    return ReadinessGap(
        profile_key=unset[0],
        raw_label="Voluntary self-identification",
        question=(
            f"{len(unset)} EEO question{'' if len(unset) == 1 else 's'} "
            "(gender, race, veteran, disability) have no recorded answer."
        ),
    )


_BLOCKING_CHECKS: tuple[Callable[[dict[str, Any]], ReadinessGap | None], ...] = (
    _check_english_level,
    _check_citizenship_country,
    _check_timezone,
    _check_work_history,
    _check_years_experience,
    _check_education,
    _check_work_authorization,
)

_SOFT_CHECKS: tuple[Callable[[dict[str, Any]], ReadinessGap | None], ...] = (
    _check_education_dates,
    _check_gpa,
    _check_salary,
    _check_demographics,
)


def evaluate_profile_readiness(profile: dict[str, Any] | None) -> ReadinessReport:
    """Which answers the profile cannot supply, before any form is seen.

    Pure: no database, no network, no clock. That is what makes it cheap enough
    to call on every Start press and simple enough to test exhaustively.
    """
    profile = profile or {}
    report = ReadinessReport()
    for check in _BLOCKING_CHECKS:
        gap = check(profile)
        if gap is not None:
            report.blocking.append(gap)
    for check in _SOFT_CHECKS:
        gap = check(profile)
        if gap is not None:
            report.soft.append(gap)
    return report
