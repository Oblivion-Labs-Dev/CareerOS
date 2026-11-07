"""Profile match: score jobs against an LLM-written resume profile, with plain code.

role_shape_match.py compares raw resume tokens with raw posting tokens. That
punishes the candidate for every generic word a posting uses and gives no credit
for synonyms, so jobs that recruiters actually called back on scored around 35.

Here the expensive reading of the resume happens once: an LLM pass turned the
resume into ``resume_match_profile.json`` (which families and levels fit, which
skills the candidate has and how strongly, with synonym patterns, including
common skills the candidate lacks so a gap registers). Each job is then scored
by looking only for those known skills, so generic words are ignored and there
is no per-job model cost.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .role_shape_match import (_MUST_MARKERS, _NICE_MARKERS, _RESP_MARKERS, detect_role_family,
                               detect_seniority)

PROFILE_PATH = Path(__file__).with_name("resume_match_profile.json")
#: Points at your own profile file instead of the bundled one.
PROFILE_ENV = "CAREEROS_MATCH_PROFILE"
MATCH_METHOD = "profile"

#: Where in a posting a skill is mentioned decides how much it counts.
SECTION_WEIGHT = {"must": 1.0, "responsibilities": 0.6, "rest": 0.6, "preferred": 0.3}
#: Exponents for the multiplicative gates. Family and level gate the score, so
#: generic skill overlap cannot rescue a wrong-family or wrong-level role, which
#: is how an LLM reads a posting too.
FAMILY_EXP, SENIORITY_EXP = 0.8, 0.7
#: When every skill named in the title is one the candidate lacks (Salesforce
#: Engineer, Android Engineer), family fit is scaled by this.
TITLE_GAP_FACTOR = 0.5
#: Coverage used when a posting names none of the known skills.
NEUTRAL_COVERAGE = 0.6
#: Generic skills (APIs, "scalable", Docker) appear in nearly every posting, so
#: they say little about fit. They count at this fraction of a specific skill.
GENERIC_WEIGHT = 0.3
#: An unknown tech name in the must-have section counts as a gap of this weight,
#: scored as "have" UNKNOWN_HAVE, with at most MAX_UNKNOWN of them per posting.
UNKNOWN_WEIGHT, UNKNOWN_HAVE, MAX_UNKNOWN = 0.8, 0.1, 3

#: Embedded / hardware / defense-systems roles. role_shape_match has no such
#: family; it is detected here so the live role-shape scorer is unchanged.
EMBEDDED_CUES = {
    "title": (r"embedded", r"firmware", r"hardware", r"\bfpga\b", r"\basic\b", r"avionics",
              r"airborne", r"flight software", r"\bdsp\b", r"\brf\b", r"silicon",
              r"electrical engineer", r"\bbsp\b", r"device driver", r"weapons?"),
    "body": (r"embedded", r"firmware", r"\brtos\b", r"microcontroller", r"\bfpga\b", r"verilog",
             r"\bvhdl\b", r"device drivers?", r"bare.metal", r"\bspi\b|\bi2c\b|\buart\b",
             r"oscilloscope", r"avionics", r"\bdo-178", r"spacecraft|satellite",
             r"missile|munitions|warfighter|weapon systems?", r"board bring.up",
             r"signal processing", r"yocto|embedded linux",
             # Defense-systems work: on-site, classified programs.
             r"\bdod\b|department of defense|department of war", r"\bscif\b|classified",
             r"national security|intelligence community", r"mission.critical systems for"),
}

#: Capitalised words that look like tech names but are not tools.
_NOT_TECH = frozenset("""
bs ms ba phd mba us usa eu uk eeo ada pto hr it ai ml ui ux qa cs ce ee gpa ceo cto vp
api apis sdk sdks saas paas iaas b2b b2c kpi kpis okr okrs roi faq etc nyc sf la
remote hybrid senior staff junior lead degree bachelor master masters engineering
computer science strong experience knowledge ability proven excellent we you our the
and or with in of to for a an years year plus bonus required preferred tdd oop mvc
json xml yaml html http https tcp ip dns ssl tls cli ide git sre devops agile scrum jira
solid dry crud etl elt soc gdpr hipaa pci sox iso nist owasp unix posix ascii utf
""".split())
_TECH_TOKEN = re.compile(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z]+|[A-Z]{3,6}|[A-Z][a-z]{2,}(?:\.js|DB|QL))\b")
_TECH_CONTEXT = re.compile(r"experience (?:with|in|using)|proficien\w* (?:with|in)|expertise in|"
                           r"knowledge of|hands.on|familiarity with|working with|fluency in", re.I)

_SOFT = re.compile(r"\bplus\b|preferred|bonus|nice to have|advantage|desirable|ideally|a benefit", re.I)
_LANG_REQ = re.compile(r"fluen(?:t|cy)|native|proficien|business.level|bilingual|\bspeak|"
                       r"written and (?:spoken|verbal)|language", re.I)

#: "5+ years of experience", not "15 years in a row on the Inc. 5000 list".
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|to)\s*\d{1,2}\s*)?\+?\s*years?"
                    r"(?=[^.\n]{0,60}(?:experience|professional|industry|engineering|software|"
                    r"develop|building|working|hands.on))", re.I)
#: "Ability to obtain a clearance" is a hurdle, not a hard stop like an active one.
_OBTAIN = re.compile(r"(?:ability|able|eligib\w*|willing\w*) (?:to )?(?:obtain|get|be granted|for)|"
                     r"eligible for|obtainable", re.I)
#: Lines about the employer's history, not the candidate ("over 20 years of experience delivering").
_COMPANY_YEARS = re.compile(r"\b(?:we|our|firm|company|founded|serving|delivering|history|in a row)\b", re.I)
#: Must-have years of a tool at or below this "have" score multiply the score by HARD_GAP_FACTOR.
HARD_GAP_HAVE, HARD_GAP_FACTOR = 0.1, 0.6
#: Titles that read as student or early-career roles, which detect_seniority leaves at mid level.
_STUDENT = re.compile(r"\bstudent\b|\bco-?op\b|\bapprentice|\bpart.time\b|\bcampus\b|university grad|new (?:college )?grad|early career|\bintern(?:ship)?\b", re.I)
_LI_TAG = re.compile(r"<\s*li\b[^>]*>", re.I)
_BLOCK_TAG = re.compile(r"<\s*(?:br|/?p|/li|/?ul|/?ol|/?h\d|/?div|/?tr)\b[^>]*>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")


def _to_lines(description: str) -> str:
    """Turn one-line HTML postings into plain lines, so sections and bullets are seen."""
    if "<" not in description:
        return description
    text = html.unescape(_ANY_TAG.sub(" ", _BLOCK_TAG.sub("\n", _LI_TAG.sub("\n- ", description))))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


@dataclass(frozen=True)
class Profile:
    family_fit: dict[str, float]
    seniority_fit: dict[int, float]
    skills: dict[str, tuple[re.Pattern[str], float]]
    domains: dict[str, re.Pattern[str]]
    years_over: int
    years_penalty: float
    clearance: re.Pattern[str]
    clearance_penalty: float
    generic: frozenset[str] = frozenset()
    cap: float = 0.15
    years_cap: int = 12
    language: re.Pattern[str] | None = None


def load_profile(path: Path = PROFILE_PATH) -> Profile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    pen = raw["penalties"]
    return Profile(
        family_fit={k: float(v) for k, v in raw["family_fit"].items()},
        seniority_fit={int(k): float(v) for k, v in raw["seniority_fit"].items()},
        skills={k: (re.compile(v["re"], re.I), float(v["have"])) for k, v in raw["skills"].items()},
        domains={k: re.compile(v, re.I) for k, v in raw["domains"].items()},
        years_over=int(pen["years_over"]),
        years_penalty=float(pen["years_penalty"]),
        clearance=re.compile(pen["clearance_re"], re.I),
        clearance_penalty=float(pen["clearance_penalty"]),
        generic=frozenset(k for k, v in raw["skills"].items() if v.get("generic")),
        cap=float(pen.get("cap", 15)) / 100,
        years_cap=int(pen.get("years_cap", 12)),
        language=re.compile(rf"\b(?:{pen['language_re']})\b", re.I) if pen.get("language_re") else None,
    )


@lru_cache(maxsize=1)
def default_profile() -> Profile:
    override = os.environ.get(PROFILE_ENV, "").strip()
    if override and not Path(override).is_file():
        # A typo here would silently score every job against the wrong resume.
        raise FileNotFoundError(f"{PROFILE_ENV}={override} does not exist")
    return load_profile(Path(override) if override else PROFILE_PATH)


def _embedded_score(title: str, body: str) -> float:
    t, b = title.lower(), body.lower()
    title_hits = sum(1 for c in EMBEDDED_CUES["title"] if re.search(c, t))
    body_hits = sum(1 for c in EMBEDDED_CUES["body"] if re.search(c, b))
    # One body cue alone ("embedded" in passing) is not enough to call the family.
    body_signal = 1.0 - (0.72 ** body_hits) if body_hits >= 2 else 0.0
    return title_hits * 3.0 + body_signal * 1.5


def _family_fit(title: str, body: str, profile: Profile) -> tuple[str, float]:
    _family, scores = detect_role_family(title, body)
    scores = {**scores, "embedded": _embedded_score(title, body)}
    best = max(scores, key=lambda k: scores[k])
    family = best if scores[best] > 0.5 else ""
    unknown = profile.family_fit.get("", 0.75)
    if not family:
        return "", unknown
    # Blend the families the posting signals, so "ML platform" or "security
    # backend" lands between its parts instead of snapping to one of them.
    total = sum(s for s in scores.values() if s > 0)
    fit = sum(profile.family_fit.get(f, unknown) * s for f, s in scores.items() if s > 0) / total
    # The headline family still matters most.
    return family, 0.6 * profile.family_fit.get(family, unknown) + 0.4 * fit


def unknown_must_tech(must: str, profile: Profile) -> list[str]:
    """Tech-looking names in must-have lines that no profile skill recognises.

    "Experience with DAML" or "expertise in ForgeRock" is a requirement the
    resume does not show; ignoring it read as a match. Only lines that ask for
    experience are scanned, so company and product names in prose do not count.
    """
    found: list[str] = []
    for line in must.splitlines():
        if not _TECH_CONTEXT.search(line):
            continue
        for tok in _TECH_TOKEN.findall(line):
            low = tok.lower()
            if low in _NOT_TECH or low in found:
                continue
            if profile.language and profile.language.fullmatch(tok):
                continue
            if any(p.search(tok) for p, _h in profile.skills.values()):
                continue
            found.append(low)
    return found[:MAX_UNKNOWN]


def _coverage(sections: dict[str, str], profile: Profile) -> tuple[float, list[str], list[str]]:
    weight_by_skill: dict[str, float] = {}
    for name, text in sections.items():
        if not text:
            continue
        w = SECTION_WEIGHT[name]
        for skill, (pattern, _have) in profile.skills.items():
            ws = w * (GENERIC_WEIGHT if skill in profile.generic else 1.0)
            if ws > weight_by_skill.get(skill, 0.0) and pattern.search(text):
                weight_by_skill[skill] = ws
    have_of = {s: profile.skills[s][1] for s in weight_by_skill}
    for tok in unknown_must_tech(sections.get("must", ""), profile):
        weight_by_skill[f"?{tok}"] = UNKNOWN_WEIGHT
        have_of[f"?{tok}"] = UNKNOWN_HAVE
    if not weight_by_skill:
        return NEUTRAL_COVERAGE, [], []
    num = sum(w * have_of[s] for s, w in weight_by_skill.items())
    den = sum(weight_by_skill.values())
    have = sorted((s for s in weight_by_skill if have_of[s] >= 0.6),
                  key=lambda s: -weight_by_skill[s])
    gaps = sorted((s for s in weight_by_skill if have_of[s] < 0.4),
                  key=lambda s: -weight_by_skill[s])
    # Saturate the denominator a little: one strong match out of one mention is
    # weaker evidence than eight out of nine.
    confidence = 1.0 - math.exp(-den / 2.0)
    raw = num / den
    return NEUTRAL_COVERAGE + (raw - NEUTRAL_COVERAGE) * confidence, have, gaps


def _is_heading(line: str) -> bool:
    # role_shape_match treats any short line with "bonus" or "plus" as a heading,
    # so "Python (Django is a bonus)." moved every later must-have into
    # "preferred". A heading here is short and reads like a label, not a sentence.
    return (len(line) < 60 and not line.endswith(".") and line[0] not in "-*•·"
            and (line.endswith(":") or len(line.split()) <= 6))


def _sections(description: str) -> dict[str, str]:
    buckets: dict[str, list[str]] = {"must": [], "preferred": [], "responsibilities": [], "rest": []}
    current = "rest"
    for line in description.splitlines():
        line = line.strip()
        if not line:
            continue
        if _is_heading(line):
            for name, marker in (("preferred", _NICE_MARKERS), ("must", _MUST_MARKERS),
                                 ("responsibilities", _RESP_MARKERS)):
                if marker.search(line):
                    current = name
                    buckets[current].append(line)
                    break
            else:
                buckets[current].append(line)
            continue
        buckets[current].append(line)
    return {k: "\n".join(v) for k, v in buckets.items()}


def _years_required(text: str) -> int | None:
    found = [int(m.group(1)) for line in text.splitlines() if not _COMPANY_YEARS.search(line)
             for m in _YEARS.finditer(line) if 1 <= int(m.group(1)) <= 25]
    return min(found) if found else None


def hard_skill_gap(must: str, profile: Profile) -> bool:
    """A must-have that asks for years of a tool the candidate does not have.

    "5+ years with ForgeRock" is a near-disqualifier in a way that one gap in a
    long list is not.
    """
    lacked = [p for p, h in profile.skills.values() if h <= HARD_GAP_HAVE]
    for line in must.splitlines():
        if _SOFT.search(line) or not _YEARS.search(line):
            continue
        if any(p.search(line) for p in lacked) or unknown_must_tech(line, profile):
            return True
    return False


def hard_blockers(title: str, sections: dict[str, str], body: str, years: int | None,
                  profile: Profile) -> list[str]:
    """Requirements that rule the candidate out whatever the skill overlap.

    An LLM reviewer scores these near zero, so they cap the score rather than
    nudge it. Lines that call the requirement a plus, and the preferred
    section, do not count.
    """
    blockers: list[str] = []
    hard_text = "\n".join(sections.get(k, "") for k in ("must", "responsibilities", "rest")) or body
    for line in [title, *hard_text.splitlines()]:
        if _SOFT.search(line):
            continue
        if ("clearance" not in blockers and profile.clearance.search(line)
                and not _OBTAIN.search(line)):
            blockers.append("clearance")
        if (profile.language and "language" not in blockers and _LANG_REQ.search(line)
                and profile.language.search(line)):
            blockers.append("language")
    if years is not None and years >= profile.years_cap:
        blockers.append("years")
    return blockers


def profile_components(title: str, description: str, profile: Profile | None = None) -> dict[str, Any]:
    profile = profile or default_profile()
    body = _to_lines(description or "")
    family, fam = _family_fit(title, body, profile)
    title_skills = [h for p_, h in profile.skills.values() if p_.search(title)]
    title_gap = bool(title_skills) and all(h < 0.4 for h in title_skills)
    if title_gap:
        fam *= TITLE_GAP_FACTOR
    level = 0 if _STUDENT.search(title) else detect_seniority(title)
    sen = profile.seniority_fit.get(level, 0.7)
    sections = _sections(body) if body else {}
    cov, have, gaps = _coverage(sections, profile) if body else (NEUTRAL_COVERAGE, [], [])
    domains = [d for d, p in profile.domains.items() if p.search(f"{title}\n{body}")]
    dom = min(1.0, 0.5 + 0.25 * len(domains))
    penalty = 0.0
    years = _years_required(sections.get("must", "") or body) if body else None
    if years is not None and years > profile.years_over:
        penalty += profile.years_penalty
    blockers = hard_blockers(title, sections, body, years, profile) if body else []
    if body and "clearance" not in blockers and profile.clearance.search(body):
        penalty += profile.clearance_penalty  # a plus, or "ability to obtain"
    score = (fam ** FAMILY_EXP) * (sen ** SENIORITY_EXP) * (0.3 + 0.7 * cov) \
        * (0.9 + 0.1 * dom) - penalty
    skill_gap = bool(body) and hard_skill_gap(sections.get("must", ""), profile)
    if skill_gap:
        score *= HARD_GAP_FACTOR
    score = max(0.0, min(1.0, score))
    if blockers:
        score = min(score, profile.cap)
    return {
        "score": round(score * 100, 1), "blockers": blockers, "hardSkillGap": skill_gap,
        "family": family, "familyFit": round(fam, 3), "seniority": level,
        "seniorityFit": sen, "coverage": round(cov, 3), "domains": domains,
        "have": have[:6], "gaps": gaps[:4], "yearsRequired": years,
        "penalty": round(penalty, 3), "titleGap": title_gap, "hasText": bool(body),
    }


def profile_match(job: dict[str, Any], profile: Profile | None = None) -> dict[str, Any]:
    parts = profile_components(str(job.get("title") or ""), str(job.get("description") or ""), profile)
    reason = f"{parts['family'] or 'unknown'} role, level {parts['seniority']}"
    if parts["have"]:
        reason += "; matches " + ", ".join(parts["have"][:4])
    if parts["gaps"]:
        reason += "; gaps " + ", ".join(parts["gaps"][:3])
    if parts["blockers"]:
        reason += "; blocked by " + ", ".join(parts["blockers"])
    elif parts["penalty"]:
        reason += "; penalised for years/clearance"
    if not parts["hasText"]:
        reason += "; title only"
    return {"matchScore": parts["score"], "matchReason": reason,
            "matchMethod": MATCH_METHOD, "matchComponents": parts}
