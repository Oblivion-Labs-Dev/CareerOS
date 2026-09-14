"""Job-specific resume bullet tailoring, gated by the Off / Honest / Aggressive dial.

The underlying generator (`generate_resume_bullets_for_job`) is deliberately
truth-safe — its system prompt forbids inventing or amplifying claims beyond
the supplied accomplishment evidence, regardless of mode. That constraint is
NOT relaxed for "Aggressive": what changes between modes is phrasing latitude
(tone) and, at the Off end, whether any rewriting happens at all. Every result
is a diff — original vs. tailored, per bullet — so nothing is ever silently
applied to the base resume; the caller must explicitly accept it.
"""

from __future__ import annotations

from typing import Any

TAILORING_TONE_BY_MODE = {
    "off": "professional",
    "honest": "professional, precise",
    "aggressive": "confident, achievement-forward",
}


def passthrough_diff(accomplishments: list[dict[str, Any]]) -> dict[str, Any]:
    """Off mode: no rewriting, every bullet passes through unchanged."""
    bullets = []
    for acc in accomplishments:
        original = str(acc.get("currentBullet") or acc.get("description") or "").strip()
        if not original:
            continue
        bullets.append(
            {
                "id": acc.get("id"),
                "company": str(acc.get("company", "")),
                "role": str(acc.get("role", "")),
                "project": str(acc.get("project", "")),
                "original": original,
                "tailored": original,
                "changed": False,
            }
        )
    return {
        "mode": "off",
        "bullets": bullets,
        "skillsList": [],
        "atsMatchScore": None,
        "overallCritique": "Tailoring is off — your resume bullets are shown unchanged.",
    }


def build_tailoring_diff(
    accomplishments: list[dict[str, Any]],
    generation_result: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    """Pair the generator's optimized bullets back up with their originals."""
    sources = {str(acc.get("id")): acc for acc in accomplishments if acc.get("id")}
    bullets = []
    for item in generation_result.get("resumeBullets", []):
        source_id = str(item.get("id", ""))
        source = sources.get(source_id)
        original = str(item.get("original") or (source.get("currentBullet") or source.get("description") or "" if source else "")).strip()
        tailored = str(item.get("optimizedBullet", "")).strip()
        bullets.append(
            {
                "id": source_id,
                "company": item.get("company", ""),
                "role": item.get("role", ""),
                "project": item.get("project", ""),
                "original": original,
                "tailored": tailored,
                "changed": original != tailored,
                "source": item.get("source"),
                "selectionReason": item.get("selectionReason"),
            }
        )
    return {
        "mode": mode,
        "bullets": bullets,
        "skillsList": generation_result.get("skillsList", []),
        "atsMatchScore": generation_result.get("atsMatchScore"),
        "overallCritique": generation_result.get("overallCritique", ""),
        "warnings": generation_result.get("warnings", []),
        "requirementCoverage": generation_result.get("requirementCoverage"),
        "method": generation_result.get("method"),
    }
