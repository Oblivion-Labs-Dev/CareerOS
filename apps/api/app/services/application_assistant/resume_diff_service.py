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

    # Master bullets across both Microsoft (0..6) and Amazon (7..16)
    master_bullets = [b["fullText"] for b in CANONICAL_MASTER_BULLETS]

    tailored_bullets: list[str] = []

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
                "model": "mistral-small3.2:24b",
                "baseUrl": "http://localhost:11434/v1",
                "timeout": 45,
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

        prompt = (
            f"You are an expert resume tailoring assistant.\n"
            f"Candidate authentic experience bullets across Microsoft (bullets 1-7) and Amazon (bullets 8-17):\n"
            + "\n".join(f"{i+1}. {b}" for i, b in enumerate(master_bullets))
            + f"\n\nTarget Role: {title} at {company}\n"
            f"Job Context / Snippet: {description[:800]}\n"
            f"Tailoring Mode: {valid_mode.upper()}\n"
            f"Instructions:\n"
            + (
                "- Mode HONEST: Strictly preserve candidate's factual achievements, tech stack, and verified scope. Reorganize, rephrase, and highlight keywords and competencies matching the target job description while remaining 100% truthful across BOTH Microsoft and Amazon roles.\n"
                if valid_mode == "honest" else
                "- Mode AGGRESSIVE: Elevate executive presence, amplify leadership impact, emphasize scale and high-impact metrics (e.g., enterprise SLAs, latency, multi-agent workflows, cross-team influence) to aggressively align with the job description and maximize callback rates across BOTH Microsoft and Amazon roles.\n"
            )
            + "- Each bullet MUST begin with a bold lead action phrase formatted as <b>Lead Action Phrase</b>, followed by the description.\n"
            + f"- Return exactly {len(master_bullets)} bullets corresponding 1-to-1 in order with the original bullets (7 Microsoft, 10 Amazon).\n"
            + "- CRITICAL LENGTH CONSTRAINT: each bullet is overlaid into a fixed-size slot on the resume PDF sized for the original bullet's length — going over breaks the layout. Match each bullet's target length below (counting only visible text, not the <b> tags); never exceed the max. If your tailored version would run long, cut it down before answering, not after.\n"
            + length_targets
            + "\n- Return ONLY a JSON array of strings, e.g. [\"<b>Lead 1</b>, text...\", ...]\n"
        )

        try:
            res = await client.complete(prompt, system="You are an expert ATS resume optimizer. Respond only with a JSON array of strings.")
            if res.get("success") and res.get("data"):
                raw = res["data"].strip()
                if raw.startswith("```json"):
                    raw = raw[7:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                parsed = json.loads(raw.strip())
                if isinstance(parsed, list) and len(parsed) == len(master_bullets):
                    tailored_bullets = [
                        clamp_bullet_length(
                            ensure_bold_lead(str(p), CANONICAL_MASTER_BULLETS[idx]["boldPrefix"]),
                            _plain_len(master_bullets[idx]) + 20,
                        )
                        for idx, p in enumerate(parsed)
                    ]
                    logger.info(f"Resume tailored successfully with model: {res.get('usedFallbackModel') or client.model}")
        except Exception as e:
            logger.warning(f"LLM resume tailoring failed, using template fallback: {e}")

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

    # Calculate match score based on mode
    base_match = job.get("matchScore") or job.get("score") or 82
    if valid_mode == "off":
        match_score = base_match
    elif valid_mode == "honest":
        match_score = min(96, base_match + 10)
    else:  # aggressive
        match_score = min(99, max(95, base_match + 18))

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
            "suggestedAnswer": "Legally authorized to work in the United States without requiring sponsorship. Available to start immediately or within standard two weeks notice.",
            "confidence": 0.99,
        },
    ]

    return {
        "jobId": job.get("id"),
        "company": company,
        "title": title,
        "mode": valid_mode,
        "matchScore": match_score,
        "salaryRange": job.get("salary") or job.get("salaryRange") or "$185,000 - $245,000 USD",
        "visaStatus": "Authorized (US Citizen / Permanent Resident)",
        "bulletDiffs": bullet_diffs,
        "tailoredCoverLetter": cover_letter,
        "screeningQAs": screening_qas,
        "totalChanges": sum(1 for b in bullet_diffs if b["isModified"]),
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
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors

    mode = diff_data.get("mode", "honest").lower()

    # Locate the authentic original resume PDF
    possible_paths = [
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
    reader = PdfReader(str(orig_path))
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
        p = Paragraph(formatted_text, bullet_style)
        w, h = p.wrap(508, 150)
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
        p = Paragraph(formatted_text, bullet_style)
        w, h = p.wrap(508, 150)
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
