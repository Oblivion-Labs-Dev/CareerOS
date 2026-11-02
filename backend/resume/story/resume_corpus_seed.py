import json
from pathlib import Path
from typing import Any

CHECKLIST_KEYS = (
    "problemExplained",
    "businessProblemExplained",
    "technicalProblemExplained",
    "architectureExplained",
    "tradeoffsExplained",
    "scaleIncluded",
    "metricsIncluded",
    "impactIncluded",
    "leadershipShown",
    "ownershipShown",
    "decisionShown",
    "failureHandlingExplained",
    "performanceExplained",
    "securityExplained",
    "reliabilityExplained",
    "devProductivityExplained",
    "platformThinkingShown",
    "operationalOwnershipShown",
    "customerImpactShown",
    "businessImpactShown",
    "evidenceAttached",
    "interviewStoryAvailable",
    "diagramAvailable",
    "rfcAttached",
)

RESUME_VARIANT_KEYS = (
    "improved",
    "top10Percent",
    "top1Percent",
    "atsOptimized",
    "hmFavorite",
    "principalFavorite",
    "mostTechnical",
    "mostBusiness",
    "mostConcise",
    "interview",
    "linkedin",
    "star",
)


def load_resume_corpus_seed(path: Path) -> list[dict[str, Any]]:
    """Load the shared, fact-only resume corpus seed without failing API startup."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict) and str(item.get("id", "")).strip()]


def _strings(seed: dict[str, Any], key: str) -> list[str]:
    value = seed.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _missing_items_for(seed: dict[str, Any], *keywords: str) -> list[str]:
    items = _strings(seed, "missing")
    if not keywords:
        return items
    return [item for item in items if any(keyword in item.lower() for keyword in keywords)]


def resume_corpus_seed_to_accomplishment(seed: dict[str, Any]) -> dict[str, Any]:
    """Map a concise shared seed record into the legacy Accomplishment contract."""
    accomplishment_id = str(seed["id"])
    title = str(seed.get("title", "Untitled accomplishment"))
    bullet = str(seed.get("currentBullet", ""))
    problem = str(seed.get("problem", ""))
    business_context = str(seed.get("businessContext", ""))
    technical_context = str(seed.get("technicalContext", ""))
    ownership = str(seed.get("ownership", ""))
    impact = str(seed.get("impact", ""))
    architecture_decision = str(seed.get("architectureDecision", ""))
    tools = _strings(seed, "tools")
    scale = _strings(seed, "scale")
    missing = _missing_items_for(seed)
    metrics = [item for item in seed.get("metrics", []) if isinstance(item, dict)]
    evidence_names = _strings(seed, "evidence")

    checklist = dict.fromkeys(CHECKLIST_KEYS, False)
    checklist.update(
        {
            "problemExplained": bool(problem or bullet),
            "businessProblemExplained": bool(business_context),
            "technicalProblemExplained": bool(technical_context),
            "architectureExplained": bool(architecture_decision),
            "scaleIncluded": bool(scale or metrics),
            "metricsIncluded": bool(metrics),
            "impactIncluded": bool(impact),
            "ownershipShown": bool(ownership),
            "decisionShown": bool(architecture_decision),
            "businessImpactShown": bool(impact),
            "evidenceAttached": bool(evidence_names),
        }
    )
    completeness = round(100 * sum(checklist.values()) / len(checklist))

    metric_metadata = {
        f"{accomplishment_id}-metric-{index}": {
            "confidence": "medium",
            "verification": str(metric.get("verification", "needs-evidence")),
            "source": str(metric.get("source", "")),
        }
        for index, metric in enumerate(metrics)
    }

    return {
        "id": accomplishment_id,
        "company": str(seed.get("company", "")),
        "team": "",
        "project": title,
        "timePeriod": "",
        "techStack": tools,
        "status": "current",
        "problemContext": {
            "what": problem or bullet,
            "why": business_context,
            "who": "",
            "businessContext": business_context,
            "engineeringContext": technical_context,
        },
        "roleDetails": {
            "responsibility": ownership,
            "ownership": ownership,
            "contributions": [],
        },
        "challenges": [technical_context] if technical_context else [],
        "decisions": {
            "what": architecture_decision,
            "why": "",
            "alternatives": [],
            "tradeoffs": "",
            "rejectedApproaches": [],
            "failureConsiderations": "",
        },
        "systemDesign": {
            "diagramType": "text",
            "diagramContent": "",
            "dataFlow": "",
            "eventFlow": "",
        },
        "concepts": [],
        "technologies": tools,
        "scaleMetrics": [
            {"metric": str(metric.get("name", "Metric")), "value": str(metric.get("value", ""))}
            for metric in metrics
        ],
        "scaleDetails": "\n".join(scale),
        "impact": {"business": [impact] if impact else [], "engineering": []},
        "leadership": [],
        "crossTeamInfluence": "",
        "mentorship": "",
        "evidence": [{"type": "doc", "name": name, "url": ""} for name in evidence_names],
        "completenessChecklist": checklist,
        "completenessStatus": (
            "Needs information"
            if missing
            else ("Complete" if completeness >= 90 else "Incomplete")
        ),
        "missingQuestions": [],
        "resumeEvolution": {
            "current": bullet,
            **{key: "" for key in RESUME_VARIANT_KEYS},
        },
        "confidenceScores": {
            "truth": 80,
            "metric": 35 if metrics else 0,
            "architecture": 55 if architecture_decision else 0,
            "leadership": 0,
            "businessImpact": 55 if impact else 0,
            "engineeringImpact": 0,
            "evidence": 35 if evidence_names else 0,
            "resume": completeness,
            "interview": 0,
        },
        "roastResistanceScore": max(10, min(70, completeness - len(missing) * 2)),
        "roastDeductions": [
            {
                "points": min(5, max(1, 20 // max(1, len(missing)))),
                "reason": item,
                "category": "Missing information",
            }
            for item in missing
        ],
        "missingInformation": missing,
        "roadmap": {
            "top3Improvements": missing[:3],
            "missingMetrics": _missing_items_for(
                seed,
                "metric",
                "number",
                "traffic",
                "scale",
                "latency",
                "volume",
                "user",
                "adoption",
                "team",
                "repository",
                "outcome",
            ),
            "missingArchitecture": _missing_items_for(
                seed,
                "architect",
                "pipeline",
                "design",
                "flow",
                "partition",
                "retry",
                "ordering",
                "dedup",
                "consistency",
                "parallel",
                "protocol",
                "framework",
                "implementation",
                "model",
                "rbac",
                "authentication",
                "auditing",
                "residency",
                "ci/cd",
                "feature flag",
                "rollout",
                "algorithm",
                "scoring",
            ),
            "missingEngineeringDetails": missing,
            "missingBusinessImpact": _missing_items_for(seed, "business", "outcome", "attribution"),
            "missingLeadershipEvidence": _missing_items_for(seed, "ownership", "adoption", "team", "user"),
            "missingInterviewStories": _missing_items_for(seed, "interview", "story"),
            "missingDocumentation": _missing_items_for(seed, "evidence", "link", "diagram", "rfc"),
        },
        "qualityStatusOverrides": {},
        "metricMetadata": metric_metadata,
        "questionMetadata": {},
        "seedSource": "resume-corpus-initial",
    }
