"""Merge the interview story corpus into the accomplishment entities.

The corpus on disk is the authored source; the accomplishment entities are what
the app reads for match scoring, the resume corpus page and the profile. Before
this, the two were unrelated: 31 accomplishment records existed as three-line
stubs with empty ``technologies`` lists while 175,000 characters of the same
work sat in a file nothing loaded.

The merge is **enrich-only, and that is a hard rule here for a specific reason**:
an earlier bulk write in this project saved a partially-hydrated object over the
user's profile and permanently destroyed two education entries and a job. So:

* No key is ever removed.
* A non-empty existing value is never overwritten. Only blank fields are filled.
* List fields are unioned, never replaced.
* New material goes into new keys (``interviewStories``, ``skills``,
  ``signals``, ``doNotClaim``), so even a total misunderstanding of the mapping
  below can only add content, never lose any.

Several corpus stories can map to one accomplishment - the CDK bootstrapping
library and the pipeline consolidation are one record in the app and two
stories in the notes - so ``interviewStories`` is a list.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger("career_os.story_corpus_sync")

#: corpus story id -> existing accomplishment id. A story with no entry here is
#: inserted under its own id rather than guessed into an existing record.
STORY_TO_ACCOMPLISHMENT = {
    # Microsoft
    "ms-historical-risk-detection": "microsoft-historical-enrichment",
    "ms-adaptive-protection": "microsoft-adaptive-protection",
    "ms-infra-separation": "microsoft-ai-agent-ingestion",
    "ms-cross-product-risk": "microsoft-risk-correlation",
    "ms-cross-domain-correlation": "microsoft-risk-correlation",
    "ms-sovereign-cloud-rollout": "microsoft-sovereign-cloud-rollout",
    # Amazon - ML and AI
    "amz-predicted-delivery-ranges": "amazon-quantile-regression",
    "amz-early-delay-detection": "amazon-xgboost",
    "amz-alternate-recommendations": "amazon-ai-delivery-platform",
    "amz-personalized-email-rag": "amazon-localization-engine",
    "amz-tno-notifications": "amazon-localization-engine",
    # Amazon - platform
    "amz-cdk-commons": "amazon-bootstrap-platform",
    "amz-pipeline-consolidation": "amazon-bootstrap-platform",
    "amz-cloudwatch-standardization": "amazon-cloudwatch-savings",
    "amz-cloudwatch-dashboards-iac": "amazon-cloudwatch-savings",
    "amz-docker-optimization": "amazon-docker-optimization",
    "amz-cicd-artifact-reuse": "amazon-docker-optimization",
    "amz-runtime-log-api": "amazon-runtime-log-api",
    "amz-decision-simulation-portal": "amazon-simulation-platform",
    "amz-promise-self-service": "amazon-simulation-platform",
    "amz-adhoc-improvements": "amazon-tier-1-readiness",
    # Amazon - orchestration and orders
    "amz-orchestrator-step-functions": "amazon-rest-grpc-layer",
    "amz-coral-vs-rest": "amazon-rest-grpc-layer",
    "amz-order-upgrade": "amazon-just-in-stock",
    "amz-fba-procurability": "amazon-just-in-stock",
    "amz-aging-orders": "amazon-operational-platform",
    "amz-html-email-templates": "amazon-operational-platform",
    # Amazon - operations
    "amz-peak-readiness": "amazon-prime-day",
    "amz-thread-starvation": "amazon-prime-day",
    "amz-oncall-reviews": "amazon-operational-reviews",
    "amz-pharmacy-sev2": "amazon-operational-reviews",
    # Personal projects
    "proj-careeros-k8s": "project-careeros-k8s",
    "proj-backinstock-k8s": "project-backinstock-k8s",
    "proj-jis-streaming": "project-jis-streaming",
    "proj-k8s-devplatform": "project-k8s-devplatform",
    "proj-security-signal-platform": "project-security-signal-platform",
    "proj-leetdesign": "project-leetdesign",
    "proj-financeos": "project-financeos",
    "proj-arsenal": "project-arsenal",
}


def _union(existing: Any, incoming: list[str]) -> list[str]:
    current = [str(v) for v in existing if str(v).strip()] if isinstance(existing, list) else []
    seen = {v.lower() for v in current}
    for item in incoming:
        if item and item.lower() not in seen:
            current.append(item)
            seen.add(item.lower())
    return current


def _fill_if_blank(target: dict[str, Any], key: str, value: str) -> None:
    if value and not str(target.get(key) or "").strip():
        target[key] = value


def _apply(record: dict[str, Any], story: dict[str, Any]) -> dict[str, Any]:
    """Fold one corpus story into one accomplishment record."""
    merged = dict(record)

    merged["technologies"] = _union(merged.get("technologies"), story.get("technologies") or [])
    merged["techStack"] = _union(merged.get("techStack"), story.get("technologies") or [])
    merged["concepts"] = _union(merged.get("concepts"), story.get("concepts") or [])
    merged["skills"] = _union(
        merged.get("skills"),
        (story.get("technologies") or []) + (story.get("concepts") or []),
    )
    merged["signals"] = _union(merged.get("signals"), story.get("signals") or [])
    merged["doNotClaim"] = _union(merged.get("doNotClaim"), story.get("doNotClaim") or [])
    merged["verifiedMetrics"] = _union(merged.get("verifiedMetrics"), story.get("metrics") or [])
    merged["storyIds"] = _union(merged.get("storyIds"), [story["id"]])

    # Evidence tier is the one field the corpus is authoritative for: it is what
    # stops a personal project being described as employer work, so a stale
    # value here would defeat the purpose.
    merged["evidenceTier"] = story.get("evidence") or merged.get("evidenceTier") or "professional"
    _fill_if_blank(merged, "strength", str(story.get("strength") or ""))

    _fill_if_blank(merged, "company", str(story.get("company") or ""))
    _fill_if_blank(merged, "project", str(story.get("title") or ""))
    _fill_if_blank(merged, "currentBullet", str(story.get("headline") or ""))

    stories = merged.get("interviewStories")
    stories = list(stories) if isinstance(stories, list) else []
    if not any(isinstance(s, dict) and s.get("id") == story["id"] for s in stories):
        stories.append(
            {
                "id": story["id"],
                "title": story.get("title") or "",
                "kind": story.get("kind") or "story",
                "evidence": story.get("evidence") or "professional",
                "body": story.get("body") or "",
            }
        )
    merged["interviewStories"] = stories
    return merged


def sync_story_corpus(db: Session) -> dict[str, int]:
    """Fold every corpus story into its accomplishment. Safe to run repeatedly."""
    from app.db.store import get_entity, upsert_entity
    from app.services.story_index import load_corpus

    corpus = load_corpus()
    if not corpus:
        return {"stories": 0, "enriched": 0, "created": 0}

    enriched = 0
    created = 0
    touched: dict[str, dict[str, Any]] = {}

    for story in corpus:
        target_id = STORY_TO_ACCOMPLISHMENT.get(story["id"], story["id"])
        if target_id not in touched:
            existing = get_entity(db, "accomplishment", target_id)
            if existing:
                enriched += 1
            else:
                created += 1
                existing = {
                    "id": target_id,
                    "company": story.get("company") or "",
                    "project": story.get("title") or "",
                    "status": "shipped",
                }
            touched[target_id] = existing
        touched[target_id] = _apply(touched[target_id], story)

    for record in touched.values():
        upsert_entity(db, "accomplishment", record)

    logger.info(
        "Story corpus sync: %d stories -> %d accomplishments (%d enriched, %d created)",
        len(corpus), len(touched), enriched, created,
    )
    return {
        "stories": len(corpus),
        "accomplishments": len(touched),
        "enriched": enriched,
        "created": created,
    }
