"""Resume Diff & Tailoring Intelligence Service.

Computes fine-grained additions, deletions, and semantic alignments between
a candidate's master resume and job-tailored application materials.
Renders pixel-perfect, watermark-free tailored PDFs preserving authentic formatting and bold headers
across both Microsoft and Amazon experiences.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
from typing import Any
from app.services.application_assistant.llm_client import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_LOCAL_MODEL,
    estimate_tokens,
)
from app.services.application_assistant.tailoring_metadata import authorization_summary, job_match_score

# Rough size of the fixed instruction block in the tailoring prompt (mode
# rules, formatting rules, the absolute-rule paragraph). Measured, not
# guessed: shrink it and this allowance should shrink with it.
INSTRUCTION_TOKEN_ALLOWANCE = 900
# The answer is 17 rewritten bullets, each roughly the length of the original
# plus the <b> markup, so budget the master-bullet size again plus slack.
OUTPUT_TOKEN_HEADROOM = 400
# Never plan to fill the context exactly; chat templates and tokenizer drift
# both cost tokens this estimator cannot see.
CONTEXT_SAFETY_MARGIN = 512

# How many stories the index may retrieve for one posting, and what share of the
# elastic context they may occupy. The job description and the retrieved
# evidence compete for the same leftover space; splitting it rather than giving
# evidence its own allowance is what keeps the prompt inside the window.
EVIDENCE_STORY_LIMIT = 5
EVIDENCE_BUDGET_SHARE = 0.45
# Below this the job description is too truncated to tailor against, so
# evidence yields rather than the posting.
MIN_JD_CHARS = 1200
# Fewest rewritten bullets that still counts as a tailored resume.
MIN_TAILORED_BULLETS = int(os.environ.get("AUTOPILOT_MIN_TAILORED_BULLETS", "3"))
# Bullets per tailoring call. Measured on qwen3:4b: asked for all 17 at once it
# returns 17 bullets in the wrong slots, so almost every rewrite was discarded
# by the alignment and figure guards and the resume went out untailored. Small
# batches keep position stable; batches never span two employers.
BULLET_BATCH_SIZE = int(os.environ.get("CAREEROS_TAILORING_BATCH_SIZE", "4"))

logger = logging.getLogger("career_os.resume_diff_service")

# Canonical 17 bullets from the authentic resume (7 Microsoft + 10 Amazon)
CANONICAL_MASTER_BULLETS: list[dict[str, str]] = [
    {
        "company": "Microsoft",
        "boldPrefix": "Built the historical risk foundation for AI Agent Risk Detection",
        "fullText": "<b>Built the historical risk foundation for AI Agent Risk Detection</b>, reconstructing 90 days of activity across 40+ environments to eliminate onboarding blind spots and enable day-one risk evaluation for 237K+ agents across 13K organizations.",
    },
    {
        "company": "Microsoft",
        "boldPrefix": "Drove architecture across Purview IRM, Entra, and DLP",
        "fullText": "<b>Drove architecture across Purview IRM, Entra, and DLP</b> for Microsoft’s AI-agent Adaptive Protection pipeline, owning design, implementation, and launch from risk scoring through Conditional Access enforcement and shipped the capability with Microsoft 365 E7.",
    },
    {
        "company": "Microsoft",
        "boldPrefix": "Led the redesign of AI-agent ingestion for independent scale and fault isolation",
        "fullText": "<b>Led the redesign of AI-agent ingestion for independent scale and fault isolation</b>, separating agent and human workloads across 28 deployments processing 135K+ security signals/day and protecting existing Insider Risk Management pipelines as agent traffic grew.",
    },
    {
        "company": "Microsoft",
        "boldPrefix": "Led AI Risk Detection's sovereign-cloud architecture and rollout across GCC, GCCH and DoD",
        "fullText": "<b>Led AI Risk Detection's sovereign-cloud architecture and rollout across GCC, GCCH and DoD</b>, engineering deployment and disaster-recovery infrastructure across 53 resource groups and 51 deployments and establishing the first Gov-cloud Kusto monitoring infrastructure.",
    },
    {
        "company": "Microsoft",
        "boldPrefix": "Connected investigations across Microsoft's security ecosystem",
        "fullText": "<b>Connected investigations across Microsoft's security ecosystem</b>, linking related risk across Entra, Defender, Sentinel, Microsoft Graph, and Insider Risk Management and increasing customer engagement with related cross-product investigations 16%.",
    },
    {
        "company": "Microsoft",
        "boldPrefix": "Designed an AI-assisted testing workflow",
        "fullText": "<b>Designed an AI-assisted testing workflow</b> using agent skills and Playwright to provision test tenants, configure Copilot Studio agents with tools/policies, trigger controlled security risks and alerts, and validate end-to-end behavior.",
    },
    {
        "company": "Microsoft",
        "boldPrefix": "Designed an AI-assisted debugging workflow spanning three repositories",
        "fullText": "<b>Designed an AI-assisted debugging workflow spanning three repositories</b>, combining historical incident analysis with Playwright to reproduce issues, implement and validate fixes, capture evidence, and create pull requests.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Built a 0→1 developer platform for 60+ microservices",
        "fullText": "<b>Built a 0→1 developer platform for 60+ microservices</b>, creating a one-click CDK-based workflow that standardized infrastructure, authentication, observability, dependencies, CI/CD, and deployment into a production-ready service; cut setup from 2 weeks to under 1 hour, consolidated 9 pipelines, and saved 40–50 engineering weeks across ~40 engineers and 3 teams.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Led a monolith-to-microservices transformation at 100K+ TPS",
        "fullText": "<b>Led a monolith-to-microservices transformation at 100K+ TPS</b>, building and launching 15+ services and establishing shared REST/gRPC orchestration supporting 10M+ daily transactions while maintaining behavioral parity throughout migration.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Designed and owned the service powering ML-predicted delivery ranges",
        "fullText": "<b>Designed and owned the service powering ML-predicted delivery ranges</b>, integrating a quantile-regression model and coordinating changes across inventory planning and fulfillment optimization systems to replace single-date promises; delivered $28M in annualized impact.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Replaced static delivery-risk rules with ML-driven decisioning",
        "fullText": "<b>Replaced static delivery-risk rules with ML-driven decisioning</b>, using XGBoost on SageMaker to identify at-risk orders and trigger recovery, customer notifications, and alternate-seller recommendations, reducing cancellations and contributing to a 7% increase in sales.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Launched inventory decisioning systems processing 200K+ events/day",
        "fullText": "<b>Launched inventory decisioning systems processing 200K+ events/day</b>, launching Just-In-Stock and Restock Alerting with 30-day order replay and real-time inventory signals; increased restocked-item sales 13% and early deliveries 16%.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Architected built a RAG-based product recommendation system for out-of-stock items",
        "fullText": "<b>Architected built a RAG-based product recommendation system for out-of-stock items</b>, to surface relevant alternatives grounded in real-time inventory and delivery constraints, keeping availability and fulfillment validation deterministic. Increased eligible product sales by 23%",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Led design and cross-functional adoption of an LLM-powered localization platform",
        "fullText": "<b>Led design and cross-functional adoption of an LLM-powered localization platform</b>, using Bedrock with vocabulary-constrained generation and deterministic validation to personalize 37 email templates across 28 locales, with pre-approved template fallbacks on validation failure to address hallucination and compliance risks.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Owned the annual operational improvement roadmap across 60+ services",
        "fullText": "<b>Owned the annual operational improvement roadmap across 60+ services</b>, driving planning and execution across 15+ engineers and reducing Sev2 incidents 40% in two months; led readiness across 90 services for Prime Day and Black Friday with zero major incidents.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Turned synchronized delivery for large Amazon Business orders into a first-class fulfillment capability",
        "fullText": "<b>Turned synchronized delivery for large Amazon Business orders into a first-class fulfillment capability</b>, driving changes across planning, inventory, and fulfillment systems to honor coordinated delivery dates; replaced manual engineering workflows with self-service tooling, eliminated 100–300 engineering hours/year, and improved GCCP 11%.",
    },
    {
        "company": "Amazon",
        "boldPrefix": "Standardized observability and container infrastructure across 60+ services",
        "fullText": "<b>Standardized observability and container infrastructure across 60+ services</b>, introducing shared logging and Docker libraries that cut CloudWatch spend $250K+/month, container size 83%, and build time 50%, with container standards adopted across teams.",
    },
]


def strip_html_tags(text: str) -> str:
    """Remove HTML tags like <b> and </b> for text comparison."""
    return re.sub(r"<[^>]+>", "", text)


def ensure_bold_lead(text: str, fallback_prefix: str = "") -> str:
    """Ensure bullet text starts with a bold lead action phrase formatted as <b>...</b>."""
    text = text.strip()
    # Convert markdown **bold** to <b>bold</b>
    if "**" in text:
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    
    if text.startswith("<b>") and "</b>" in text:
        return text

    # If no bold tags present, wrap the first phrase (up to comma or first 6-8 words) in <b></b>
    if fallback_prefix and fallback_prefix in text:
        return text.replace(fallback_prefix, f"<b>{fallback_prefix}</b>", 1)

    if "," in text:
        parts = text.split(",", 1)
        return f"<b>{parts[0].strip()}</b>, {parts[1].strip()}"

    words = text.split()
    lead = " ".join(words[:5])
    rest = " ".join(words[5:])
    return f"<b>{lead}</b> {rest}".strip()


def finish_sentence(text: str) -> str:
    """Add the full stop the model left off.

    Every bullet on the original resume ends in one. A rewrite that ends on
    "...and compliance risks" is a complete sentence missing a single
    character, and failing it for that would cost a whole retry to fix
    punctuation. Only ever appends - never edits or trims the wording - and
    leaves anything already terminated alone.
    """
    plain = re.sub(r"<[^>]+>", "", str(text or "")).rstrip()
    if not plain or plain.endswith((".", "!", "?", ")", "]", "%", ":", ";", ",")):
        return text
    if plain[-1].isalnum() or plain[-1] in "+\u2019\"":
        return text.rstrip() + "."
    return text


def clamp_bullet_length(text: str, max_len: int, original: str | None = None) -> str:
    """Keep an over-long bullet inside its slot without leaving it mid-sentence.

    Bullets that run long wrap to an extra line in the fixed-height overlay slot
    and collide with the bullet below (see render_tailored_resume_pdf), so a
    hard limit is unavoidable. What changed is what happens at the limit.

    This used to cut at a word boundary and append an ellipsis, which fixed the
    layout and broke the writing: the resume went out carrying bullets that
    stopped mid-thought on "...enable day-one ris…". A trailing ellipsis on a
    resume bullet reads as a bug, not as brevity.

    So: prefer a clean sentence boundary inside the budget; failing that, fall
    back to the candidate's original bullet, which is well-formed and fits by
    construction. A slot keeping its original wording is a smaller loss than a
    slot containing a fragment - and the quality gate counts it honestly as
    "not rewritten" rather than letting a truncation pass as tailoring.
    """
    plain = re.sub(r"<[^>]+>", "", text)
    if len(plain) <= max_len:
        return text

    match = re.match(r"^\s*<b>(.*?)</b>\s*(.*)$", text, re.DOTALL)
    if not match:
        return original if original else text

    lead, rest = match.group(1), match.group(2).lstrip()
    sep = "" if rest[:1] in (",", ".", ";", ":") else " "
    budget = max_len - len(lead) - len(sep)
    if budget > 20 and rest:
        window = rest[:budget]
        # Last sentence end inside the budget, so the bullet still reads as a
        # finished statement rather than a clipped one.
        cut = max(window.rfind(". "), window.rfind("; "), window.rfind("! "))
        if cut > budget * 0.55:
            trimmed = window[: cut + 1].rstrip()
            return f"<b>{lead}</b>{sep}{trimmed}"

    # No sentence boundary inside the budget, so there is no honest way to
    # shorten this bullet without cutting a clause in half. Keep the original.
    #
    # Trimming at a word boundary and adding a full stop was tried and is worse
    # than it looks: it produced "...validate end-to-end behavior in
    # production-like." and "...create pull requests with automated." on a real
    # rendered resume. Both read as sentences to any automated check - they end
    # in a word and a period - while being obvious gibberish to a human. A slot
    # that keeps its original wording costs one rewrite; a slot containing a
    # severed clause costs the application.
    return original if original else text


def compute_text_diff_chunks(original: str, modified: str) -> list[dict[str, str]]:
    """Compute word/token-level diff chunks between original and modified text."""
    orig_clean = strip_html_tags(original)
    mod_clean = strip_html_tags(modified)

    if not orig_clean and not mod_clean:
        return []
    if not orig_clean:
        return [{"type": "add", "text": mod_clean}]
    if not mod_clean:
        return [{"type": "del", "text": orig_clean}]

    matcher = difflib.SequenceMatcher(None, orig_clean.split(" "), mod_clean.split(" "))
    chunks: list[dict[str, str]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            chunks.append({"type": "eq", "text": " ".join(orig_clean.split(" ")[i1:i2])})
        elif tag == "delete":
            chunks.append({"type": "del", "text": " ".join(orig_clean.split(" ")[i1:i2])})
        elif tag == "insert":
            chunks.append({"type": "add", "text": " ".join(mod_clean.split(" ")[j1:j2])})
        elif tag == "replace":
            chunks.append({"type": "del", "text": " ".join(orig_clean.split(" ")[i1:i2])})
            chunks.append({"type": "add", "text": " ".join(mod_clean.split(" ")[j1:j2])})

    return chunks


def compute_bullet_diffs(
    master_bullets: list[str],
    tailored_bullets: list[str],
) -> list[dict[str, Any]]:
    """Compare lists of resume bullet points, aligning corresponding bullets and computing token diffs."""
    results: list[dict[str, Any]] = []

    max_len = max(len(master_bullets), len(tailored_bullets))
    for idx in range(max_len):
        orig = master_bullets[idx] if idx < len(master_bullets) else ""
        tailored = tailored_bullets[idx] if idx < len(tailored_bullets) else ""

        chunks = compute_text_diff_chunks(orig, tailored)
        is_modified = any(c["type"] in ("add", "del") for c in chunks)

        results.append({
            "index": idx,
            "original": orig,
            "tailored": tailored,
            "isModified": is_modified,
            "chunks": chunks,
        })

    return results


def _figure_set(text: str) -> set[str]:
    """The figures a bullet claims, normalised so formatting is not a difference.

    "$28M", "28M" and "28 M" are the same claim; "237K+" and "237K" are the same
    claim. Comparing raw matches treated each rewording as a changed number,
    which is what made the guard below fire on almost every rewrite.
    """
    plain = re.sub(r"<[^>]+>", "", text)
    out: set[str] = set()
    # The lookbehind keeps digits that live inside a word out of the figure set.
    # Without it "K8s" contributed the figure 8, "Log4j" contributed 4 and "S3"
    # contributed 3 - so a rewrite that merely mentioned S3 or Log4j was
    # rejected for introducing a metric the original did not have, and one that
    # dropped the word was logged as losing a number. Neither is a claim about
    # scale, which is the only thing this guard is meant to police.
    for match in re.finditer(r"(?<![A-Za-z0-9])(\d[\d,.]*)\s*([KkMmBb%])?(?![A-Za-z])", plain):
        digits = match.group(1).replace(",", "").rstrip(".")
        if not digits:
            continue
        unit = (match.group(2) or "").lower()
        out.add(f"{digits}{unit}")
    return out


_TAILORING_SYSTEM = (
    "You are an expert ATS resume optimizer. Respond only with a JSON array "
    "of strings."
)

#: Gemini may do the rewriting when a key is configured. It costs no local RAM,
#: which is the constraint that keeps tailoring switched off by default in the
#: first place. Set CAREEROS_GEMINI_TAILORING=off to keep tailoring purely local.
_GEMINI_TAILORING = os.environ.get("CAREEROS_GEMINI_TAILORING", "on").strip().lower() not in (
    "off", "0", "false",
)

#: Gemini needs an object at the top level, while this prompt was tuned to
#: return a bare array. Wrapping the array in one key keeps the prompt - and
#: everything downstream that parses it - exactly as it was.
_GEMINI_BULLET_SCHEMA = {
    "type": "object",
    "properties": {"bullets": {"type": "array", "items": {"type": "string"}}},
    "required": ["bullets"],
}


async def _complete_batch_via_gemini(prompt: str, expected: int) -> dict[str, Any] | None:
    """One batch of bullets from Gemini, or None to fall through to the local model.

    The prompt is the same one the local model gets, hard rules and all, and the
    result goes back through the same parser, the same echo check, the same
    length clamp and the same `_reject_fabrication` guard. Gemini is a different
    writer here, not a different set of rules - it gets no more latitude to
    invent than a local 4B model does.
    """
    if not _GEMINI_TAILORING:
        return None
    try:
        from app.services.gemini.gateway import GeminiRequest, Priority, get_gateway
        from app.services.gemini.schemas import RESUME_TAILORING_VERSION

        result = await get_gateway().submit(GeminiRequest(
            task="resume_tailoring",
            system=_TAILORING_SYSTEM,
            prompt=prompt + (
                "\n\nReturn a JSON object of the form "
                '{"bullets": [...]} whose bullets array holds exactly '
                f"{expected} strings.\n"
            ),
            schema=_GEMINI_BULLET_SCHEMA,
            schema_name="tailored_bullets",
            prompt_version=RESUME_TAILORING_VERSION,
            priority=Priority.RESUME_TAILORING,
            max_tokens=2000,
            deadline_seconds=150.0,
        ))
    except Exception:  # noqa: BLE001 - optional layer, never load-bearing
        logger.warning("Gemini tailoring raised; using the local model", exc_info=True)
        return None

    if not result.ok or not result.data:
        logger.info("Gemini tailoring unavailable (%s); using the local model", result.outcome.value)
        return None

    bullets = [str(item) for item in (result.data.get("bullets") or []) if str(item).strip()]
    if len(bullets) != expected:
        # A wrong count would be silently mapped onto the wrong slots further
        # down, which is the exact failure that once put bullet 3's text in
        # slot 1. Treat it as no answer rather than a partial one.
        logger.info(
            "Gemini returned %d bullets for a batch of %d; using the local model",
            len(bullets), expected,
        )
        return None

    return {
        "success": True,
        "data": json.dumps(bullets),
        "model": f"gemini ({'cached' if result.cached else 'live'})",
        "provider": "gemini",
    }


async def _complete_batch(client: Any, prompt: str, expected: int = 0) -> dict[str, Any]:
    """Gemini when it can, the local model otherwise. Identical output shape."""
    if expected:
        via_gemini = await _complete_batch_via_gemini(prompt, expected)
        if via_gemini is not None:
            return via_gemini
    return await client.complete(
        prompt,
        system=_TAILORING_SYSTEM,
        task="resume_tailoring",
    )


def _echoed_count(res: dict[str, Any], originals: list[str]) -> int:
    """How many bullets in a batch came back byte-identical to their input.

    Honest mode is allowed to rewrite every bullet, so an echoed bullet is a
    missed rewrite rather than a considered decision to leave it alone.
    """
    if not res or not res.get("success") or not res.get("data"):
        return 0
    from app.services.application_assistant.resume_response import parse_resume_bullets

    parsed = parse_resume_bullets(res["data"])
    if not isinstance(parsed, list) or len(parsed) != len(originals):
        return 0

    def plain(text: str) -> str:
        return re.sub(r"<[^>]+>", "", str(text or "")).strip().lower()

    return sum(1 for p, o in zip(parsed, originals) if plain(p) == plain(o))


def _bullet_batches(
    bullets: list[dict[str, str]], max_size: int = 4
) -> list[list[int]]:
    """Index groups to tailor together: consecutive, one employer, small.

    Seventeen bullets in one completion is past what a 4B model keeps ordered -
    measured, it returns the right count in the wrong slots. Batches never span
    two employers so the model cannot drift a Microsoft bullet into an Amazon
    slot, and stay small so position is easy to hold.
    """
    batches: list[list[int]] = []
    current: list[int] = []
    current_company: str | None = None
    for idx, bullet in enumerate(bullets):
        company = bullet.get("company", "")
        if current and (company != current_company or len(current) >= max_size):
            batches.append(current)
            current = []
        current.append(idx)
        current_company = company
    if current:
        batches.append(current)
    return batches


def _is_aligned(returned: list[str], originals: list[str]) -> bool:
    """True when each returned bullet is a rewrite of the one in its own slot.

    A rewrite should still resemble its source more than it resembles any of its
    neighbours. When that fails the model has reordered, and writing the batch
    through would put one role's work under another's heading - the exact defect
    this guard exists to catch.
    """
    if len(returned) != len(originals) or len(originals) < 2:
        return len(returned) == len(originals)

    def plain(text: str) -> str:
        return re.sub(r"<[^>]+>", "", str(text or "")).lower()

    for i, candidate in enumerate(returned):
        own = difflib.SequenceMatcher(None, plain(candidate), plain(originals[i])).ratio()
        for j, other in enumerate(originals):
            if j == i:
                continue
            rival = difflib.SequenceMatcher(None, plain(candidate), plain(other)).ratio()
            if rival > own + 0.05:
                logger.info(
                    "Tailored batch came back misaligned: slot %d resembles source %d "
                    "more than its own (%.2f vs %.2f); keeping the originals.",
                    i, j, rival, own,
                )
                return False
    return True


def _reject_fabrication(tailored: str, original: str) -> str:
    """Return `tailored`, or fall back to `original` when the rewrite is unsafe.

    These bullets go onto a resume submitted to a real employer, so a rewrite
    that invents scope is worse than no rewrite at all. Two checks, both
    observed failing live with a small local model:

    * placeholder wording copied straight out of the prompt ("Lead 4, ...");
    * **no figure may appear that was not in the original.** Turning "100K+ TPS"
      into "500K+ TPS", or adding a metric to a bullet that never carried one,
      is the fabrication that actually harms the candidate, and it is what this
      rejects.

    Dropping a figure is treated differently from inventing one, and the
    asymmetry is deliberate. The earlier version required every original number
    to survive and discarded the whole rewrite otherwise, which conflated two
    very different things: an understated bullet is still true, while an
    inflated one is a false claim on a real application. It also left the
    dangerous direction unguarded - a rewrite that kept every original figure
    and added an invented one passed the subset test cleanly. Measured against
    this corpus the old rule rejected 15 of 17 rewrites, so the resume went out
    essentially untailored while appearing to have been tailored.
    """
    if re.match(r"^\s*(?:<b>\s*)?Lead\s+\d+", tailored, re.I):
        return original

    original_figures = _figure_set(original)
    tailored_figures = _figure_set(tailored)

    invented = tailored_figures - original_figures
    if invented:
        logger.info(
            "Tailored bullet introduced a figure the original did not contain; keeping "
            "the original bullet. invented=%s",
            sorted(invented)[:4],
        )
        return original

    dropped = original_figures - tailored_figures
    if dropped:
        # Kept, not rejected: the bullet now says less than it could, which is a
        # weaker resume but not a false one.
        logger.info(
            "Tailored bullet dropped a figure from the original; keeping the rewrite. "
            "dropped=%s",
            sorted(dropped)[:4],
        )

    return tailored


async def generate_role_tailoring_diff(
    job: dict[str, Any],
    profile: dict[str, Any],
    master_resume: dict[str, Any] | None = None,
    mode: str = "honest",
    *,
    feedback_gaps: list[str] | None = None,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
    rescore: bool = True,
) -> dict[str, Any]:
    """Generate or retrieve role-tailored materials with full visual diff data across 3 modes:
    - 'off': no change, resume bullets remain identical to original.
    - 'honest': precision rewriting/reorganizing strictly aligned with job description and verified experience.
    - 'aggressive': same source-only composition and evidence checks as honest mode.
    
    Selects source-backed achievements locally across the complete profile and corpus.
    """
    valid_mode = mode if mode in ("off", "honest", "aggressive") else "honest"
    company = job.get("company") or "Target Company"
    title = job.get("title") or "Target Role"
    description = job.get("description") or job.get("snippet") or ""

    # Autopilot job rows carry only company/title/url/location — never the posting
    # text — so tailoring was running with an empty job description and could not
    # actually match anything to the role. The full description does exist, on the
    # discovered_job row this autopilot job was created from, so fetch it by jobId.
    if not description.strip():
        try:
            from app.db.store import session_scope, get_entity
            from app.services.application_assistant.persistence import ENTITY_DISCOVERED_JOB

            source_id = job.get("jobId") or job.get("id")
            if source_id:
                with session_scope() as _db:
                    src_job = get_entity(_db, ENTITY_DISCOVERED_JOB, source_id)
                if src_job:
                    description = (
                        src_job.get("description") or src_job.get("snippet") or ""
                    )
                    if description.strip():
                        logger.info(
                            "Loaded job description (%d chars) from discovered job %s for tailoring",
                            len(description), source_id,
                        )
        except Exception as e:
            logger.warning("Could not load job description for tailoring: %s", e)

    if not description.strip():
        logger.warning(
            "No job description available for %s — %s; tailoring can only use the title.",
            company, title,
        )

    from app.services.resume_intelligence.minimal_tailoring import tailor, mode_config
    from app.services.resume_intelligence.local_document import document_text

    if accomplishments is None:
        from app.db.store import session_scope, list_entities
        with session_scope() as db:
            accomplishments = list_entities(db, "accomplishment")
    config = mode_config(valid_mode, profile.get("resumeTailoringConfig"))
    result = tailor(accomplishments, description, title, config=config, mode=valid_mode)
    from app.services.resume_intelligence.evidence_match import compare_pdfs
    from app.services.resume_intelligence.baseline_document import approved_path, render_baseline
    document_comparison = compare_pdfs(approved_path().read_bytes(), render_baseline(result), description,
        use_semantic=config.use_semantic, bm25_k1=config.bm25_k1, bm25_b=config.bm25_b, rrf_k=config.rrf_k)
    originals = [b["original"] for b in result["resumeBullets"]]
    bullets = [b["optimizedBullet"] for b in result["resumeBullets"]]
    diffs = compute_bullet_diffs(originals, bullets)
    for diff, selected in zip(diffs, result["resumeBullets"]):
        diff.update({"source": selected["source"], "company": selected["company"],
                     "selectionReason": selected["selectionReason"], "decision": selected["decision"], "richText": selected["richText"]})
    off = valid_mode == "off"
    # Keep the existing eligibility score separate from heuristic evidence coverage.
    # Do not manufacture score improvement or relax the runner's submission bar.
    score = job_match_score(job)
    problems = [] if off else list(result["warnings"])
    return {
        "jobId": job.get("id"), "company": company, "title": title, "mode": valid_mode,
        "matchScore": score, "baseMatchScore": score, "baselineMatchScore": score,
        "documentMatch": document_comparison,
        "matchRescored": False, "matchReason": "Local source selection; eligibility score unchanged.",
        "requirementCoverage": result["requirementCoverage"], "scoreKind": result["scoreKind"],
        "missingSkills": [r["text"] for r in result["uncoveredRequirements"]],
        "keyMatchingSkills": result["skillsList"], "bulletDiffs": [] if off else diffs,
        "resumeDocument": result, "resumeText": document_text(result, profile),
        "quality": {"ok": off or result["exportReady"], "changed": sum(b["decision"] != "KEEP" for b in result["resumeBullets"]), "total": len(bullets), "problems": problems},
        "totalChanges": sum(b["decision"] != "KEEP" for b in result["resumeBullets"]), "selectedAchievements": len(bullets),
        "tailoringFailed": not off and not bool(bullets), "tailoringModel": "none (local evidence selection)",
        "tailoringError": "", "jobDescriptionChars": len(description),
        "tailoredCoverLetter": "", "screeningQAs": [],
        "salaryRange": job.get("salary") or job.get("salaryRange") or "Not provided",
        "visaStatus": authorization_summary(profile),
    }


def render_tailored_resume_pdf(diff_data: dict[str, Any], candidate_info: dict[str, Any]) -> bytes:
    """Render a flowing source-based resume, or return the exact original in off mode."""
    from pathlib import Path

    mode = diff_data.get("mode", "honest").lower()
    if mode != "off":
        from app.services.resume_intelligence.local_document import render
        document = diff_data.get("resumeDocument")
        if not document or diff_data.get("tailoringFailed") or not (diff_data.get("quality") or {}).get("ok"):
            raise ValueError("Resume is not ready to export; review the source evidence first.")
        if document.get("method") == "minimal-change-v1":
            from app.db.store import session_scope, list_entities
            from app.services.resume_intelligence.minimal_tailoring import validate
            with session_scope() as db:
                problems = validate(document, list_entities(db, "accomplishment"))
            if problems:
                raise ValueError(" ".join(problems))
        return render(document, candidate_info)


    from app.services.resume_intelligence.baseline_document import approved_path
    path = approved_path()
    if not path.is_file():
        raise FileNotFoundError("Approved baseline PDF is not configured.")
    return path.read_bytes()
