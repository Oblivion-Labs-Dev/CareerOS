"""Evidence-aware ATS match engine for resume corpus + profile."""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.application_assistant.job_matching import _parse_qualifications, match_job
from app.services.resume_intelligence.corpus_adapter import accomplishment_to_record
from app.services.resume_intelligence.text_utils import extract_keywords, text_blob

CoverageKind = Literal["explicit", "inferred", "unsupported", "missing"]


def _record_direct_text(record: dict[str, Any]) -> str:
    return text_blob([
        record.get("title"),
        record.get("currentBullet"),
        record.get("summary"),
        record.get("technologies"),
        [f"{m.get('name', '')} {m.get('value', '')}" for m in record.get("metrics", [])],
        [f"{e.get('name', '')} {e.get('type', '')}" for e in record.get("evidence", [])],
    ])


def _record_context_text(record: dict[str, Any]) -> str:
    return text_blob([
        record.get("technicalChallenge"),
        record.get("architectureDecision"),
        record.get("domains"),
        record.get("concepts"),
    ])


def _has_explicit_proof(term: str, record: dict[str, Any]) -> bool:
    evidence_text = text_blob([
        [f"{e.get('name', '')} {e.get('type', '')}" for e in record.get("evidence", [])],
    ])
    if term in evidence_text:
        return True
    for metric in record.get("metrics", []):
        if metric.get("verification") != "verified":
            continue
        metric_text = f"{metric.get('name', '')} {metric.get('value', '')}".lower()
        if term in metric_text:
            return True
    return False


def _classify_keyword(term: str, records: list[dict[str, Any]]) -> tuple[CoverageKind, list[str]]:
    direct_matches = [r for r in records if term in _record_direct_text(r)]
    contextual_matches = [r for r in records if term in _record_context_text(r)]

    if any(_has_explicit_proof(term, r) for r in direct_matches):
        coverage: CoverageKind = "explicit"
    elif direct_matches:
        coverage = "unsupported"
    elif contextual_matches:
        coverage = "inferred"
    else:
        coverage = "missing"

    record_ids = list({*(r["id"] for r in direct_matches), *(r["id"] for r in contextual_matches)})
    return coverage, record_ids


def build_ats_keyword_sets(job_description: str, job_title: str = "") -> dict[str, Any]:
    keywords = extract_keywords(f"{job_title} {job_description}", limit=50)
    required, preferred = _parse_qualifications(job_description)

    skill_like = [k for k in keywords if re.match(r"^[a-z0-9+#.-]+$", k)]
    return {
        "primary": keywords[:25],
        "skills": skill_like[:20],
        "requiredPhrases": required[:12],
        "preferredPhrases": preferred[:12],
    }


def match_corpus_to_job(
    accomplishments: list[dict[str, Any]],
    job_description: str,
    *,
    job_title: str = "",
    profile: dict[str, Any] | None = None,
    resume_text: str = "",
) -> dict[str, Any]:
    records = [accomplishment_to_record(a) for a in accomplishments]
    if resume_text.strip():
        records.append({
            "id": "__resume_text__",
            "title": "Uploaded resume",
            "company": "",
            "project": "",
            "currentBullet": resume_text[:4000],
            "summary": resume_text[:2000],
            "technicalChallenge": "",
            "architectureDecision": "",
            "technologies": extract_keywords(resume_text, limit=30),
            "domains": [],
            "concepts": [],
            "metrics": [],
            "evidence": [],
            "concerns": [],
            "interviewQuestions": [],
            "resumeVariants": [],
            "readiness": "draft",
            "roastResistance": 0,
            "personId": "",
        })

    keywords = extract_keywords(f"{job_title} {job_description}", limit=40)
    keyword_matches: list[dict[str, Any]] = []
    for term in keywords:
        coverage, record_ids = _classify_keyword(term, records)
        keyword_matches.append({"term": term, "coverage": coverage, "recordIds": record_ids})

    explicit = [m for m in keyword_matches if m["coverage"] == "explicit"]
    inferred = [m for m in keyword_matches if m["coverage"] == "inferred"]
    unsupported = [m for m in keyword_matches if m["coverage"] == "unsupported"]
    missing = [m for m in keyword_matches if m["coverage"] == "missing"]

    score = 0
    if keywords:
        score = round(((len(explicit) + len(inferred) * 0.2) / len(keywords)) * 100)

    relevant = sorted(
        (
            {
                "recordId": record["id"],
                "title": record["title"],
                "company": record["company"],
                "hits": sum(1 for m in keyword_matches if record["id"] in m["recordIds"]),
                "readiness": record.get("readiness"),
            }
            for record in records
            if record["id"] != "__resume_text__"
            and any(record["id"] in m["recordIds"] for m in keyword_matches)
        ),
        key=lambda item: (-item["hits"], item.get("title") or ""),
    )[:8]

    ats_sets = build_ats_keyword_sets(job_description, job_title)
    matched_skills = [s for s in ats_sets["skills"] if any(m["term"] == s and m["coverage"] != "missing" for m in keyword_matches)]
    gap_skills = [s for s in ats_sets["skills"] if s not in matched_skills]

    profile_match: dict[str, Any] | None = None
    if profile:
        profile_match = match_job(
            {"title": job_title, "description": job_description},
            profile,
        )

    call_likelihood = "low"
    if score >= 75 and len(explicit) >= max(3, len(keywords) // 4):
        call_likelihood = "high"
    elif score >= 50 or len(explicit) >= 2:
        call_likelihood = "medium"

    return {
        "overallScore": score,
        "callLikelihood": call_likelihood,
        "keywordMatches": keyword_matches,
        "explicit": explicit,
        "inferred": inferred,
        "unsupported": unsupported,
        "missing": missing,
        "relevantAccomplishments": relevant,
        "atsKeywordSets": {
            **ats_sets,
            "matchedSkills": matched_skills,
            "gapSkills": gap_skills,
        },
        "profileMatch": profile_match,
        "summary": _build_summary(score, explicit, missing, gap_skills),
    }


def _build_summary(
    score: int,
    explicit: list[dict[str, Any]],
    missing: list[dict[str, Any]],
    gap_skills: list[str],
) -> str:
    parts = [f"Evidence-aware match score is {score}%."]
    if explicit:
        parts.append(f"{len(explicit)} keywords have explicit proof in your corpus.")
    if missing:
        parts.append(f"{len(missing)} priority keywords are missing or unsupported.")
    if gap_skills[:5]:
        parts.append(f"Top ATS gaps: {', '.join(gap_skills[:5])}.")
    return " ".join(parts)
