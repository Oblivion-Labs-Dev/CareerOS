"""Stage 10 (critiqueResumeStyle): a separate DeepSeek pass that scores each bullet's writing and lists problems.

The critic returns scores and issue codes only, never text, so it cannot change a fact. Its findings join the
deterministic lint; only flagged, unlocked bullets are then restyled, and a restyle must keep every number,
technology and citation (style.same_facts) and still validate.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.services.career_compiler import prompts
from app.services.career_compiler.deepseek import DeepSeekClient, DeepSeekError
from app.services.career_compiler.models import Bullet, JobDescription

logger = logging.getLogger("careeros.career_compiler")
CRITIC_VERSION = "style-critic-v1"
CODES = ("technical_specificity", "jd_relevance", "clarity", "seniority", "redundancy", "unnecessary_adjectives",
         "density", "repeated_pattern", "generic_ai_language", "voice_mismatch")
#: A critic score below this, with the critic asking for a rewrite, sends the bullet to the restyle pass.
REWRITE_BELOW = 70


class CriticIssue(BaseModel):
    code: str
    message: str = ""


class BulletCritique(BaseModel):
    bullet_id: str
    style_score: int = Field(default=75, ge=0, le=100)
    issues: list[CriticIssue] = Field(default_factory=list)
    rewrite: bool = False


class _Critique(BaseModel):
    bullets: list[BulletCritique] = Field(default_factory=list)


def critique_resume_style(bullets: list[Bullet], jd: JobDescription, llm: DeepSeekClient, exemplars: list[str]
                          ) -> tuple[dict[str, BulletCritique], dict, list[str]]:
    if not bullets or not llm.configured:
        return {}, {}, []
    requirements = {r.id: r.normalized_requirement for r in jd.requirements}
    payload = {"role": jd.title, "style_exemplars": exemplars,
               "bullets": [{"bullet_id": b.id, "text": b.text,
                            "targets": [requirements[r["id"]] for r in b.requirements if r.get("id") in requirements][:3]}
                           for b in bullets]}
    try:
        result, meta = llm.complete_json(task="critique_style", system=prompts.CRITIC_SYSTEM, user=payload,
                                         schema=_Critique, max_tokens=2500, temperature=0.0)
    except DeepSeekError as exc:
        logger.warning("Style critic unavailable: %s", exc.code)
        return {}, {}, [f"Style critic unavailable ({exc}); used the deterministic lint only."]
    known = {b.id for b in bullets}
    out = {}
    for item in result.bullets:
        if item.bullet_id not in known or item.bullet_id in out:
            continue
        issues = [CriticIssue(code=i.code if i.code in CODES else "clarity", message=i.message[:200]) for i in item.issues[:4]]
        out[item.bullet_id] = item.model_copy(update={"issues": issues})
    return out, meta, []


def lint_score(findings: list[dict]) -> int:
    return max(0, 100 - 20 * sum(f["severity"] == "rewrite" for f in findings) - 7 * sum(f["severity"] == "flag" for f in findings))


def combine(findings: dict[str, list[dict]], critiques: dict[str, BulletCritique]) -> dict[str, dict]:
    """Per bullet: style_score (critic when available, else lint), issues from both, and whether to restyle."""
    out = {}
    for bullet_id, lint in findings.items():
        critique = critiques.get(bullet_id)
        issues = list(lint)
        rewrite = any(f["severity"] == "rewrite" for f in lint)
        if critique:
            flagged = critique.rewrite and critique.style_score < REWRITE_BELOW
            issues += [{"code": f"critic:{i.code}", "severity": "rewrite" if flagged else "flag",
                        "message": i.message or i.code.replace("_", " ")} for i in critique.issues]
            rewrite = rewrite or flagged
        out[bullet_id] = {"style_score": min(critique.style_score, lint_score(lint) + 10) if critique else lint_score(lint),
                          "source": "critic" if critique else "lint", "issues": issues, "rewrite": rewrite}
    return out
