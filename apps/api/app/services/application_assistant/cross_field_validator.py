"""Cross-Field Validator — prevents contradictory answers from submission.

Runs AFTER all fields are resolved but BEFORE clicking Submit.
Returns a ValidationReport with blocking errors, warnings, and per-field status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.db.store import now_iso
from app.services.application_assistant.profile_answer_resolver import (
    AnswerResolution,
    LLM_GENERATED_TEXT,
)
from app.services.application_assistant.question_classifier import (
    QuestionType,
    SENSITIVE_FACTUAL_TYPES,
)


@dataclass
class ValidationIssue:
    field_id: str
    question: str
    answer: str
    severity: str  # BLOCKING | WARNING
    rule: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fieldId": self.field_id,
            "question": self.question,
            "answer": self.answer,
            "severity": self.severity,
            "rule": self.rule,
            "reason": self.reason,
        }


@dataclass
class ValidationReport:
    status: str = "PASS"  # PASS | FAIL
    blocking_errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    validated_at: str = ""
    field_statuses: dict[str, str] = field(default_factory=dict)  # field_id → PASS/FAIL/WARN

    def to_dict(self) -> dict[str, Any]:
        return {
            "validationStatus": self.status,
            "blockingErrors": [e.to_dict() for e in self.blocking_errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "validatedAt": self.validated_at,
            "fieldStatuses": self.field_statuses,
        }


def _add_error(report: ValidationReport, res: AnswerResolution, rule: str, reason: str) -> None:
    issue = ValidationIssue(
        field_id=res.field_id,
        question=res.question,
        answer=str(res.answer or ""),
        severity="BLOCKING",
        rule=rule,
        reason=reason,
    )
    report.blocking_errors.append(issue)
    report.status = "FAIL"
    report.field_statuses[res.field_id] = "FAIL"


def _add_warning(report: ValidationReport, res: AnswerResolution, rule: str, reason: str) -> None:
    issue = ValidationIssue(
        field_id=res.field_id,
        question=res.question,
        answer=str(res.answer or ""),
        severity="WARNING",
        rule=rule,
        reason=reason,
    )
    report.warnings.append(issue)
    if res.field_id not in report.field_statuses:
        report.field_statuses[res.field_id] = "WARN"


def validate_answers(
    resolutions: list[AnswerResolution],
    profile: dict[str, Any],
) -> ValidationReport:
    """Run all cross-field and per-field validation rules.

    Returns a ValidationReport. If status == "FAIL", submission MUST be blocked.
    """
    report = ValidationReport(validated_at=now_iso())

    # Build lookup by question type
    by_type: dict[str, AnswerResolution] = {}
    for res in resolutions:
        by_type[res.question_type] = res
        report.field_statuses[res.field_id] = "PASS"

    wa = profile.get("workAuth") or {}
    sec = profile.get("security") or {}

    # ── Rule 1: LLM must not generate answers for sensitive factual fields ──
    for res in resolutions:
        qtype_str = res.question_type
        try:
            qtype = QuestionType(qtype_str)
        except ValueError:
            continue
        if qtype in SENSITIVE_FACTUAL_TYPES and res.resolution_method == LLM_GENERATED_TEXT:
            _add_error(report, res, "SENSITIVE_LLM_BLOCKED",
                       f"LLM-generated answer for sensitive field '{qtype_str}' is not allowed")

    # ── Rule 2: H1B + sponsorship = No → BLOCK ──
    auth_type = wa.get("authorizationType", "").upper()
    spons_res = by_type.get(QuestionType.SPONSORSHIP_REQUIRED.value)
    if spons_res and auth_type == "H1B":
        if spons_res.answer and spons_res.answer.lower().startswith("no"):
            _add_error(report, spons_res, "H1B_SPONSORSHIP_INCONSISTENCY",
                       "Candidate is on H1B but sponsorship was answered 'No'")

    # ── Rule 3: Not US citizen + export control = "US citizen" → BLOCK ──
    export_res = by_type.get(QuestionType.EXPORT_CONTROL.value)
    if export_res and not wa.get("usCitizen", False) and not wa.get("usNational", False):
        answer_lower = (export_res.answer or "").lower()
        if re.search(r"united states citizen|u\.s\.\s*citizen|citizen or national", answer_lower):
            _add_error(report, export_res, "CITIZENSHIP_EXPORT_INCONSISTENCY",
                       "Candidate is not a US citizen but export control answer claims citizenship")

    # ── Rule 4: Not US citizen + citizenship = Yes → BLOCK ──
    citizen_res = by_type.get(QuestionType.CITIZENSHIP.value)
    if citizen_res and not wa.get("usCitizen", False):
        if citizen_res.answer and citizen_res.answer.lower() == "yes":
            _add_error(report, citizen_res, "CITIZENSHIP_INCONSISTENCY",
                       "Candidate is not a US citizen but citizenship was answered 'Yes'")

    # ── Rule 5: H1B + permanent authorization = Yes → BLOCK ──
    perm_res = by_type.get(QuestionType.PERMANENT_WORK_AUTHORIZATION.value)
    if perm_res and not wa.get("permanentWorkAuthorization", False):
        if perm_res.answer and perm_res.answer.lower().startswith("yes"):
            _add_error(report, perm_res, "PERMANENT_AUTH_INCONSISTENCY",
                       "Candidate does not have permanent work authorization but answered 'Yes'")

    # ── Rule 6: Location city/state mismatch → BLOCK ──
    state_res = by_type.get(QuestionType.STATE.value)
    city_res = by_type.get(QuestionType.CITY.value) or by_type.get(QuestionType.LOCATION.value)
    profile_city = (profile.get("city") or "").lower()
    profile_state = (profile.get("state") or "").lower()

    if state_res and profile_state:
        answer_state = (state_res.answer or "").lower()
        if answer_state and profile_state not in answer_state and answer_state not in profile_state:
            # Check for abbreviation match (e.g., "WA" vs "Washington")
            state_abbrevs = {"washington": "wa", "california": "ca", "new york": "ny", "texas": "tx",
                             "illinois": "il", "florida": "fl", "north dakota": "nd"}
            profile_abbrev = state_abbrevs.get(profile_state, "")
            if not (profile_abbrev and profile_abbrev in answer_state):
                _add_error(report, state_res, "STATE_MISMATCH",
                           f"Profile state is '{profile.get('state')}' but answer is '{state_res.answer}'")

    # ── Rule 7: Ethnicity question answered with race option → BLOCK ──
    hispanic_res = by_type.get(QuestionType.ETHNICITY_HISPANIC_LATINO.value)
    if hispanic_res and hispanic_res.answer:
        answer_lower = hispanic_res.answer.lower()
        race_keywords = ["american indian", "alaska", "asian", "black", "african",
                         "native hawaiian", "pacific islander", "white", "caucasian"]
        if any(kw in answer_lower for kw in race_keywords):
            _add_error(report, hispanic_res, "ETHNICITY_RACE_CROSSOVER",
                       f"Race option '{hispanic_res.answer}' was used to answer an ethnicity question")

    # ── Rule 8: Race question answered with ethnicity option → BLOCK ──
    race_res = by_type.get(QuestionType.RACE.value)
    if race_res and race_res.answer:
        answer_lower = race_res.answer.lower()
        if any(kw in answer_lower for kw in ["hispanic", "latino", "latina", "latinx"]):
            if "not hispanic" not in answer_lower and "non hispanic" not in answer_lower:
                _add_error(report, race_res, "RACE_ETHNICITY_CROSSOVER",
                           f"Ethnicity option '{race_res.answer}' was used to answer a race question")

    # ── Rule 9: Phone field contains only country code → BLOCK ──
    phone_res = by_type.get(QuestionType.PHONE.value)
    if phone_res and phone_res.answer:
        digits = re.sub(r"[^\d]", "", phone_res.answer)
        if len(digits) < 7:
            _add_error(report, phone_res, "PHONE_INCOMPLETE",
                       f"Phone field contains '{phone_res.answer}' — no actual phone number")

    # ── Rule 10: Low confidence on required field → WARNING ──
    for res in resolutions:
        if res.confidence < 0.75 and res.answer:
            _add_warning(report, res, "LOW_CONFIDENCE",
                         f"Confidence {res.confidence:.2f} is below 0.75 threshold")

    # ── Rule 11: Security clearance inferred from resume → BLOCK ──
    clearance_res = by_type.get(QuestionType.SECURITY_CLEARANCE_ELIGIBILITY.value)
    if clearance_res and not sec.get("eligibleForUSSecurityClearance", False):
        if clearance_res.answer and clearance_res.answer.lower().startswith("yes"):
            _add_error(report, clearance_res, "CLEARANCE_ELIGIBILITY_INCONSISTENCY",
                       "Profile indicates not eligible for security clearance but answered 'Yes'")

    # ── Rule 12: Name used as location → BLOCK ──
    loc_res = by_type.get(QuestionType.LOCATION.value) or by_type.get(QuestionType.CITY.value)
    if loc_res and loc_res.answer:
        first_name = (profile.get("firstName") or "").lower()
        last_name = (profile.get("lastName") or "").lower()
        loc_lower = loc_res.answer.lower().strip()
        if first_name and loc_lower == first_name:
            _add_error(report, loc_res, "NAME_AS_LOCATION",
                       f"Candidate's first name '{first_name}' was used as location")
        if last_name and loc_lower == last_name:
            _add_error(report, loc_res, "NAME_AS_LOCATION",
                       f"Candidate's last name '{last_name}' was used as location")

    return report
