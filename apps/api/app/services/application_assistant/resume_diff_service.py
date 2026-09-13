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
    - 'aggressive': inflates phrasing, senior impact, and metrics to aggressively match JD requirements for maximum callback rates.
    
    Tailors BOTH Microsoft (7 bullets) and Amazon (10 bullets) maintaining clean formatting and bold lead action phrases.
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

    # Master bullets across both Microsoft (0..6) and Amazon (7..16)
    master_bullets = [b["fullText"] for b in CANONICAL_MASTER_BULLETS]

    tailored_bullets: list[str] = []
    tailoring_failed = False
    tailoring_model = ""
    tailoring_error = ""

    if valid_mode == "off":
        # Off: passthrough exact master bullets with zero alteration
        tailored_bullets = list(master_bullets)
    else:
        # Generate bullets via LLM: Mistral primary (via Ollama) with automatic fallback to Gemini Flash
        from app.services.application_assistant.llm_client import create_llm_client

        llm_settings = {
            "llm": {
                "enabled": True,
                "provider": "ollama",
                # Context the server actually serves; the prompt below is sized
                # against this rather than against the model card maximum.
                "contextWindow": DEFAULT_CONTEXT_WINDOW,
                # mistral-small3.2:24b needs ~16GB and this box has an 8GB
                # RTX 2070 Super Max-Q, so only ~5.8GB ever loaded and the rest
                # ran on CPU at ~2.6 tok/s - a 17-bullet completion never
                # finished, so every tailoring call fell back to the static
                # template and every "tailored" resume came out byte-identical.
                # mistral:7b-instruct fits entirely in VRAM and does the same
                # 17-bullet pass in ~9s measured.
                # Read per call, not at import, so the model can be switched
                # without restarting the process - which is what lets a
                # benchmark compare models, and lets the user pick a different
                # model for tailoring than for scoring.
                "model": os.environ.get("CAREEROS_TAILORING_MODEL")
                or DEFAULT_LOCAL_MODEL,
                "baseUrl": "http://localhost:11434/v1",
                                # Deliberately short. mistral-small3.2:24b runs mostly on CPU here
                # (~2.6 tok/s measured), so a 17-bullet completion never finishes no
                # matter how long we wait - raising this to 300s did not produce a
                # single success, it just made every job spend 300s failing before
                # handing off. create_llm_client retries the primary 0 times and falls
                # straight through to the cloud fallback, so failing fast is the point.
                # ~9s warm; the first call after an idle period also pays a
                # ~47s model load, so this covers a cold start with margin.
                "timeout": 120,
                "maxRetries": 1,
            }
        }
        client = create_llm_client(llm_settings)

        # The rendered PDF overlays each tailored bullet into a fixed-height
        # slot sized for the original bullet's line count (see
        # render_tailored_resume_pdf's ms_dot_positions/amz_dot_positions,
        # spaced ~19pt apart) — a tailored bullet noticeably longer than the
        # one it replaces wraps to an extra line and visually overlaps the
        # bullet below it. Without an explicit length target the model has no
        # way to know that constraint, so it regularly ran long — especially
        # in AGGRESSIVE mode, whose amplified phrasing tends to add length —
        # producing exactly that broken, overlapping layout. Giving each
        # bullet's own character count as its target keeps the tailored
        # version within the same visual footprint.
        def _plain_len(html_text: str) -> int:
            return len(re.sub(r"<[^>]+>", "", html_text))

        # The budget is written inline against each bullet rather than as a
        # separate numbered list further down the prompt. A 4B model asked to
        # cross-reference "bullet 11" in one list against "11. target ~240
        # characters" in another gets the pairing wrong often enough to matter,
        # and the failure is invisible: a bullet silently overruns its slot and
        # the rendered PDF overlaps. Putting the number beside the text it
        # governs removes the indexing step entirely.
        length_targets = "\n".join(
            f"{i+1}. target ~{_plain_len(b)} characters (max {_plain_len(b) + 15})"
            for i, b in enumerate(master_bullets)
        )
        numbered_bullets = "\n".join(
            f"[{i+1}] ({CANONICAL_MASTER_BULLETS[i]['company']}, "
            f"max {_plain_len(b) + 15} chars) {b}"
            for i, b in enumerate(master_bullets)
        )

        # What the posting asks for, named explicitly. Without this the model
        # has to infer the requirements from raw prose and then rewrite against
        # its own inference; naming them splits one hard task into two easy
        # ones. On a retry the gaps the scorer actually found are appended,
        # which is the only thing that makes a second attempt different from a
        # re-roll of the first.
        try:
            from app.services.story_index import flat_tags

            detected = sorted(flat_tags(f"{title}\n{description}"))
        except Exception:  # noqa: BLE001 - never block tailoring on the index
            detected = []
        requirement_line = (
            "Requirements detected in this posting: " + ", ".join(detected) + "\n"
            if detected else ""
        )
        gap_line = ""
        if feedback_gaps:
            gap_line = (
                "\nPREVIOUS ATTEMPT FELL SHORT. A scorer compared your last rewrite "
                "against this posting and reported these requirements as still not "
                "evidenced:\n"
                + "\n".join(f"  - {g}" for g in feedback_gaps)
                + "\nWhere the candidate's real work below genuinely demonstrates one of "
                "these, bring it to the front of the bullet it belongs to and use the "
                "posting's own words for it. Where it does not, leave it alone: an "
                "unevidenced claim is stripped by the scorer and costs points rather "
                "than gaining them.\n"
            )

        # The job description is the only elastic part of this prompt: the 17
        # master bullets, the instructions and the per-bullet length targets are
        # all fixed, and the answer needs room for 17 rewritten bullets. Size the
        # JD against whatever is left instead of a flat 6000 characters, so the
        # request cannot overflow the context and come back truncated (which is
        # what silently produced untailored resumes before).
        fixed_prompt_tokens = estimate_tokens(
            chr(10).join(master_bullets) + length_targets
        ) + INSTRUCTION_TOKEN_ALLOWANCE
        expected_output_tokens = estimate_tokens(chr(10).join(master_bullets)) + OUTPUT_TOKEN_HEADROOM
        jd_token_budget = (
            DEFAULT_CONTEXT_WINDOW - fixed_prompt_tokens - expected_output_tokens - CONTEXT_SAFETY_MARGIN
        )
        elastic_chars = max(800, jd_token_budget * 4)

        # Retrieve only the stories this posting actually asks about. The master
        # bullets above are the 1-to-1 skeleton the answer must preserve; the
        # evidence below is the detail behind them, and sending the whole corpus
        # instead would not fit and would bury the relevant part.
        evidence_budget = int(elastic_chars * EVIDENCE_BUDGET_SHARE)
        if elastic_chars - evidence_budget < MIN_JD_CHARS:
            evidence_budget = max(0, elastic_chars - MIN_JD_CHARS)
        evidence_brief = ""
        evidence_meta: dict[str, Any] = {}
        if evidence_budget > 0:
            try:
                from app.services.story_index import select_evidence_for_job

                evidence_brief, evidence_meta = select_evidence_for_job(
                    description,
                    title=f"{title} {company}",
                    limit=EVIDENCE_STORY_LIMIT,
                    char_budget=evidence_budget,
                )
            except Exception as exc:  # noqa: BLE001 - retrieval must never block tailoring
                logger.warning("Story retrieval failed, tailoring without evidence: %s", exc)
        selected = evidence_meta.get("stories") or []
        if selected:
            coverage = evidence_meta.get("coverage") or {}
            logger.info(
                "Retrieved %d stories for %s — %s (%.0f%% of requirements covered; "
                "uncovered: %s): %s",
                len(selected), company, title,
                100 * float(coverage.get("weightedCoverage") or 0),
                ", ".join(coverage.get("uncovered") or []) or "none",
                ", ".join(f"{e['id']}->{','.join(e['covers'])}" for e in selected),
            )

        jd_char_budget = max(800, elastic_chars - len(evidence_brief))
        full_jd = description.strip()
        jd_text = full_jd[:jd_char_budget] or "(no job description available)"
        if len(full_jd) > jd_char_budget:
            logger.info(
                "Tailoring prompt budget: JD trimmed %d -> %d chars "
                "(fixed ~%d tok, output ~%d tok, context %d tok)",
                len(full_jd), jd_char_budget, fixed_prompt_tokens,
                expected_output_tokens, DEFAULT_CONTEXT_WINDOW,
            )

        # Prompt order is deliberate: task, target, source material, rules,
        # output contract. The rules sit last because a small model weights the
        # end of a long prompt most heavily, and the rules are what it actually
        # breaks - length overruns and dropped bullets - not the job itself.
        mode_rule = (
            "MODE: HONEST. Rewrite every bullet. Change only how the work is told, "
            "never what it was. For each bullet, ask what this posting wants and "
            "whether the candidate genuinely did that. If yes, lead with it and use "
            "the posting's own vocabulary for it. Surface a true detail that is "
            "currently buried, drop filler this role does not care about, and reorder "
            "within the bullet. Even where the overlap is small, lead with whatever "
            "part of the bullet is closest to this posting and tighten the rest. "
            "Returning a bullet word-for-word unchanged is a failure unless its fit "
            "genuinely cannot be improved."
            if valid_mode == "honest" else
            "MODE: AGGRESSIVE. Do everything HONEST does, then push the framing to the "
            "strongest defensible reading of the same facts: stronger ownership verbs, "
            "the senior end of what the work actually was, scale and business impact "
            "forward, and the posting's language wherever the candidate's real work is "
            "adjacent to it. Amplify the framing, never the facts - same employers, "
            "same projects, same numbers."
        )

        prompt = (
            "You rewrite a candidate's existing resume bullets to fit one specific job "
            "posting. You never invent experience.\n\n"
            f"TARGET ROLE: {title} at {company}\n"
            f"{requirement_line}{gap_line}"
            f"\n=== JOB DESCRIPTION ===\n{jd_text}\n=== END JOB DESCRIPTION ===\n\n"
            + (
                "=== EVIDENCE: the candidate's own account of this work ===\n"
                "Source material for rewording only. Use it to pick which true detail "
                "to surface and which words to use. Do not turn it into new bullets. "
                "Honour every 'MUST NOT claim' line. Anything marked PERSONAL PROJECT "
                "must never be worded as employer work.\n"
                f"{evidence_brief}\n=== END EVIDENCE ===\n\n"
                if evidence_brief else ""
            )
            + "=== THE 17 BULLETS TO REWRITE ===\n"
            "Each line is [number] (employer, character budget) then the current "
            "bullet. Bullets 1-7 are Microsoft, 8-17 are Amazon.\n"
            + numbered_bullets
            + "\n=== END BULLETS ===\n\n"
            + mode_rule
            + "\n\nHARD RULES - breaking any of these makes the answer unusable:\n"
            "1. NEVER change where or on what the work happened. The employer, product, "
            "industry and domain of each bullet stay exactly as given. Logistics work "
            "stays logistics work when applying to a healthcare role. Do not move a "
            "technology into a bullet it was not already in.\n"
            "2. Reuse every number exactly as written. Never round, scale or add one.\n"
            f"3. Return exactly {len(master_bullets)} bullets, in the same order as the "
            "input, matching 1-to-1. Bullet 5 out must be a rewrite of bullet 5 in.\n"
            "4. Every bullet starts with a bold lead phrase: <b>Lead Action Phrase</b> "
            "then the rest of the sentence. Take that phrase from the candidate's own "
            "work - never copy wording from these instructions.\n"
            "5. Stay within each bullet's character budget, shown beside it above. The "
            "PDF overlays each bullet into a fixed-height slot, so going over makes it "
            "overlap the bullet below. Count visible characters only, not the <b> tags. "
            "Cut it down before answering, not after.\n\n"
            "Return ONLY a JSON array of exactly "
            f"{len(master_bullets)} strings. No prose, no keys, no markdown fence.\n"
        )

        try:
            batches = _bullet_batches(CANONICAL_MASTER_BULLETS, BULLET_BATCH_SIZE)
            # Start from the candidate's own bullets: any batch the model
            # fumbles simply keeps its originals, so a partial failure costs
            # that batch's tailoring and nothing else.
            working = list(master_bullets)
            succeeded = 0
            usage_in = usage_out = 0

            for batch in batches:
                batch_prompt = (
                    prompt
                    + "\n=== REWRITE ONLY THESE BULLETS ===\n"
                    + "\n".join(
                        f"[{position + 1}] (max {_plain_len(master_bullets[idx]) + 15} chars) "
                        f"{master_bullets[idx]}"
                        for position, idx in enumerate(batch)
                    )
                    + f"\n\nReturn a JSON array of exactly {len(batch)} strings, one per "
                    "bullet above, in the same order. Item 1 must be a rewrite of bullet "
                    "[1] above, item 2 of bullet [2], and so on. Do not reorder them and "
                    "do not return any other bullet. Each string must be a genuine "
                    "rewrite - do not copy the input text back.\n"
                )
                res = await _complete_batch(client, batch_prompt, expected=len(batch))

                # Any echoed bullet is a missed rewrite, so ask again naming how
                # many came back untouched. Only one retry: a second model that
                # still echoes is not going to be argued into rewriting.
                echoed = _echoed_count(res, [master_bullets[i] for i in batch])
                if echoed:
                    logger.info(
                        "Tailoring batch %s returned %d of %d bullets unchanged; "
                        "retrying once with an explicit rewrite instruction.",
                        batch, echoed, len(batch),
                    )
                    res = await _complete_batch(
                        client,
                        batch_prompt
                        + f"\nYour previous answer repeated {echoed} of {len(batch)} "
                        "bullets word for word. That is not a rewrite. Every bullet "
                        "must come back genuinely reworded: change the opening phrase, "
                        "reorder the clauses, and use this posting's vocabulary. Keep "
                        "every fact, employer and number exactly as given, and end each "
                        "bullet with a full stop.\n",
                    ) or res
                if not res.get("success") or not res.get("data"):
                    tailoring_error = str(res.get("error") or "unknown LLM failure")[:300]
                    logger.info(
                        "Tailoring batch %s failed (%s); keeping those bullets as written.",
                        batch, tailoring_error[:120],
                    )
                    continue

                from app.services.application_assistant.resume_response import (
                    parse_resume_bullets,
                )

                parsed = parse_resume_bullets(res["data"])
                if not isinstance(parsed, list) or not parsed:
                    continue
                originals = [master_bullets[i] for i in batch]
                candidates = [str(p) for p in parsed][: len(batch)]
                if len(candidates) != len(batch):
                    logger.info(
                        "Tailoring batch %s returned %d of %d bullets; keeping originals.",
                        batch, len(candidates), len(batch),
                    )
                    continue
                if not _is_aligned(candidates, originals):
                    continue

                for position, idx in enumerate(batch):
                    working[idx] = finish_sentence(
                        clamp_bullet_length(
                            ensure_bold_lead(
                                _reject_fabrication(
                                    candidates[position], master_bullets[idx]
                                ),
                                CANONICAL_MASTER_BULLETS[idx]["boldPrefix"],
                            ),
                            _plain_len(master_bullets[idx]) + 20,
                            master_bullets[idx],
                        )
                    )
                succeeded += 1
                usage = res.get("usage") or {}
                usage_in += int(usage.get("promptTokens") or 0)
                usage_out += int(usage.get("completionTokens") or 0)
                tailoring_model = res.get("usedFallbackModel") or client.model

            if succeeded:
                tailored_bullets = working
                logger.info(
                    "Resume tailored: %d/%d batches applied, model=%s tokens_in=%s "
                    "tokens_out=%s",
                    succeeded, len(batches), tailoring_model, usage_in, usage_out,
                )
            else:
                logger.warning(
                    "Every tailoring batch failed or came back misaligned for %s - %s.",
                    company, title,
                )
        except Exception as e:
            tailoring_error = str(e)[:300]
            logger.warning(f"LLM resume tailoring failed, using template fallback: {e}")

        if not tailored_bullets:
            # The static bullets below are generic and identical for every posting,
            # so falling back means this resume is NOT tailored to the job. That used
            # to happen on every single application (the LLM call always timed out)
            # while still reporting a 95-99% match score, so nothing ever surfaced it.
            # Flag it on the diff so the caller can log and act on it.
            tailoring_failed = True
            logger.warning(
                "Resume tailoring FELL BACK to the static template for %s - %s "
                "(mode=%s): the generated resume is NOT tailored to this job description.",
                company, title, valid_mode,
            )

        if not tailored_bullets:
            # High quality template fallbacks tailored specifically to title & company across all 17 bullets
            title_lower = title.lower()
            if valid_mode == "honest":
                if "ai" in title_lower or "ml" in title_lower or "agent" in title_lower:
                    tailored_bullets = [
                        # Microsoft (7)
                        f"<b>Built the historical risk foundation for AI Agent Risk Detection</b>, reconstructing 90 days of multi-tenant activity to enable day-one evaluation for 237K+ autonomous agents across 13K organizations, directly applicable to {company}'s AI roadmap.",
                        f"<b>Drove cross-service architecture across Purview IRM, Entra, and DLP</b> for Microsoft's AI-agent Adaptive Protection pipeline, owning end-to-end launch through Conditional Access enforcement shipped with Microsoft 365 E7.",
                        f"<b>Led the redesign of AI-agent ingestion for independent scale and fault isolation</b>, separating agent and human workloads across 28 deployments processing 135K+ security signals/day.",
                        f"<b>Led AI Risk Detection's sovereign-cloud architecture and rollout across GCC, GCCH and DoD</b>, engineering deployment infrastructure across 53 resource groups and establishing Gov-cloud Kusto telemetry.",
                        f"<b>Connected cross-product investigations across Microsoft's security ecosystem</b>, linking risk across Entra, Defender, Sentinel, and Graph, elevating customer investigation engagement 16%.",
                        f"<b>Designed an AI-assisted testing workflow</b> using agent skills and Playwright to provision test tenants, configure Copilot Studio agents with tools/policies, and validate end-to-end behavior.",
                        f"<b>Designed an AI-assisted debugging workflow spanning three repositories</b>, combining historical incident analysis with Playwright to reproduce issues, implement fixes, and create automated pull requests.",
                        # Amazon (10)
                        f"<b>Built a 0→1 developer platform for 60+ microservices</b>, creating a CDK-based workflow that standardized infrastructure, authentication, observability, and CI/CD; cut service setup from 2 weeks to under 1 hour.",
                        f"<b>Led a monolith-to-microservices transformation at 100K+ TPS</b>, building 15+ services with shared REST/gRPC orchestration supporting 10M+ daily transactions while maintaining behavioral parity.",
                        f"<b>Designed and owned the service powering ML-predicted delivery ranges</b>, integrating quantile-regression models and fulfillment optimization systems to deliver $28M in annualized business impact.",
                        f"<b>Replaced static delivery-risk rules with ML-driven decisioning</b>, deploying XGBoost on SageMaker to identify at-risk orders and trigger recovery workflows, contributing to a 7% increase in sales.",
                        f"<b>Launched inventory decisioning systems processing 200K+ events/day</b>, launching Just-In-Stock and Restock Alerting with 30-day order replay; increased restocked-item sales 13%.",
                        f"<b>Architected built a RAG-based product recommendation system for out-of-stock items</b>, surfacing relevant alternatives grounded in real-time inventory and delivery constraints, increasing sales 23%.",
                        f"<b>Led design and cross-functional adoption of an LLM-powered localization platform</b>, using Bedrock with vocabulary-constrained generation and deterministic validation across 37 email templates and 28 locales.",
                        f"<b>Owned the annual operational improvement roadmap across 60+ services</b>, driving execution across 15+ engineers and reducing Sev2 incidents 40%; led Prime Day and Black Friday readiness with zero major incidents.",
                        f"<b>Turned synchronized delivery for large Amazon Business orders into a first-class fulfillment capability</b>, driving changes across planning and fulfillment systems, eliminating 100–300 engineering hours/year.",
                        f"<b>Standardized observability and container infrastructure across 60+ services</b>, introducing shared logging and Docker libraries that cut CloudWatch spend $250K+/month and container size 83%.",
                    ]
                else:
                    tailored_bullets = [
                        # Microsoft (7)
                        f"<b>Built the historical risk foundation for AI Agent Risk Detection</b>, reconstructing 90 days of activity across 40+ environments to eliminate blind spots and enable day-one evaluation for 237K+ agents across 13K organizations.",
                        f"<b>Drove architecture across Purview IRM, Entra, and DLP</b> for Microsoft’s AI-agent Adaptive Protection pipeline, owning design and launch from risk scoring through Conditional Access enforcement with Microsoft 365 E7.",
                        f"<b>Led the redesign of AI-agent ingestion for independent scale and fault isolation</b>, separating agent and human workloads across 28 deployments processing 135K+ security signals/day.",
                        f"<b>Led AI Risk Detection's sovereign-cloud architecture and rollout across GCC, GCCH and DoD</b>, engineering deployment across 53 resource groups and 51 deployments with Gov-cloud Kusto monitoring.",
                        f"<b>Connected investigations across Microsoft's security ecosystem</b>, linking related risk across Entra, Defender, Sentinel, and Graph and increasing cross-product investigation adoption 16%.",
                        f"<b>Designed an AI-assisted testing workflow</b> using agent skills and Playwright to provision test tenants, configure Copilot Studio agents with policies, and validate end-to-end behavior.",
                        f"<b>Designed an AI-assisted debugging workflow spanning three repositories</b>, combining historical incident analysis with Playwright to reproduce issues, validate fixes, and create pull requests.",
                        # Amazon (10)
                        f"<b>Built a 0→1 developer platform for 60+ microservices</b>, creating a one-click CDK-based workflow that standardized infrastructure, observability, and CI/CD; saved 40–50 engineering weeks.",
                        f"<b>Led a monolith-to-microservices transformation at 100K+ TPS</b>, building 15+ services and establishing shared REST/gRPC orchestration supporting 10M+ daily transactions.",
                        f"<b>Designed and owned the service powering ML-predicted delivery ranges</b>, integrating quantile-regression models and fulfillment optimization systems to deliver $28M in annualized impact.",
                        f"<b>Replaced static delivery-risk rules with ML-driven decisioning</b>, using XGBoost on SageMaker to identify at-risk orders and trigger recovery notifications, boosting sales 7%.",
                        f"<b>Launched inventory decisioning systems processing 200K+ events/day</b>, deploying Just-In-Stock and Restock Alerting with 30-day order replay; increased early deliveries 16%.",
                        f"<b>Architected built a RAG-based product recommendation system for out-of-stock items</b>, surfacing alternatives grounded in real-time inventory and delivery constraints; increased sales 23%.",
                        f"<b>Led design and cross-functional adoption of an LLM-powered localization platform</b>, using Bedrock with vocabulary-constrained generation and deterministic validation across 28 locales.",
                        f"<b>Owned the annual operational improvement roadmap across 60+ services</b>, driving execution across 15+ engineers and reducing Sev2 incidents 40% in two months.",
                        f"<b>Turned synchronized delivery for large Amazon Business orders into a first-class fulfillment capability</b>, driving changes across planning and fulfillment systems, improving GCCP 11%.",
                        f"<b>Standardized observability and container infrastructure across 60+ services</b>, introducing shared logging and Docker libraries that cut CloudWatch spend $250K+/month and container size 83%.",
                    ]
            else:
                # Aggressive
                tailored_bullets = [
                    # Microsoft (7)
                    f"<b>Spearheaded Microsoft's flagship enterprise AI Agent Risk Detection platform</b>, orchestrating 90-day activity reconstruction across 40+ global environments to unlock instant day-one risk governance for 237,000+ AI agents across 13,000 enterprise customers.",
                    f"<b>Directed principal-level architecture across Purview IRM, Entra, and DLP</b> for Microsoft's flagship AI Adaptive Protection pipeline; authored the end-to-end technical spec and shipped core conditional access enforcement powering Microsoft 365 E7.",
                    f"<b>Pioneered hyper-scale distributed ingestion infrastructure with zero-latency fault isolation</b>, partitioning agent and human traffic across 28 worldwide deployments processing 150K+ critical security signals/day at 99.999% SLA.",
                    f"<b>Championed sovereign-cloud infrastructure expansion across US GCC, GCCH, and DoD high-security enclaves</b>, orchestrating 53 Azure resource groups and 51 deployments with automated disaster recovery and real-time Kusto telemetry.",
                    f"<b>Orchestrated unified investigation graphs across Entra, Defender, Sentinel, and Graph</b>, delivering unified threat intelligence that boosted customer security operation engagement by 28%.",
                    f"<b>Architected autonomous AI-agent synthetic validation and end-to-end test harnesses using Playwright</b>, simulating advanced attack vectors and policy violations across dynamic enterprise environments.",
                    f"<b>Pioneered closed-loop AI debugging and self-healing pipelines across 3 major codebases</b>, integrating telemetry pattern recognition with Playwright to automatically reproduce issues, generate code fixes, and submit PRs.",
                    # Amazon (10)
                    f"<b>Architected enterprise 0→1 developer platform for 60+ Tier-1 microservices</b>, establishing standardized CDK-based infrastructure, zero-trust authentication, and CI/CD pipelines that reduced onboarding from 2 weeks to under 1 hour, saving 50+ engineering weeks.",
                    f"<b>Engineered monolith-to-microservices transformation at 100K+ peak TPS</b>, launching 15+ mission-critical microservices with high-performance gRPC orchestration handling 10M+ daily transactions at sub-10ms latency.",
                    f"<b>Directed ML-predicted delivery promise service powering global fulfillment</b>, integrating high-throughput quantile-regression models across planning and fulfillment systems delivering $28M+ in annual bottom-line impact.",
                    f"<b>Transformed fulfillment risk operations with real-time ML decisioning on SageMaker</b>, deploying automated XGBoost risk scoring that prevented thousands of order cancellations and generated a 7% sales lift.",
                    f"<b>Architected real-time inventory intelligence platforms processing 200K+ events/day</b>, engineering Just-In-Stock and Restock alerting with distributed replay that increased restocked sales by 13% and expedited delivery 16%.",
                    f"<b>Pioneered production RAG-based product recommendation architecture for out-of-stock items</b>, combining embedding vector search with deterministic inventory constraints to deliver a 23% increase in conversion sales.",
                    f"<b>Spearheaded generative AI localization platform using AWS Bedrock</b>, implementing constrained vocabulary decoding and deterministic guardrails across 37 global notification templates across 28 locales with zero compliance errors.",
                    f"<b>Spearheaded operational excellence and resilience roadmap across 60+ distributed services</b>, mentoring 15+ engineers, cutting Sev2 incidents 40% in 60 days, and maintaining 100% uptime through Prime Day and Black Friday.",
                    f"<b>Architected synchronized fulfillment capabilities for high-volume enterprise Amazon Business orders</b>, eliminating manual workflows, freeing 300+ engineering hours/year, and boosting GCCP efficiency by 11%.",
                    f"<b>Championed container modernization and distributed observability across 60+ microservices</b>, designing shared container standards and optimized telemetry that reduced CloudWatch spend $250K+/month and cut image size 83%.",
                ]

    bullet_diffs = compute_bullet_diffs(master_bullets, tailored_bullets)

    # Rewording a resume is not evidence of improved job fit. Never manufacture
    # points (or a passing default) merely because tailoring was selected.
    # The score the caller compares against the submit bar must describe the
    # document that will actually be sent. job_match_score(job) reads the stored
    # pre-tailoring score straight back, so it could never move however good the
    # rewrite was - which made a retry loop meaningless and made
    # matchScoreAtSubmission a record of a document nobody submitted.
    base_match_score = job_match_score(job)
    match_score = base_match_score
    baseline_score = base_match_score
    tailored_match: dict[str, Any] | None = None
    if rescore and valid_mode != "off" and tailored_bullets and not tailoring_failed:
        from app.services.application_assistant.tailored_match import score_tailored_resume

        scored_job = {**job, "description": description}
        tailored_match = await score_tailored_resume(
            scored_job,
            tailored_bullets,
            profile=profile,
            documents=documents,
            accomplishments=accomplishments,
        )
        if tailored_match:
            match_score = float(tailored_match.get("matchScore") or 0.0)
            # The control: the untailored resume, scored the same way in the
            # same run. Without it "did the resume improve" is a comparison
            # between two samples of a noisy scorer taken at different times.
            baseline_match = await score_tailored_resume(
                scored_job,
                master_bullets,
                profile=profile,
                documents=documents,
                accomplishments=accomplishments,
            )
            if baseline_match:
                baseline_score = float(baseline_match.get("matchScore") or 0.0)
            logger.info(
                "Re-scored for %s - %s: tailored %.1f%% vs untailored %.1f%% "
                "(stored queue score %.1f%%)",
                company, title, match_score, baseline_score, base_match_score,
            )
    work_auth = authorization_summary(profile)

    # Draft tailored cover letter
    candidate_name = f"{profile.get('firstName', 'Akshay')} {profile.get('lastName', 'Borse')}".strip()
    
    if valid_mode == "off":
        letter_tone_p1 = f"I am writing to express my interest in the {title} role at {company}."
        letter_tone_p2 = "My background spans software engineering, distributed systems, and modern web application development."
    elif valid_mode == "honest":
        letter_tone_p1 = f"I am writing to express my strong enthusiasm for the {title} role at {company}."
        letter_tone_p2 = f"With direct experience architecting distributed services and deploying modern AI systems at Microsoft and Amazon, my proven track record aligns closely with {company}'s immediate technical needs."
    else:
        letter_tone_p1 = f"I am writing to present my candidacy for the {title} opportunity at {company}."
        letter_tone_p2 = f"Having driven high-impact distributed architectures and high-velocity engineering transformations that scaled products to tens of millions of users across Microsoft and Amazon, I am uniquely equipped to elevate {company}'s technical roadmap and deliver outsized business impact from day one."

    from app.services.application_assistant.resume_quality import assess as _assess_quality

    if valid_mode == "off":
        from app.services.application_assistant.resume_quality import QualityReport
        quality_report = QualityReport(
            ok=True,
            changed=0,
            total=len(master_bullets),
            score_before=baseline_score,
            score_after=match_score,
        )
    else:
        quality_report = _assess_quality(
            master_bullets,
            tailored_bullets,
            score_before=baseline_score,
            score_after=match_score,
            min_changed=MIN_TAILORED_BULLETS,
            # Only ask for an improvement when a real re-score happened; otherwise
            # both numbers are the same stored value and the check is meaningless.
            require_improvement=bool(tailored_match),
        )
    if not quality_report.ok:
        logger.info(
            "Tailored resume for %s - %s is not submittable: %s",
            company, title, quality_report.summary(),
        )

    cover_letter = (
        f"Dear Hiring Team at {company},\n\n"
        f"{letter_tone_p1} {letter_tone_p2}\n\n"
        f"At {company}, I am particularly excited about your focus on technical excellence and ambitious engineering standards. "
        f"I welcome the opportunity to discuss how my skill set can accelerate your key goals.\n\n"
        f"Sincerely,\n{candidate_name}"
    )

    # Screening answers preview
    screening_qas = [
        {
            "question": f"Why are you interested in joining {company} as a {title}?",
            "suggestedAnswer": (
                f"I am deeply inspired by {company}'s engineering culture and mission. My background in building resilient, high-performance distributed systems directly enables me to contribute immediately to {title} initiatives."
                if valid_mode != "aggressive" else
                f"I have consistently driven market-leading technical innovations in {title} domains. Joining {company} represents the ideal opportunity to apply high-scale distributed architectural leadership and accelerate mission-critical engineering initiatives."
            ),
            "confidence": 0.95 if valid_mode == "off" else (0.98 if valid_mode == "honest" else 0.99),
        },
        {
            "question": "What is your authorization status and notice period?",
            "suggestedAnswer": work_auth + ". Confirm your notice period before submitting.",
            "confidence": 0.0,
        },
    ]

    return {
        "jobId": job.get("id"),
        "company": company,
        "title": title,
        "mode": valid_mode,
        "matchScore": match_score,
        # Whether the document is fit to send, judged separately from how well it
        # scores. The caller must check both.
        "quality": quality_report.to_dict(),
        # Kept separate so a caller can always tell the tailored document's score
        # from the stored one, and see whether re-scoring ran at all.
        "baseMatchScore": base_match_score,
        # The untailored resume scored in this same run. This, not the stored
        # queue score, is what the tailored number should be compared against.
        "baselineMatchScore": baseline_score,
        "matchRescored": bool(tailored_match),
        "matchReason": (tailored_match or {}).get("matchReason", ""),
        "missingSkills": (tailored_match or {}).get("missingSkills", []),
        "keyMatchingSkills": (tailored_match or {}).get("keyMatchingSkills", []),
        "salaryRange": job.get("salary") or job.get("salaryRange") or "Not provided",
        "visaStatus": work_auth,
        "bulletDiffs": bullet_diffs,
        "tailoredCoverLetter": cover_letter,
        "screeningQAs": screening_qas,
        "totalChanges": sum(1 for b in bullet_diffs if b["isModified"]),
        # True when the LLM rewrite failed and the generic static template was used,
        # i.e. this resume is NOT actually tailored to this posting.
        "tailoringFailed": tailoring_failed,
        # Which model actually produced the bullets, and why it did not when
        # it did not — callers must be able to tell a real tailored resume
        # from the generic static template without re-deriving it.
        "tailoringModel": tailoring_model,
        "tailoringError": tailoring_error,
        "jobDescriptionChars": len(description or ""),
    }


def render_tailored_resume_pdf(diff_data: dict[str, Any], candidate_info: dict[str, Any]) -> bytes:
    """Render the tailored resume PDF using the candidate's authentic original resume PDF as base.
    
    Modes:
    - 'off': Returns the exact, byte-for-byte authentic original resume PDF with zero modifications.
    - 'honest' / 'aggressive': Preserves 100% of the candidate's authentic resume layout, styling,
      hyperlinks, Liquiron, Persistent Systems, Education, and Skills.
      Applies pixel-perfect, completely watermark-free overlays to BOTH Microsoft (7 bullets)
      and Amazon (10 bullets) sections, preserving clean typography and bold lead action phrases.
    """
    import io
    from pathlib import Path
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors

    mode = diff_data.get("mode", "honest").lower()

    # Locate the authentic original resume PDF
    possible_paths = [
        Path(__file__).resolve().parents[3] / "data" / "Akshay_Borse_Resume_Original.pdf",
        Path("apps/api/data/Akshay_Borse_Resume_Original.pdf"),
        Path("d:/3 - Resources/Docs/Interview/Resume/Akshay_Borse_Resume.pdf"),
        Path("D:/3 - Resources/Docs/Interview/Resume/Akshay_Borse_Resume.pdf"),
    ]
    orig_path = None
    for p in possible_paths:
        if p.exists():
            orig_path = p
            break

    if not orig_path:
        raise FileNotFoundError("Original resume PDF not found at expected paths.")

    # In 'off' mode: return exact original PDF bytes directly
    if mode == "off":
        return orig_path.read_bytes()

    # In 'honest' or 'aggressive' mode: overlay tailored bullets onto original PDF
    from app.services.application_assistant.resume_pdf_text import remove_replaced_bullets, fit_bullet_paragraph

    reader = PdfReader(io.BytesIO(remove_replaced_bullets(orig_path.read_bytes())))
    page = reader.pages[0]

    # Create overlay canvas
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)

    # 1. Mask original bullets with exact white bounding boxes
    # Microsoft bullets: x=48 to 580, y=550 to 684 (protects company title at y=686.7 & divider at y=544.8)
    can.setFillColor(colors.white)
    can.rect(48, 550, 532, 134, fill=1, stroke=0)

    # Amazon bullets: x=48 to 580, y=314 to 532 (protects company title at y=534.4 & divider at y=308.2)
    can.rect(48, 314, 532, 218, fill=1, stroke=0)

    # NOTE: NO watermark or badge is drawn. The output PDF remains 100% clean and authentic.

    # 2. Typography styling matching authentic resume (Helvetica 8.04pt, 9.24 leading, black)
    bullet_style = ParagraphStyle(
        "OverlayBullet",
        fontName="Helvetica",
        fontSize=8.04,
        leading=9.24,
        textColor=colors.HexColor("#000000"),
    )

    all_bullets = [
        b.get("tailored") or b.get("original")
        for b in diff_data.get("bulletDiffs", [])
        if (b.get("tailored") or b.get("original"))
    ]
    if not all_bullets:
        all_bullets = [b["fullText"] for b in CANONICAL_MASTER_BULLETS]

    # Partition into Microsoft (first 7) and Amazon (remaining up to 10)
    ms_bullets = all_bullets[:7]
    amz_bullets = all_bullets[7:17] if len(all_bullets) > 7 else []

    # 3. Render Microsoft bullets
    ms_dot_positions = [677.02, 658.06, 639.1, 620.26, 601.3, 582.34, 563.38]
    for i, b_text in enumerate(ms_bullets):
        dot_y = ms_dot_positions[i] if i < len(ms_dot_positions) else 684.0 - (i * 19.0)
        can.setFillColor(colors.HexColor("#000000"))
        can.setFont("Helvetica", 8.04)
        can.drawString(54.0, dot_y, chr(8226))

        formatted_text = ensure_bold_lead(b_text, CANONICAL_MASTER_BULLETS[i]["boldPrefix"])
        slot_height = dot_y - ms_dot_positions[i + 1] if i + 1 < len(ms_dot_positions) else dot_y + 7 - 550
        p, h = fit_bullet_paragraph(formatted_text, bullet_style, slot_height)
        # Position top of paragraph 7.0pt above the bullet dot baseline
        top_y = dot_y + 7.0
        p.drawOn(can, 72.0, top_y - h)

    # 4. Render Amazon bullets
    amz_dot_positions = [524.71, 496.51, 477.67, 458.71, 439.75, 420.79, 401.83, 373.73, 354.77, 326.69]
    for j, b_text in enumerate(amz_bullets):
        dot_y = amz_dot_positions[j] if j < len(amz_dot_positions) else 525.0 - (j * 20.0)
        can.setFillColor(colors.HexColor("#000000"))
        can.setFont("Helvetica", 8.04)
        can.drawString(54.0, dot_y, chr(8226))

        master_idx = 7 + j
        fallback_lead = CANONICAL_MASTER_BULLETS[master_idx]["boldPrefix"] if master_idx < len(CANONICAL_MASTER_BULLETS) else ""
        formatted_text = ensure_bold_lead(b_text, fallback_lead)
        slot_height = dot_y - amz_dot_positions[j + 1] if j + 1 < len(amz_dot_positions) else dot_y + 7 - 314
        p, h = fit_bullet_paragraph(formatted_text, bullet_style, slot_height)
        # Position top of paragraph 7.0pt above the bullet dot baseline
        top_y = dot_y + 7.0
        p.drawOn(can, 72.0, top_y - h)

    can.save()
    packet.seek(0)

    # Merge overlay with original PDF page
    overlay_pdf = PdfReader(packet)
    page.merge_page(overlay_pdf.pages[0])

    writer = PdfWriter()
    writer.add_page(page)

    out_buffer = io.BytesIO()
    writer.write(out_buffer)
    out_buffer.seek(0)
    return out_buffer.getvalue()
