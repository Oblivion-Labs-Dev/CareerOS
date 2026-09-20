"""LLM service to generate candidate answers for open-ended job application questions."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.application_assistant.llm_client import create_llm_client

logger = logging.getLogger("career_os.application_assistant.llm_answer_generator")


SYSTEM_INSTRUCTION = """You answer job application questions using the candidate's resume and profile.

Your goal is to write the answer the candidate would naturally type themselves.

## Rules

Answer the exact question directly.

Use only facts supported by the resume or profile. Never invent experience, technologies, products, metrics, responsibilities, employers, or years of experience.

Choose the strongest 1 to 3 pieces of evidence relevant to the question. Prefer specific systems, products, scale, technical work, or measurable results over broad claims.

Write in first person unless the question asks otherwise.

Keep the answer to one short paragraph, usually 2 to 4 sentences and 40 to 100 words.

### Writing style

Write like a real software engineer filling out a job application, not like a recruiter, marketer, or AI assistant.

Use simple, natural professional English.

Prefer direct sentences such as:
"I worked on..."
"I built..."
"My experience includes..."
"At Amazon..."
"At Microsoft..."

Vary sentence structure naturally. Do not make every answer follow the same template.

Do not over-polish the writing. Slightly conversational wording is preferred over corporate language.

Do not use:
* em dashes
* semicolons unless necessary
* excessive adjectives
* buzzwords
* motivational language
* marketing language
* exaggerated claims
* unnecessary introductions
* unnecessary conclusions

Avoid common AI-sounding phrases such as:
* "I have extensive experience"
* "I have a proven track record"
* "I am passionate about"
* "I am well versed in"
* "I have leveraged"
* "I have spearheaded"
* "robust"
* "cutting-edge"
* "seamlessly"
* "end-to-end"
* "dynamic"
* "innovative solutions"
* "at scale" unless scale is actually relevant
* "Additionally"
* "Furthermore"
* "Moreover"

Do not start every response with "Yes, I have..."

If the question is yes/no, answer yes naturally and immediately move into evidence.

Do not repeat information just to make the paragraph longer.

Do not claim the candidate has X years of experience with a technology unless the resume explicitly supports that duration.

If the candidate has adjacent experience rather than exact experience, describe the closest relevant work honestly.

If there is not enough information in the resume to answer the question without guessing, return:
INSUFFICIENT_EVIDENCE: <brief explanation>

## Final check

Before returning the answer, silently check:
1. Is every claim supported by the resume?
2. Does this actually answer the question?
3. Does it sound like something a person would type into an application form?
4. Did I remove generic AI wording?
5. Did I avoid em dashes?
6. Is there anything I can delete without losing useful information?

Return only the answer. No headings, explanation, bullet points, quotation marks, or commentary."""


class _GeminiOffForApplications(Exception):
    """Gemini is disabled for the job-application path.

    Raised and swallowed locally so that "switched off" takes exactly the same
    fall-through route as "Gemini declined to answer", rather than needing a
    second copy of the code below.
    """


def _format_profile_text(profile_data: dict[str, Any]) -> str:
    parts = []
    full_name = profile_data.get("fullName") or f"{profile_data.get('firstName', '')} {profile_data.get('lastName', '')}".strip()
    if full_name:
        parts.append(f"Name: {full_name}")
    if profile_data.get("currentTitle") or profile_data.get("currentCompany"):
        parts.append(f"Current Role: {profile_data.get('currentTitle', '')} at {profile_data.get('currentCompany', '')}".strip())
    if profile_data.get("location"):
        parts.append(f"Location: {profile_data.get('location')}")
    if profile_data.get("skills"):
        skills = profile_data.get("skills")
        skills_str = ", ".join(skills) if isinstance(skills, list) else str(skills)
        parts.append(f"Skills: {skills_str}")
    if profile_data.get("summary") or profile_data.get("bio"):
        parts.append(f"Summary: {profile_data.get('summary') or profile_data.get('bio')}")
    if profile_data.get("github"):
        parts.append(f"GitHub: {profile_data.get('github')}")
    if profile_data.get("linkedin"):
        parts.append(f"LinkedIn: {profile_data.get('linkedin')}")

    return "\n".join(parts) if parts else "No profile metadata provided."


def _synthesize_profile_fallback(
    question: str,
    profile_data: dict[str, Any],
    resume_text: str = "",
    company: str = "",
    role: str = ""
) -> str:
    """A last-resort answer drawn only from values the profile actually holds.

    This used to carry keyword-triggered paragraphs of invented experience —
    "I built agentic AI workflows, LLM orchestration layers, and RAG pipelines"
    for any question mentioning AI, "I designed developer APIs, internal CLI
    tools, and web microservices" for any mentioning developers. None of it was
    checked against the resume, and it was returned with `success: True`, so
    the executor filled it in and submitted. Two of those templates went to
    real employers verbatim.

    Returning "" instead is the honest outcome: the caller leaves the field
    empty and the application goes to review, which is what the candidate
    actually wants for a question nothing in their profile answers.
    """
    from app.services.answer_engine import generate_answer
    engine_ans = generate_answer(question, company=company, role_title=role, profile=profile_data)
    if engine_ans:
        return engine_ans

    # Only questions whose answer is a literal profile field are safe to
    # complete without a model. Everything else is a claim about the
    # candidate's experience, and inventing one is the thing this must not do.
    q_lower = question.lower()
    if "github" in q_lower:
        return str(profile_data.get("github") or "")
    if "linkedin" in q_lower:
        return str(profile_data.get("linkedin") or "")
    if "portfolio" in q_lower or "website" in q_lower:
        return str(profile_data.get("portfolio") or profile_data.get("linkedin") or "")

    return ""


# Wording that means the model declined rather than answered. The system prompt
# asks for "INSUFFICIENT_EVIDENCE: ..." but models say it in their own words far
# more often than they emit the token — and one such sentence was submitted to
# an employer intact: "I don't have information about my interest in working at
# Discord. My profile shows I'm currently a Senior Software Engineer at
# Microsoft, and I haven't expressed any specific interest in joining Discord."
_NON_ANSWER_PATTERNS = (
    "insufficient_evidence",
    "i don't have information",
    "i do not have information",
    "i don't have enough information",
    "i do not have enough information",
    "my profile doesn't include",
    "my profile does not include",
    "my profile shows",
    "there's no evidence in my background",
    "there is no evidence in my background",
    "no evidence in my background",
    "i haven't expressed",
    "i have not expressed",
    "the resume doesn't",
    "the resume does not",
    "as an ai",
    "i cannot answer",
    "i can't answer",
    "i'm unable to",
    "i am unable to",
    "based on the information provided, i",
)


def story_evidence_for(question: str, *, role: str = "", limit: int = 3) -> str:
    """Recorded experience stories that speak to this question.

    The experience corpus already powers resume tailoring, but nothing fed it to
    the code that answers application questions — so a long-form prompt like
    Canonical's "Describe your Python software development experience" had only
    the resume and the flat profile to work from, and declined for want of
    evidence that was sitting in the corpus the whole time.

    These are the candidate's own recorded stories, so using them is grounding,
    not invention: the model is being handed more of what it is allowed to say,
    never licence to say more.

    ``doNotClaim`` is carried through verbatim and stated as a prohibition. A
    story is a record of what happened *and* of what must not be read into it,
    and dropping that half while keeping the narrative is how an application
    ends up overstating the candidate.
    """
    text = f"{question} {role}".strip()
    if not text:
        return ""
    try:
        from app.services.story_index import get_index

        matches = get_index().rank(text, title=role, limit=limit)
    except Exception:  # noqa: BLE001 - evidence is an enrichment, never load-bearing
        logger.debug("Story evidence unavailable for %r", question[:60], exc_info=True)
        return ""

    # `rank` scores every story independently, and its own docstring warns that
    # several stories on one subject all score highly together. For a single
    # question that is mostly fine, but three near-identical accounts crowd out
    # the variety the answer needs, so keep one per headline.
    blocks: list[str] = []
    seen_headlines: set[str] = set()
    for match in matches:
        if len(blocks) >= limit:
            break
        story = match.story
        headline_key = (story.headline or story.title or "").strip().lower()
        if headline_key and headline_key in seen_headlines:
            continue
        seen_headlines.add(headline_key)
        parts = [f"- {story.headline or story.title}".rstrip()]
        if story.company:
            parts[0] += f" ({story.company})"
        body = (story.body or "").strip()
        if body:
            parts.append(f"  {body[:700]}")
        if story.metrics:
            parts.append("  Measured: " + "; ".join(str(m) for m in story.metrics[:3]))
        if story.do_not_claim:
            parts.append("  Must NOT be claimed: " + "; ".join(str(d) for d in story.do_not_claim[:3]))
        blocks.append("\n".join(parts))

    return "\n\n".join(blocks)


def _is_non_answer(text: str) -> bool:
    """Whether the model declined instead of answering.

    Checked on the model's own output before it can reach a form. A decline is
    a legitimate result — the question genuinely has no answer in the profile —
    but it belongs in review, not in the textarea.
    """
    lowered = (text or "").strip().lower()
    if not lowered:
        return True
    return any(pattern in lowered for pattern in _NON_ANSWER_PATTERNS)


def _declined(question: str, reason: str) -> dict[str, Any]:
    """No honest answer exists, so return none.

    The executor's contract already covers this case - an empty value leaves
    the field blank and sends the application to review instead of submitting
    it. What was missing was any path that actually produced an empty value:
    every branch here returned `success: True` with something invented.
    """
    return {
        "success": False,
        "answer": "",
        "question": question,
        "insufficientEvidence": True,
        "reason": reason,
    }


async def generate_theory_answer(
    question: str,
    *,
    company: str = "",
    role: str = "",
    job_description: str = "",
    profile: dict[str, Any] | None = None,
    resume_text: str = "",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generates a professional, concise candidate answer to a custom open-ended application question.
    Uses candidate's resume/profile details and Ollama Qwen model, following user's precise prompt template.
    """
    if not question or not question.strip():
        return {"success": False, "error": "Question is empty"}

    profile_data = profile or {}
    settings_data = settings or {}
    client = create_llm_client(settings_data)

    effective_resume = resume_text or profile_data.get("resumeText") or profile_data.get("resume") or ""
    formatted_profile = _format_profile_text(profile_data)
    story_block = story_evidence_for(question, role=role)

    # Gemini first, when it is enabled for applications and the question is
    # open-ended. It is better at this than a 4B local model and costs no local
    # RAM, which is the whole reason this layer exists. Anything it will not
    # answer honestly - including being switched off for the application path -
    # falls through to the paths below unchanged.
    from app.services.gemini.config import applications_enabled

    try:
        if not applications_enabled():
            raise _GeminiOffForApplications
        from app.services.gemini.enrichment import answer_application_question

        enriched = await answer_application_question(
            question,
            profile=profile_data,
            resume_text=effective_resume,
            company=company,
            role=role,
            job_description=job_description,
        )
        if enriched.available and not _is_non_answer(enriched.answer):
            return {
                "success": True,
                "answer": enriched.answer,
                "question": question,
                "provider": "gemini",
                "confidence": enriched.confidence,
                "evidence": enriched.evidence,
            }
    except _GeminiOffForApplications:
        pass  # Switched off for applications; the paths below answer instead.
    except Exception:  # noqa: BLE001 - optional layer, never load-bearing
        pass

    if not client.enabled:
        fallback_ans = _synthesize_profile_fallback(
            question,
            profile_data,
            resume_text=effective_resume,
            company=company,
            role=role
        )
        if not fallback_ans:
            return _declined(question, "no profile evidence answers this question")
        return {"success": True, "answer": fallback_ans, "question": question, "fallback": True}

    # Construct user prompt adhering strictly to user template
    user_prompt = (
        f"You answer job application questions using the candidate's resume and profile.\n\n"
        f"Your goal is to write the answer the candidate would naturally type themselves.\n\n"
        f"## Resume\n\n"
        f"{effective_resume[:6000] if effective_resume else 'No resume text provided.'}\n\n"
        f"## Profile\n\n"
        f"{formatted_profile}\n\n"
        + (
            f"## Recorded experience\n\n"
            f"These are the candidate's own written accounts of work they did. Treat them "
            f"as evidence on the same footing as the resume, and honour every "
            f"\"Must NOT be claimed\" line exactly.\n\n{story_block}\n\n"
            if story_block
            else ""
        )
        + f"## Question\n\n"
        f"{question.strip()}\n"
    )

    response = await client.chat(
        messages=[{"role": "user", "content": user_prompt}],
        system=SYSTEM_INSTRUCTION,
    )

    if not response.get("success"):
        fallback_ans = _synthesize_profile_fallback(
            question,
            profile_data,
            resume_text=effective_resume,
            company=company,
            role=role
        )
        if not fallback_ans:
            return _declined(question, "no profile evidence answers this question")
        return {"success": True, "answer": fallback_ans, "question": question, "fallback": True}

    raw_text = str(response.get("data", "")).strip()

    # The model either said it had nothing to go on, or said so in its own
    # words. Either way this is not an answer, and the only safe fallback is a
    # value the profile literally holds - never a synthesised claim.
    if _is_non_answer(raw_text):
        fallback_ans = _synthesize_profile_fallback(
            question,
            profile_data,
            resume_text=effective_resume,
            company=company,
            role=role
        )
        if not fallback_ans:
            return _declined(question, "the model found no supporting evidence in the resume or profile")
        return {"success": True, "answer": fallback_ans, "question": question, "insufficientEvidence": True}

    # Strip surrounding quotes if present
    if (raw_text.startswith('"') and raw_text.endswith('"')) or (raw_text.startswith("'") and raw_text.endswith("'")):
        raw_text = raw_text[1:-1].strip()

    if _is_non_answer(raw_text):
        return _declined(question, "the model declined to answer from the available evidence")

    return {
        "success": True,
        "answer": raw_text,
        "question": question,
    }
