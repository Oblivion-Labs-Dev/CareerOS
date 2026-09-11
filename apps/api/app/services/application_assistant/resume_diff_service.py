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


def clamp_bullet_length(text: str, max_len: int) -> str:
    """Hard safety net behind the tailoring prompt's length guidance: even a
    well-instructed LLM occasionally overshoots. Bullets that run long wrap
    to an extra line in the fixed-height overlay slot and visually collide
    with the bullet below (see render_tailored_resume_pdf) — truncating at a
    word boundary keeps the layout intact even when the prompt is ignored.
    """
    plain = re.sub(r"<[^>]+>", "", text)
    if len(plain) <= max_len:
        return text

    match = re.match(r"^\s*<b>(.*?)</b>\s*(.*)$", text, re.DOTALL)
    if not match:
        truncated = plain[:max_len].rsplit(" ", 1)[0].rstrip(",.;: ")
        return truncated + "…"

    lead, rest = match.group(1), match.group(2).lstrip()
    sep = "" if rest[:1] in (",", ".", ";", ":") else " "
    budget = max_len - len(lead) - len(sep)
    if budget <= 10 or not rest:
        return f"<b>{lead}</b>"
    truncated_rest = rest[:budget].rsplit(" ", 1)[0].rstrip(",.;: ")
    return f"<b>{lead}</b>{sep}{truncated_rest}…"


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


def _reject_fabrication(tailored: str, original: str) -> str:
    """Return `tailored`, or fall back to `original` when the rewrite is unsafe.

    These bullets go onto a resume submitted to a real employer, so a rewrite that
    invents scope is worse than no rewrite at all. Two checks, both observed
    failing live with a 7B model:

    * placeholder wording copied straight out of the prompt ("Lead 4, ...");
    * every figure in the original must survive. Dropping or changing a number
      is how "100K+ TPS at Amazon" quietly became a different claim, and it is a
      cheap, reliable signal that the model rewrote substance rather than
      phrasing.
    """
    plain_tailored = re.sub(r"<[^>]+>", "", tailored)

    if re.match(r"^\s*(?:<b>\s*)?Lead\s+\d+", tailored, re.I):
        return original

    original_numbers = set(re.findall(r"\d[\d,.]*\+?%?", re.sub(r"<[^>]+>", "", original)))
    tailored_numbers = set(re.findall(r"\d[\d,.]*\+?%?", plain_tailored))
    if original_numbers and not original_numbers.issubset(tailored_numbers):
        logger.info(
            "Tailored bullet dropped or altered a figure from the original; keeping the "
            "original bullet. missing=%s",
            sorted(original_numbers - tailored_numbers)[:4],
        )
        return original

    return tailored


async def generate_role_tailoring_diff(
    job: dict[str, Any],
    profile: dict[str, Any],
    master_resume: dict[str, Any] | None = None,
    mode: str = "honest",
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
                "model": DEFAULT_LOCAL_MODEL,
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

        length_targets = "\n".join(
            f"{i+1}. target ~{_plain_len(b)} characters (max {_plain_len(b) + 15})"
            for i, b in enumerate(master_bullets)
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

        prompt = (
            f"You are an expert resume tailoring assistant.\n"
            f"Candidate authentic experience bullets across Microsoft (bullets 1-7) and Amazon (bullets 8-17):\n"
            + "\n".join(f"{i+1}. {b}" for i, b in enumerate(master_bullets))
            + f"\n\nTarget Role: {title} at {company}\n"
            f"=== JOB DESCRIPTION (tailor against THIS) ===\n{jd_text}\n=== END JOB DESCRIPTION ===\n\n"
            + (
                "=== RETRIEVED EVIDENCE ===\n"
                "These are the candidate's own detailed accounts of the work behind the bullets "
                "above, selected because this posting asks about them. Use them to decide which "
                "true detail to surface in a bullet and which vocabulary to use. They are source "
                "material for rewording, not new bullets: do not add an eighteenth bullet, do not "
                "move a project into a bullet it does not belong to, and honour every "
                "'MUST NOT claim' line. Where an evidence block is marked PERSONAL PROJECT, "
                "anything drawn from it must never be worded as employer or professional work.\n"
                f"{evidence_brief}\n=== END RETRIEVED EVIDENCE ===\n\n"
                if evidence_brief else ""
            )
            + f"Tailoring Mode: {valid_mode.upper()}\n"
            f"Instructions:\n"
            + (
                "- Mode HONEST: start from the candidate's real bullets above and change only how they are told. "
                "Read the job description, identify the responsibilities, technologies and competencies it asks for, "
                "and where the candidate has genuinely done that work, reorganize and rephrase the bullet to lead with "
                "it and to use the job description's own vocabulary. Re-order emphasis inside a bullet, surface a "
                "technology that is already true but buried, and drop filler this role does not care about. Invent "
                "nothing: no new employers, technologies, scope, seniority or metrics, and never change a number. If a "
                "bullet is irrelevant to this role, leave it essentially as-is.\n"
                if valid_mode == "honest" else
                "- Mode AGGRESSIVE: do everything HONEST does, then inflate somewhat so the resume matches more of "
                "the job description. Use stronger leadership verbs, frame the candidate at the senior/owner end of "
                "what is plausible, emphasize scale and business impact, and lean into the job description's language "
                "wherever the candidate's real work is adjacent to what is asked for. Stay anchored to the same "
                "underlying projects and employers, and keep every hard number exactly as given - amplify the framing, "
                "not the facts.\n"
            )
            + "- ABSOLUTE RULE, both modes: never change WHERE or ON WHAT the work happened. Keep the employer, product, industry and domain of each bullet exactly as given. If a bullet describes e-commerce or logistics work, it stays e-commerce or logistics work even when applying to a healthcare or finance role - you may change the emphasis and wording, never the facts. Do not move a technology into a bullet it was not already in, and reuse every number exactly.\n"
            + "- Each bullet MUST begin with a bold lead action phrase formatted as <b>Lead Action Phrase</b>, followed by the description.\n"
            + f"- Return exactly {len(master_bullets)} bullets corresponding 1-to-1 in order with the original bullets (7 Microsoft, 10 Amazon).\n"
            + "- CRITICAL LENGTH CONSTRAINT: each bullet is overlaid into a fixed-size slot on the resume PDF sized for the original bullet's length — going over breaks the layout. Match each bullet's target length below (counting only visible text, not the <b> tags); never exceed the max. If your tailored version would run long, cut it down before answering, not after.\n"
            + length_targets
            + "\n- Never copy any placeholder wording from these instructions (for example \"Lead\" followed by a number) into a bullet; every bullet must begin with a real action phrase taken from the candidate's own work.\n"
            + "- Return ONLY a JSON array of strings, and nothing else.\n"
        )

        try:
            res = await client.complete(
                prompt,
                system="You are an expert ATS resume optimizer. Respond only with a JSON array of strings.",
                task="resume_tailoring",
            )
            if not res.get("success"):
                tailoring_error = str(res.get("error") or "unknown LLM failure")[:300]
            if res.get("success") and res.get("data"):
                from app.services.application_assistant.resume_response import parse_resume_bullets
                parsed = parse_resume_bullets(res["data"])
                # A 7B model is not reliably exact about list length. Requiring a
                # perfect 17 meant one short list threw away every good bullet in
                # the response and silently served the generic static template
                # instead. Take what it did return, position by position, and keep
                # the candidate's own bullet wherever it did not.
                if isinstance(parsed, list) and parsed:
                    if len(parsed) != len(master_bullets):
                        logger.info(
                            "Tailoring returned %d bullets, expected %d - keeping originals "
                            "for the remainder.",
                            len(parsed), len(master_bullets),
                        )
                        parsed = [
                            parsed[i] if i < len(parsed) else master_bullets[i]
                            for i in range(len(master_bullets))
                        ]
                    tailored_bullets = [
                        clamp_bullet_length(
                            ensure_bold_lead(
                                _reject_fabrication(str(p), master_bullets[idx]),
                                CANONICAL_MASTER_BULLETS[idx]["boldPrefix"],
                            ),
                            _plain_len(master_bullets[idx]) + 20,
                        )
                        for idx, p in enumerate(parsed)
                    ]
                    tailoring_model = res.get("usedFallbackModel") or client.model
                    usage = res.get("usage") or {}
                    logger.info(
                        "Resume tailored successfully: model=%s tokens_in=%s tokens_out=%s finish=%s",
                        tailoring_model,
                        usage.get("promptTokens"),
                        usage.get("completionTokens"),
                        res.get("finishReason"),
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
    match_score = job_match_score(job)
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
