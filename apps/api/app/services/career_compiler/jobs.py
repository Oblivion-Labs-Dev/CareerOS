"""Stages 1-2: ingest a job description and structure it into jd.json."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from app.services.career_compiler import prompts
from app.services.career_compiler.deepseek import DeepSeekClient, DeepSeekError
from app.services.career_compiler.models import SECTIONS, JobAnalysis, JobDescription, JobInput, Requirement
from app.services.career_compiler.store import CareerStore, mentions, tokens

logger = logging.getLogger("careeros.career_compiler")
MAX_JD_CHARS = 14000
IMPORTANCE_RANK = {"low": 0, "medium": 1, "high": 2}
HEADING_SECTIONS = (
    (re.compile(r"prefer|nice to have|bonus|plus\b|desired", re.I), "preferred_qualifications"),
    (re.compile(r"requir|minimum|basic qualif|must have|what you.ll need|qualifications|who you are", re.I), "required_qualifications"),
    (re.compile(r"responsib|what you.ll do|what you will do|the role|day to day|you will", re.I), "responsibilities"),
)
BOILERPLATE = re.compile(r"equal opportunity|benefits|salary|compensation|401\(?k|pay range|accommodation|about us|"
                         r"privacy|e-verify|veteran|disabilit", re.I)
REQUIREMENT_CUE = re.compile(r"\b(experience|ability|able to|knowledge|familiar|proficien|build|design|own|lead|"
                             r"mentor|develop|drive|deliver|work with|partner|you will|you'll|strong|deep|expert)", re.I)


class _RawRequirement(BaseModel):
    section: str
    original_text: str
    normalized_requirement: str = ""
    skills: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    importance: str = "medium"
    required: bool = False


class _RawJD(BaseModel):
    title: str = ""
    company: str = ""
    requirements: list[_RawRequirement] = Field(default_factory=list)


def data_root() -> Path:
    """Where feedback, resume versions and outcomes live. Never career.json's directory."""
    configured = os.environ.get("CAREEROS_COMPILER_DATA")
    return Path(configured) if configured else Path(__file__).resolve().parents[3] / "data" / "career_compiler"


def cache_dir() -> Path:
    configured = os.environ.get("CAREEROS_JD_CACHE")
    return Path(configured) if configured else Path(__file__).resolve().parents[3] / "data" / "career_compiler" / "jd"


def _norm(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"[\u2022\u25cf\u25aa\u2023\u2043\-\*]\s+", " ", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def jd_id(text: str) -> str:
    return hashlib.sha256(_norm(text).encode()).hexdigest()[:16]


def ingest_job_description(text: str = "", url: str = "", title: str = "", company: str = "") -> JobInput:
    text = (text or "").strip()
    if not text and url:
        from app.services.job_discover.url_import import autoextract_job_from_url
        fetched = autoextract_job_from_url(url) or {}
        text = str(fetched.get("description") or "").strip()
        title = title or str(fetched.get("title") or "")
        company = company or str(fetched.get("company") or "")
        if not text:
            raise ValueError("Could not read a job description from that URL. Paste the description instead.")
    if len(text) < 40:
        raise ValueError("Paste a job description of at least 40 characters, or a job URL.")
    text = re.sub(r"\n{3,}", "\n\n", text)[:MAX_JD_CHARS]
    return JobInput(text=text, url=url, title=title.strip(), company=company.strip())


def _units(text: str) -> list[str]:
    units = []
    for line in text.splitlines():
        line = re.sub(r"^\s*[\u2022\u25cf\u25aa\-\*\d.)]+\s*", "", line).strip()
        if not line:
            continue
        units.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if s.strip())
    return units


def _locate(original: str, jd_text: str, units: list[str]) -> tuple[str, int] | None:
    """Return the verbatim JD wording for `original` and its position, or None if the JD lacks it."""
    haystack = _norm(jd_text)
    pieces = original.split()
    if pieces:
        exact = re.search(r"\s+".join(re.escape(p) for p in pieces), jd_text, re.I)
        if exact:
            return exact.group(0), haystack.find(_norm(exact.group(0)))
    words = tokens(original)
    best, best_score = None, 0.0
    for unit in units:
        unit_words = tokens(unit)
        if words and unit_words:
            score = len(words & unit_words) / len(words)
            if score > best_score:
                best, best_score = unit, score
    if best and best_score >= .8:
        return best, haystack.find(_norm(best))
    return None


def _skills_in(text: str, skills: list[str], store: CareerStore) -> list[str]:
    kept = [s.strip() for s in skills if s.strip() and (mentions(text, s.strip()) or (tokens(s) and tokens(s) <= tokens(text)))]
    kept += [t for t in store.technologies + store.concepts if mentions(text, t)]
    out, seen = [], set()
    for skill in kept:
        if skill.casefold() not in seen:
            seen.add(skill.casefold())
            out.append(skill)
    return out[:10]


def _finalize(raw: list[_RawRequirement], job: JobInput, store: CareerStore, source: str, title: str, company: str,
              dropped: list[str]) -> JobDescription:
    units = _units(job.text)
    placed: list[tuple[int, int, Requirement]] = []
    seen = set()
    for item in raw:
        section = item.section if item.section in SECTIONS else None
        located = _locate(item.original_text, job.text, units) if section else None
        if not located:
            dropped.append(item.original_text[:160])
            continue
        original, offset = located
        key = (section, _norm(original))
        if key in seen:
            continue
        seen.add(key)
        importance = item.importance if item.importance in IMPORTANCE_RANK else "medium"
        if section == "required_qualifications":
            importance = "high"
        elif section == "preferred_qualifications" and importance == "high":
            importance = "medium"
        placed.append((offset, SECTIONS.index(section), Requirement(
            id="", section=section, original_text=original,
            normalized_requirement=(item.normalized_requirement or original).strip()[:300],
            skills=_skills_in(original, item.skills, store), themes=[t.strip() for t in item.themes if t.strip()][:4],
            importance=importance, offset=max(offset, 0),
            required=item.required and section != "preferred_qualifications")))
    placed.sort(key=lambda p: (p[0], p[1], p[2].original_text))
    requirements = [r.model_copy(update={"id": f"R{i}"}) for i, (_, _, r) in enumerate(placed, 1)]
    return with_repeated_themes(JobDescription(id=jd_id(job.text), title=title or job.title, company=company or job.company,
                                               url=job.url, text=job.text, requirements=requirements, source=source,
                                               dropped=dropped))


def with_repeated_themes(jd: JobDescription) -> JobDescription:
    """Mark themes and skills the posting returns to in two or more requirements. Pure function of jd.json."""
    def terms(req: Requirement) -> dict[str, str]:
        return {t.strip().casefold(): t.strip() for t in [*req.themes, *req.skills] if t.strip()}

    counts = Counter(key for req in jd.requirements for key in terms(req))
    repeated = {key for key, n in counts.items() if n >= 2}
    labels: dict[str, str] = {}
    requirements = []
    for req in jd.requirements:
        mine = {k: v for k, v in terms(req).items() if k in repeated}
        for key, label in mine.items():
            labels.setdefault(key, label)
        requirements.append(req.model_copy(update={"repeated_themes": sorted(mine.values(), key=str.casefold)}))
    ordered = sorted(repeated, key=lambda k: (-counts[k], k))
    return jd.model_copy(update={"requirements": requirements, "repeated_themes": [labels[k] for k in ordered]})


def _deterministic_raw(job: JobInput, store: CareerStore) -> list[_RawRequirement]:
    raw, context = [], "responsibilities"
    for unit in _units(job.text):
        stripped = unit.rstrip(":").strip()
        if len(stripped) < 60 and (unit.endswith(":") or not REQUIREMENT_CUE.search(unit)):
            for pattern, section in HEADING_SECTIONS:
                if pattern.search(stripped):
                    context = section
                    break
            if not re.search(r"[:]\s*\S", unit):
                continue
        prefix = re.match(r"^(required|requirements|preferred|nice to have|bonus)\s*:\s*", unit, re.I)
        section = context
        if prefix:
            section = "preferred_qualifications" if re.match(r"pref|nice|bonus", prefix.group(1), re.I) else "required_qualifications"
            unit = unit[prefix.end():]
        if BOILERPLATE.search(unit) or len(unit) < 15:
            continue
        found = [t for t in store.technologies + store.concepts if mentions(unit, t)]
        if not found and not REQUIREMENT_CUE.search(unit):
            continue
        if section == "responsibilities":
            if re.search(r"\b(lead|mentor|ownership|own|drive)\b", unit, re.I):
                section = "leadership"
            elif re.search(r"\b(architect|system design|scalab|distributed)", unit, re.I):
                section = "architecture"
            elif re.search(r"\b(AI|ML|LLM|machine learning|agent)", unit):
                section = "ai_ml"
        importance = {"required_qualifications": "high", "preferred_qualifications": "low"}.get(section, "medium")
        raw.append(_RawRequirement(section=section, original_text=unit, normalized_requirement=unit, skills=found,
                                   importance=importance))
    return raw


def structure_job_description(job: JobInput, store: CareerStore, llm: DeepSeekClient, *, refresh: bool = False
                              ) -> tuple[JobDescription, list[str], dict]:
    """Return jd.json for this posting. Cached by content so requirement IDs stay stable."""
    path = cache_dir() / f"{jd_id(job.text)}.json"
    if path.is_file() and not refresh:
        cached = with_repeated_themes(JobDescription.model_validate_json(path.read_text(encoding="utf-8")))
        if cached.source == "deepseek" or not llm.configured:
            missing = {k: getattr(job, k) for k in ("url", "title", "company") if getattr(job, k) and not getattr(cached, k)}
            if missing:
                cached = cached.model_copy(update=missing)
                path.write_text(cached.model_dump_json(indent=2), encoding="utf-8")
            return cached, [], {}
    warnings: list[str] = []
    meta: dict = {}
    jd = None
    if llm.configured:
        try:
            raw, meta = llm.complete_json(task="structure_jd", system=prompts.STRUCTURE_SYSTEM,
                                          user=prompts.structure_user(job), schema=_RawJD, max_tokens=4000)
            jd = _finalize(raw.requirements, job, store, "deepseek", raw.title, raw.company, [])
            if not jd.requirements:
                warnings.append("DeepSeek returned no requirements that appear in the posting. Used keyword structuring.")
                jd = None
        except DeepSeekError as exc:
            logger.warning("JD structuring fell back to deterministic: %s", exc.code)
            warnings.append(f"DeepSeek structuring unavailable ({exc}). Used keyword structuring instead.")
    else:
        warnings.append("DEEPSEEK_API_KEY is not set. Used keyword structuring instead.")
    if jd is None:
        jd = _finalize(_deterministic_raw(job, store), job, store, "deterministic", job.title, job.company, [])
    if jd.dropped:
        warnings.append(f"Dropped {len(jd.dropped)} extracted requirement(s) whose wording is not in the posting.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(jd.model_dump_json(indent=2), encoding="utf-8")
    return jd, warnings, meta


def load_jd(identifier: str) -> JobDescription:
    if not re.fullmatch(r"[0-9a-f]{16}", identifier or ""):
        raise ValueError("Unknown job description id.")
    path = cache_dir() / f"{identifier}.json"
    if not path.is_file():
        raise FileNotFoundError("This job description is no longer cached. Analyze it again.")
    return with_repeated_themes(JobDescription.model_validate_json(path.read_text(encoding="utf-8")))


def analysis_from_jd(jd: JobDescription) -> JobAnalysis:
    def skills(*sections: str) -> list[str]:
        out: list[str] = []
        for req in jd.requirements:
            if req.section in sections:
                out += [s for s in req.skills if s.casefold() not in {o.casefold() for o in out}]
        return out
    must = skills("required_qualifications", "technologies", "responsibilities", "architecture", "ai_ml")
    nice = [s for s in skills("preferred_qualifications", "domain", "leadership") if s.casefold() not in {m.casefold() for m in must}]
    themes = Counter(t for r in jd.requirements for t in r.themes)
    return JobAnalysis(target_role=jd.title, company=jd.company, must_have=must[:16], nice_to_have=nice[:12],
                       themes=[t for t, _ in themes.most_common(6)], source=jd.source)
