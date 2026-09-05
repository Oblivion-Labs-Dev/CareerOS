"""Resume Diff & Tailoring Intelligence Service.

Computes fine-grained additions, deletions, and semantic alignments between
a candidate's master resume and job-tailored application materials.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

logger = logging.getLogger("career_os.resume_diff_service")


def compute_text_diff_chunks(original: str, modified: str) -> list[dict[str, str]]:
    """Compute word/token-level diff chunks between original and modified text.
    
    Returns list of dicts: [{"type": "eq" | "add" | "del", "text": "..."}]
    """
    if not original and not modified:
        return []
    if not original:
        return [{"type": "add", "text": modified}]
    if not modified:
        return [{"type": "del", "text": original}]

    matcher = difflib.SequenceMatcher(None, original.split(" "), modified.split(" "))
    chunks: list[dict[str, str]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            chunks.append({"type": "eq", "text": " ".join(original.split(" ")[i1:i2])})
        elif tag == "delete":
            chunks.append({"type": "del", "text": " ".join(original.split(" ")[i1:i2])})
        elif tag == "insert":
            chunks.append({"type": "add", "text": " ".join(modified.split(" ")[j1:j2])})
        elif tag == "replace":
            chunks.append({"type": "del", "text": " ".join(original.split(" ")[i1:i2])})
            chunks.append({"type": "add", "text": " ".join(modified.split(" ")[j1:j2])})

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
    """
    valid_mode = mode if mode in ("off", "honest", "aggressive") else "honest"
    company = job.get("company") or "Target Company"
    title = job.get("title") or "Target Role"
    description = job.get("description") or job.get("snippet") or ""

    # Extract sample master bullets or summary
    experiences = profile.get("experience") or []
    master_bullets: list[str] = []
    for exp in experiences:
        if isinstance(exp, dict) and exp.get("highlights"):
            highlights = exp.get("highlights")
            if isinstance(highlights, list):
                master_bullets.extend([str(h) for h in highlights[:4]])
            elif isinstance(highlights, str):
                master_bullets.extend([b.strip() for b in highlights.split("\n") if b.strip()][:3])

    if not master_bullets:
        master_bullets = [
            "Built the historical risk foundation for AI Agent Risk Detection, reconstructing 90 days of activity across 40+ environments to eliminate onboarding blind spots and enable day-one risk evaluation for 237K+ agents across 13K organizations.",
            "Drove architecture across Purview IRM, Entra, and DLP for Microsoft’s AI-agent Adaptive Protection pipeline, owning design, implementation, and launch from risk scoring through Conditional Access enforcement and shipped the capability with Microsoft 365 E7.",
            "Led the redesign of AI-agent ingestion for independent scale and fault isolation, separating agent and human workloads across 28 deployments processing 135K+ security signals/day and protecting existing Insider Risk Management pipelines as agent traffic grew.",
            "Led AI Risk Detection's sovereign-cloud architecture and rollout across GCC, GCCH and DoD, engineering deployment and disaster-recovery infrastructure across 53 resource groups and 51 deployments and establishing the first Gov-cloud Kusto monitoring infrastructure.",
            "Connected investigations across Microsoft's security ecosystem, linking related risk across Entra, Defender, Sentinel, Microsoft Graph, and Insider Risk Management and increasing customer engagement with related cross-product investigations 16%.",
            "Designed an AI-assisted testing workflow using agent skills and Playwright to provision test tenants, configure Copilot Studio agents with tools/policies, trigger controlled security risks and alerts, and validate end-to-end behavior.",
            "Designed an AI-assisted debugging workflow spanning three repositories, combining historical incident analysis with Playwright to reproduce issues, implement and validate fixes, capture evidence, and create pull requests.",
        ]

    tailored_bullets: list[str] = []

    if valid_mode == "off":
        # Off: passthrough exact master bullets with zero alteration
        tailored_bullets = list(master_bullets)
    else:
        # Generate bullets via LLM: Mistral primary (via Ollama) with automatic fallback to Gemini Flash
        from app.services.application_assistant.llm_client import create_llm_client
        import json

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

        prompt = (
            f"You are an expert resume tailoring assistant.\n"
            f"Candidate experience bullets to tailor:\n"
            + "\n".join(f"- {b}" for b in master_bullets)
            + f"\n\nTarget Role: {title} at {company}\n"
            f"Job Context / Snippet: {description[:800]}\n"
            f"Tailoring Mode: {valid_mode.upper()}\n"
            f"Instructions:\n"
            + (
                "- Mode HONEST: Strictly preserve candidate's factual achievements, tech stack, and scope. Reorganize, rephrase, and highlight keywords and competencies matching the target job description while remaining 100% truthful.\n"
                if valid_mode == "honest" else
                "- Mode AGGRESSIVE: Elevate executive presence, amplify leadership impact, emphasize scale and high-impact metrics (e.g., enterprise SLAs, latency, cross-team influence) to aggressively align with the job description and maximize callback rates.\n"
            )
            + f"- Return exactly {len(master_bullets)} bullets corresponding 1-to-1 in order with the original bullets.\n"
            f"- Return ONLY a JSON array of strings, e.g. [\"bullet 1\", \"bullet 2\", ...]\n"
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
                    tailored_bullets = [str(p) for p in parsed]
                    logger.info(f"Resume tailored successfully with model: {res.get('usedFallbackModel') or client.model}")
        except Exception as e:
            logger.warning(f"LLM resume tailoring failed, using template fallback: {e}")

        if not tailored_bullets:
            # High quality template fallbacks tailored specifically to title & company
            title_lower = title.lower()
            if valid_mode == "honest":
                if "ai" in title_lower or "ml" in title_lower or "agent" in title_lower:
                    tailored_bullets = [
                        f"Built the historical risk foundation for AI Agent Risk Detection, reconstructing 90 days of multi-tenant activity to enable day-one evaluation for 237K+ autonomous agents across 13K organizations, directly applicable to {company}'s AI roadmap.",
                        f"Drove cross-service architecture across Purview IRM, Entra, and DLP for Microsoft's AI-agent Adaptive Protection pipeline, owning end-to-end launch through Conditional Access enforcement shipped with Microsoft 365 E7.",
                        f"Led the redesign of AI-agent ingestion for independent scale and fault isolation, separating agent and human workloads across 28 deployments processing 135K+ security signals/day.",
                        f"Designed an AI-assisted testing workflow using agent skills and Playwright to provision test tenants, configure Copilot Studio agents with tools/policies, and validate end-to-end behavior for high-reliability systems.",
                        f"Designed an AI-assisted debugging workflow spanning three repositories, combining historical incident analysis with Playwright to reproduce issues, implement fixes, and create automated pull requests.",
                        f"Connected cross-product investigations across Entra, Defender, Sentinel, Microsoft Graph, and Insider Risk Management, elevating customer investigation engagement by 16%.",
                        f"Led sovereign-cloud architecture and rollout across GCC, GCCH and DoD across 53 resource groups and 51 deployments, establishing the first Gov-cloud Kusto monitoring infrastructure.",
                    ]
                elif "cloud" in title_lower or "infra" in title_lower or "platform" in title_lower:
                    tailored_bullets = [
                        f"Led cloud platform infrastructure and sovereign-cloud rollout across GCC, GCCH, and DoD across 53 resource groups and 51 deployments, establishing high-scale Kusto monitoring and disaster-recovery pipelines aligned with {company}'s cloud architecture.",
                        f"Architected AI-agent ingestion infrastructure for independent scale and fault isolation, decoupling workloads across 28 deployments processing 135K+ high-frequency events/day.",
                        f"Engineered historical risk pipeline reconstructing 90 days of high-throughput telemetry across 40+ cloud environments for 237K+ instances across 13K customer organizations.",
                        f"Drove multi-service architecture spanning Purview IRM, Entra, and DLP, designing risk scoring through Conditional Access enforcement shipped at global enterprise scale.",
                        f"Orchestrated cross-system security telemetry across Entra, Defender, Sentinel, and Graph, increasing cross-service investigation engagement 16%.",
                        f"Built automated cloud testing and synthetic tenant orchestration using Playwright and agent automation for continuous integration and fault injection.",
                        f"Created telemetry-driven incident reproduction and automated remediation workflows across multiple repositories, accelerating fix delivery and reliability.",
                    ]
                else:
                    tailored_bullets = [
                        f"Architected and delivered core platform capabilities for AI Agent Risk Detection, processing 90 days of activity across 40+ environments to enable zero-day evaluation for 237K+ agents across 13K organizations.",
                        f"Spearheaded distributed system architecture across Purview IRM, Entra, and DLP for adaptive security pipelines, driving design from risk scoring to policy enforcement at Microsoft scale.",
                        f"Led decoupled ingestion architecture across 28 distributed deployments handling 135K+ security signals/day, ensuring fault isolation and high system availability.",
                        f"Directed sovereign-cloud rollout across GCC, GCCH, and DoD across 53 resource groups, implementing robust disaster recovery and distributed telemetry monitoring.",
                        f"Integrated complex multi-service workflows across Defender, Sentinel, Entra, and Microsoft Graph, driving a 16% increase in cross-product customer adoption.",
                        f"Architected automated testing and verification workflows using Playwright to dynamically configure services, simulate risk workloads, and validate end-to-end resilience.",
                        f"Built multi-repository debugging automation combining incident telemetry and automated testing to accelerate root-cause analysis and code fixes.",
                    ]
            else:
                # Aggressive
                tailored_bullets = [
                    f"Spearheaded Microsoft's flagship enterprise AI Agent Risk Detection platform as lead architect, orchestrating 90-day activity reconstruction across 40+ global environments to unlock instant day-one risk governance for 237,000+ AI agents across 13,000 enterprise customers.",
                    f"Directed principal-level architecture across Purview IRM, Entra, and DLP for Microsoft's flagship AI Adaptive Protection pipeline; authored the end-to-end technical spec and shipped core conditional access enforcement powering Microsoft 365 E7.",
                    f"Pioneered hyper-scale distributed ingestion infrastructure with zero-latency fault isolation, partitioning agent and human traffic across 28 worldwide deployments processing 150K+ critical security signals/day at 99.999% SLA.",
                    f"Championed sovereign-cloud infrastructure expansion across US GCC, GCCH, and DoD high-security enclaves, orchestrating 53 Azure resource groups and 51 deployments with automated disaster recovery and real-time Kusto telemetry.",
                    f"Orchestrated unified investigation graphs across Entra, Defender, Sentinel, and Graph, delivering unified threat intelligence that boosted customer security operation engagement by 28%.",
                    f"Architected autonomous AI-agent synthetic validation and end-to-end test harnesses using Playwright, simulating advanced attack vectors and policy violations across dynamic enterprise environments.",
                    f"Pioneered closed-loop AI debugging and self-healing pipelines across 3 major codebases, integrating telemetry pattern recognition with Playwright to automatically reproduce issues, generate code fixes, and submit PRs.",
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
    - 'off': Returns the exact, byte-for-byte authentic original resume PDF.
    - 'honest' / 'aggressive': Preserves 100% of the candidate's authentic resume layout, styling,
      hyperlinks, Amazon experience, Liquiron, Persistent Systems, Education, and Skills, applying
      a pixel-perfect overlay only to the Microsoft experience section to reflect the tailored bullets.
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

    # Locate the original resume PDF
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

    # In 'honest' or 'aggressive' mode: overlay tailored Microsoft bullets onto original PDF
    reader = PdfReader(str(orig_path))
    page = reader.pages[0]

    # Create overlay canvas
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)

    # 1. Mask the original Microsoft bullets with exact white bounding box
    # Coordinates derived from original PDF: x=48 to 580, y=550 to 684
    can.setFillColor(colors.white)
    can.rect(48, 550, 532, 134, fill=1, stroke=0)

    # 2. Add subtle mode indicator badge on the top right
    badge_colors = {
        "honest": colors.HexColor("#0d9488"),
        "aggressive": colors.HexColor("#e11d48"),
    }
    mode_text = f"TSENTA {mode.upper()}"
    can.setFillColor(badge_colors.get(mode, colors.HexColor("#0284c7")))
    can.setFont("Helvetica-Bold", 7.0)
    can.drawRightString(576, 772, mode_text)

    # 3. Render the tailored bullets inside the Microsoft block
    bullet_style = ParagraphStyle(
        "OverlayBullet",
        fontName="Helvetica",
        fontSize=7.8,
        leading=9.2,
        textColor=colors.HexColor("#000000"),
    )

    bullets = [b.get("tailored") or b.get("original") for b in diff_data.get("bulletDiffs", []) if (b.get("tailored") or b.get("original"))]
    if not bullets:
        bullets = [
            "Built the historical risk foundation for AI Agent Risk Detection, reconstructing 90 days of activity across 40+ environments to eliminate onboarding blind spots and enable day-one risk evaluation for 237K+ agents across 13K organizations.",
            "Drove architecture across Purview IRM, Entra, and DLP for Microsoft’s AI-agent Adaptive Protection pipeline, owning design, implementation, and launch from risk scoring through Conditional Access enforcement and shipped the capability with Microsoft 365 E7.",
            "Led the redesign of AI-agent ingestion for independent scale and fault isolation, separating agent and human workloads across 28 deployments processing 135K+ security signals/day and protecting existing Insider Risk Management pipelines as agent traffic grew.",
            "Led AI Risk Detection's sovereign-cloud architecture and rollout across GCC, GCCH and DoD, engineering deployment and disaster-recovery infrastructure across 53 resource groups and 51 deployments and establishing the first Gov-cloud Kusto monitoring infrastructure.",
            "Connected investigations across Microsoft's security ecosystem, linking related risk across Entra, Defender, Sentinel, Microsoft Graph, and Insider Risk Management and increasing customer engagement with related cross-product investigations 16%.",
            "Designed an AI-assisted testing workflow using agent skills and Playwright to provision test tenants, configure Copilot Studio agents with tools/policies, trigger controlled security risks and alerts, and validate end-to-end behavior.",
            "Designed an AI-assisted debugging workflow spanning three repositories, combining historical incident analysis with Playwright to reproduce issues, implement and validate fixes, capture evidence, and create pull requests.",
        ]

    y_curr = 684.0
    for b in bullets:
        # Draw clean bullet dot at original X=54
        can.setFillColor(colors.HexColor("#000000"))
        can.setFont("Helvetica", 7.8)
        can.drawString(54.0, y_curr - 7.5, chr(8226))
        # Draw wrapped bullet text starting at X=72 with width 504
        p = Paragraph(b, bullet_style)
        w, h = p.wrap(504, 120)
        p.drawOn(can, 72.0, y_curr - h)
        y_curr -= (h + 1.2)

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
