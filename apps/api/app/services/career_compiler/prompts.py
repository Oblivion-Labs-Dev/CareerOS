"""Prompts and the compact payloads DeepSeek sees. Only retrieved records are sent. DeepSeek writes content only."""
from __future__ import annotations

from typing import Any

from app.services.career_compiler.models import JobDescription, JobInput, Retrieval

STRUCTURE_SYSTEM = """You turn a software job description into structured requirements.
Return JSON: {"title", "company", "requirements": [{"section", "original_text", "normalized_requirement",
"skills", "themes", "importance", "required"}]}.
- section is one of: responsibilities, required_qualifications, preferred_qualifications, technologies, domain,
  architecture, leadership, ai_ml. Use ai_ml only when the posting asks for AI/ML work.
- original_text must be copied exactly, character for character, from the posting: one bullet or one sentence.
- normalized_requirement restates that requirement plainly in one short sentence. Do not add anything.
- skills: technologies or skills named in original_text (1-3 words each). themes: 1-3 short themes.
- importance: high, medium or low, judged from the posting's own emphasis.
- required: true only when the posting itself marks the item as required, minimum, basic or must-have.
- Never invent requirements, skills or seniority the posting does not state. Skip benefits, salary, EEO text."""

QUERY_SYSTEM = """You describe what evidence would prove a candidate meets each job requirement.
You receive structured requirements and the vocabulary of the candidate's evidence store (technology, concept and
tag names only). You never see or state facts about the candidate.
For each requirement return:
- terms: vocabulary entries that mean the same thing as the requirement (synonyms, spelled-out forms, the same skill
  in other words). Never list a different product as a term: a requirement for Kafka does not have Kinesis as a term.
- adjacent: vocabulary entries for related but different work that an engineer could point to as transferable.
- evidence_types: which kinds of evidence would prove it (from evidence_types).
Use only strings that appear in the vocabulary, copied exactly. Leave lists empty rather than guess.
Return JSON: {"requirements": [{"requirement_id", "terms", "adjacent", "evidence_types"}]}."""

RANK_SYSTEM = """You select which of a candidate's existing projects best answer a job's requirements.
You receive structured requirements (id, section, importance, text) and candidate projects with the
requirement ids each already covers and their evidence records, all retrieved by the application.
Only use project_id and evidence id values from the input. Never invent facts.
Prefer projects that show ownership, technical depth and measured impact on the most important requirements, and
avoid picking two projects that prove the same thing.
Return JSON: {"target_role": (the role in a few words), "primary_themes": (2-5 themes this resume should emphasise,
taken from the requirements), "projects": [{"project_id", "score" (0-100), "reason" (one sentence naming the
requirement ids it answers), "evidence_ids" (the 1-4 strongest ids)}]}, best first. Omit weak projects."""

VOICE = """Voice: direct, technical, concrete, implementation-oriented, restrained, naturally varied, human-written.
Prefer: what was built, then how it actually worked, then scale or impact when it is meaningful. Do not force every
bullet into one formula, and vary how bullets open. Correct grammar and spelling.
Avoid: leveraged, utilized, cutting-edge, innovative solution, transformative, revolutionized, spearheaded,
"utilized X to optimize Y", and trailing "resulting in ..." or "showcasing ..." clauses that add no information.
style_exemplars show the user's own writing. Imitate their voice only. Their facts are NOT evidence: never copy
their numbers, technologies or claims.
style_preferences, when present, are the user's past corrections: a REJECTED bullet, the reason, and the version
they PREFERRED (or bullets they accepted). Learn the style lesson only. Never copy their projects, technologies,
metrics or claims."""

WRITE_SYSTEM = """You write resume bullets strictly from supplied evidence records.
Rules:
- Each bullet fills one slot and may only use facts from that slot's evidence claims and project context.
- Cite every evidence id you used in evidence_ids. Every number in the text must appear in a cited claim.
- Never add technologies, metrics, scale, ownership, responsibilities, dates, business impact or architecture
  that the supplied records do not state. A bullet without a metric is fine.
- For a slot marked existence_only, state only that the work existed, in plain words, with no numbers,
  technologies or outcomes beyond the claim.
- Each slot lists target requirements. Address them only where the evidence genuinely supports it.
- Respect max_chars for every slot; the layout is fixed and cannot grow. Plain text only, no markdown.
- Personal-project slots are printed after a bold "Project name:" label. Do not repeat the project name; start
  with what was built, e.g. "Built ...".
- The summary follows the same rules: cite every summary_slot evidence id whose facts or technologies it mentions.
- Respect every guardrail and conflict usage rule.
""" + VOICE + """
Return JSON: {"summary": {"text", "evidence_ids"} or null, "bullets": [{"slot_id", "text", "evidence_ids"}]}."""

REPAIR_SYSTEM = WRITE_SYSTEM + """
Some bullets failed validation. Rewrite only the listed slots using only their allowed evidence.
Fix each listed problem by removing or replacing the unsupported content, never by adding new facts. Each error
names the unsupported claim and, in allowed_evidence, the exact wording the evidence does support: use that or
drop the claim.
rejected_drafts holds your previous text for each failing slot: edit that draft rather than starting over, and
respect max_chars strictly (count characters; cut whole clauses to get under it)."""

COMPRESS_SYSTEM = """You shorten resume bullets so they fit a fixed layout.
Each item has its current text, its cited evidence, and max_chars. Return a shorter version under max_chars that
keeps the same meaning. You may drop detail; you may not add facts, numbers, technologies or claims, and you may
only cite the item's evidence ids.
""" + VOICE + """
Return JSON: {"bullets": [{"slot_id", "text", "evidence_ids"}]}."""

RESTYLE_SYSTEM = """You fix the writing style of resume bullets without changing any fact.
Keep every number, technology, claim and evidence id exactly as given; change only wording and structure to address
the listed style problems. Stay under max_chars.
""" + VOICE + """
Return JSON: {"bullets": [{"slot_id", "text", "evidence_ids"}]}."""


CRITIC_SYSTEM = """You review the writing style of resume bullets. You do not rewrite them and you never judge or
change facts: assume every number, technology and claim is correct.
Score each bullet 0-100 for how well it reads as the candidate's own direct, technical, specific writing
(style_exemplars show their voice). List at most 4 concrete issues, each with a code from: technical_specificity,
jd_relevance, clarity, seniority, redundancy, unnecessary_adjectives, density, repeated_pattern, generic_ai_language,
voice_mismatch, and a short message saying exactly what to change. Look across bullets for repeated openings and
repeated sentence shapes. Set rewrite true only when the issues are worth a rewrite; a plain, specific bullet with no
metric is fine.
Return JSON: {"bullets": [{"bullet_id", "style_score", "issues": [{"code", "message"}], "rewrite"}]}."""

PROMPT_VERSIONS = {"structure": "structure-v2", "query": "evidence-query-v1", "rank": "rank-v2", "write": "write-v3",
                   "repair": "repair-v2", "compress": "compress-v1", "restyle": "restyle-v2", "critic": "style-critic-v1"}


def structure_user(job: JobInput) -> dict[str, Any]:
    return {"title_hint": job.title, "company_hint": job.company, "job_description": job.text}


def _requirements(jd: JobDescription) -> list[dict[str, Any]]:
    return [{"id": r.id, "section": r.section, "importance": r.importance, "requirement": r.normalized_requirement}
            for r in jd.requirements]


def query_user(jd: JobDescription, vocabulary: dict[str, list[str]]) -> dict[str, Any]:
    return {"role": jd.title, "requirements": [{"id": r.id, "section": r.section, "text": r.original_text,
                                                "skills": r.skills} for r in jd.requirements],
            "vocabulary": vocabulary}


def rank_user(jd: JobDescription, retrieval: Retrieval) -> dict[str, Any]:
    return {
        "role": jd.title, "requirements": _requirements(jd),
        "candidates": [{
            "project_id": p.project_id, "company": p.company or "Personal project", "name": p.name,
            "existence_only": p.existence_only, "covers": p.coverage,
            "evidence": [{"id": c.evidence_id, "type": c.type, "claim": c.claim} for c in p.evidence],
        } for p in retrieval.projects],
    }


def write_user(slots: list[dict[str, Any]], *, style: dict[str, Any], exemplars: list[str], guardrails: list[str],
               conflicts: list[dict], locked: list[str], summary: dict[str, Any] | None, target_role: str,
               preferences: list[dict] | None = None, themes: list[str] | None = None) -> dict[str, Any]:
    return {
        "target_role": target_role,
        "primary_themes": themes or [],
        "writing_style": style,
        "style_exemplars": exemplars,
        "style_preferences": preferences or [],
        "guardrails": guardrails,
        "conflict_rules": [{"subject": c.get("subject"), "usage_rule": c.get("usage_rule")} for c in conflicts],
        "already_on_resume_do_not_repeat": locked,
        "summary_slot": summary,
        "slots": slots,
    }
