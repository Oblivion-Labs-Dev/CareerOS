"""Bridge accomplishment entities into flat records for matching and graphs."""

from __future__ import annotations

from typing import Any


def accomplishment_to_record(acc: dict[str, Any]) -> dict[str, Any]:
    phase = acc.get("phaseOne") or {}
    return {
        "id": str(acc.get("id") or ""),
        "title": acc.get("title") or acc.get("project") or "Untitled",
        "company": acc.get("company") or "",
        "project": acc.get("project") or acc.get("title") or "",
        "currentBullet": acc.get("currentBullet") or "",
        "summary": acc.get("summary") or phase.get("summary") or "",
        "technicalChallenge": acc.get("technicalChallenge") or phase.get("technicalChallenge") or "",
        "architectureDecision": acc.get("architectureDecision") or phase.get("architectureDecision") or "",
        "technologies": _str_list(acc.get("technologies")),
        "domains": _str_list(acc.get("domains")),
        "concepts": _str_list(acc.get("concepts")),
        "metrics": _metric_list(acc.get("metrics")),
        "evidence": _evidence_list(acc.get("evidence")),
        "concerns": _concern_list(acc.get("concerns") or acc.get("reviewerConcerns")),
        "interviewQuestions": _question_list(acc.get("interviewQuestions")),
        "resumeVariants": _variant_list(acc.get("resumeVariants") or acc.get("resumeEvolution")),
        "readiness": acc.get("readiness") or "draft",
        "roastResistance": int(acc.get("roastResistance") or 0),
        "personId": acc.get("personId") or "",
    }


def scan_candidate_to_record(candidate: dict[str, Any], person_id: str = "") -> dict[str, Any]:
    return {
        "id": candidate.get("id") or candidate.get("tempId") or "",
        "title": candidate.get("title") or "Imported accomplishment",
        "company": candidate.get("company") or "",
        "project": candidate.get("project") or candidate.get("title") or "",
        "currentBullet": candidate.get("bullet") or candidate.get("currentBullet") or "",
        "summary": candidate.get("summary") or "",
        "technicalChallenge": candidate.get("technicalChallenge") or "",
        "architectureDecision": candidate.get("architectureDecision") or "",
        "technologies": _str_list(candidate.get("technologies")),
        "domains": _str_list(candidate.get("domains")),
        "concepts": _str_list(candidate.get("concepts")),
        "metrics": _metric_list(candidate.get("metrics")),
        "evidence": [],
        "concerns": [],
        "interviewQuestions": [],
        "resumeVariants": [],
        "readiness": "draft",
        "roastResistance": 0,
        "personId": person_id,
    }


def _str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def _metric_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "value": str(item.get("value") or ""),
            "verification": item.get("verification") or "needs-evidence",
        })
    return out


def _evidence_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "type": str(item.get("type") or ""),
        })
    return out


def _concern_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": str(item.get("id") or ""),
            "concern": str(item.get("concern") or item.get("text") or ""),
        })
    return out


def _question_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": str(item.get("id") or ""),
            "question": str(item.get("question") or ""),
        })
    return out


def _variant_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("variant") or "Resume variant"),
        })
    return out
