"""Stage 8: check every generated claim against career.json. A failure here blocks preview approval, download and apply."""
from __future__ import annotations

import re

from app.services.career_compiler.lexicon import SCALE_WORDS, TITLES, mentions_tech, technologies
from app.services.career_compiler.models import Bullet, ResumeDocument, ValidationIssue
from app.services.career_compiler.store import EXISTENCE_ONLY, CareerStore, mentions

#: A number with optional currency, thousands separators, magnitude suffix and percent sign.
QUANTITY = re.compile(r"(?<![A-Za-z0-9.])\$?(\d+(?:,\d{3})+|\d+(?:\.\d+)?)"
                      r"(?:\s?(K|M|B|k)(?![A-Za-z])|\s(thousand|million|billion)\b)?\+?(\s?%)?")
MAGNITUDE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}
YEARS_OF_EXPERIENCE = re.compile(r"(\d+)\s*\+?\s*(?:years?|yrs)\b(?=[^.;]{0,40}\bexperience\b)|(\d+)\+\s*(?:years?|yrs)\b", re.I)
CALENDAR_YEAR = re.compile(r"(?<![\d.])(19[89]\d|20[0-4]\d)(?![\d%])")
#: Sanity caps only. The template's measured line budget is the real length limit.
MAX_CHARS = 360
MAX_SUMMARY_CHARS = 520
#: A verb in the bullet needs one of these whole-word forms in the cited claims or the project's ownership/summary.
OWNERSHIP_TERMS = {
    "led": r"\b(led|lead|leading)\b", "owned": r"\b(own|owned|owner|ownership)\b", "architected": r"\barchitected\b",
    "mentored": r"\bmentor(ed|ing|s)?\b", "managed": r"\bmanag(ed|ing|er)\b", "drove": r"\b(drove|drive|driving)\b",
}


def _canonical(match: re.Match[str]) -> str:
    digits, short, word, percent = match.groups()
    value = float(digits.replace(",", ""))
    scale = (short or word or "").casefold()
    value *= MAGNITUDE.get(scale, 1)
    text = str(int(value)) if value == int(value) else f"{value:g}"
    return text + ("%" if percent else "")


def numbers(text: str) -> set[str]:
    """Every quantity in `text`, magnitude applied: "100K+" and "100,000" are both 100000, "1M" is 1000000."""
    return {_canonical(m) for m in QUANTITY.finditer(text)}


def _phrase(text: str, match: re.Match[str]) -> str:
    """The quantity with the word after it, e.g. "1M TPS", for structured errors."""
    after = re.match(r"\s*[A-Za-z/]+", text[match.end():])
    return (match.group(0) + (after.group(0) if after else "")).strip()


def quantity_phrases(text: str) -> list[str]:
    return list(dict.fromkeys(_phrase(text, m) for m in QUANTITY.finditer(text)))


def _conflict_values(store: CareerStore, company: str) -> set[str]:
    values: set[str] = set()
    for conflict in store.conflicts:
        scope = str(conflict.get("id", "")).split(".")
        if company and len(scope) > 1 and scope[1] != company.casefold().split()[0]:
            continue
        for candidate in conflict.get("candidates") or []:
            values |= numbers(str(candidate))
    return values


def _years(value: str) -> tuple[int, int] | None:
    found = re.findall(r"(\d{4})", value or "")
    return (int(found[0]), int(found[-1])) if found else None


def validate_bullet(bullet: Bullet, store: CareerStore, *, allowed: set[str] | None = None,
                    summary: bool = False) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def fail(code: str, message: str, claim: str = "", allowed_evidence: list[str] | None = None) -> None:
        issues.append(ValidationIssue(bullet_id=bullet.id, code=code, message=message, claim=claim,
                                      allowed_evidence=allowed_evidence or []))

    text = bullet.text.strip()
    if not text:
        fail("empty", "The bullet has no text.")
        return issues
    if not bullet.evidence_ids:
        fail("missing_evidence", "The bullet cites no evidence.")
        return issues
    records = []
    for evidence_id in dict.fromkeys(bullet.evidence_ids):
        record = store.evidence.get(evidence_id)
        if record is None:
            fail("unknown_evidence", f"{evidence_id} does not exist in career.json.", evidence_id)
            continue
        if record.status == "needs_reconciliation":
            fail("unresolved_conflict", f"{evidence_id} needs reconciliation and cannot be cited.", evidence_id)
            continue
        if record.status not in ("supported", "supported_variant", *EXISTENCE_ONLY):
            fail("evidence_not_allowed", f"{evidence_id} has status {record.status} and is not resume evidence.", evidence_id)
            continue
        if allowed is not None and evidence_id not in allowed and not (summary and record.type == "positioning"):
            fail("evidence_not_allowed", f"{evidence_id} was not retrieved for this slot.", evidence_id, sorted(allowed))
            continue
        if not summary and record.employment_id and record.employment_id != bullet.employment_id:
            fail("wrong_company", f"{evidence_id} belongs to {record.company or 'a personal project'}, not this section.",
                 evidence_id)
            continue
        records.append(record)
    if not records:
        return issues

    job = store.employment.get(bullet.employment_id) or {}
    if not summary:
        for company in store.company_names:
            if company != job.get("company") and mentions(text, company):
                fail("wrong_company", f"The bullet names {company} inside another employer's section.", company,
                     [job.get("company", "")] if job else [])

    claims = " ".join(r.claim for r in records)
    existence_only = all(r.status in EXISTENCE_ONLY for r in records)
    projects = {r.project_id for r in records if r.project_id}
    context, ownership = claims, claims
    if not existence_only:
        for project_id in projects:
            project = store.projects[project_id]
            context += " " + " ".join((project.name, project.summary, *project.technologies, *project.ownership, *project.details))
            ownership += " " + " ".join((project.summary, *project.ownership))

    allowed_quantities = quantity_phrases(claims)
    claim_numbers = numbers(claims)
    reported: set[str] = set()
    for match in YEARS_OF_EXPERIENCE.finditer(text):
        value = match.group(1) or match.group(2)
        if value not in claim_numbers:
            reported.add(value)
            fail("unsupported_experience", f"'{match.group(0)}' is not the experience career.json records.",
                 match.group(0).strip(), [r.claim for r in records if r.type == "positioning"] or allowed_quantities)
    for match in QUANTITY.finditer(text):
        value = _canonical(match)
        if value in claim_numbers or value in reported:
            continue
        reported.add(value)
        fail("unsupported_metric", f"{_phrase(text, match)} ({value}) does not appear in the cited evidence.",
             _phrase(text, match), allowed_quantities)
    supported_numbers = numbers(" ".join(r.claim for r in records if r.status == "supported"))
    for value in sorted((numbers(text) & claim_numbers & _conflict_values(store, job.get("company", ""))) - supported_numbers):
        fail("unresolved_conflict", f"{value} is a disputed value supported only by a variant record.", value)

    span = _years(str(job.get("start") or "")), _years(str(job.get("end") or ""))
    if not summary and span[0] and span[1]:
        for year in sorted({int(y) for y in CALENDAR_YEAR.findall(text)}):
            if not span[0][0] <= year <= span[1][1]:
                fail("date_mismatch", f"{year} is outside {job.get('company')} employment ({job.get('start')} to {job.get('end')}).",
                     str(year), [f"{job.get('start')} to {job.get('end')}"])

    known = technologies(store.technologies)
    supported_tech = [t for t in known if mentions_tech(context, t)]
    for term in known:
        if mentions_tech(text, term) and not mentions_tech(context, term):
            # "AWS CDK" in the text already covers "AWS"; only report the term the evidence lacks.
            fail("unsupported_technology", f"{term} is not supported by the cited evidence or project.", term,
                 supported_tech[:12])

    roles = " ".join(str(j.get("role") or "") for j in (store.employment.values() if summary else [job]))
    for title in TITLES:
        said = re.compile(r"(?<![A-Za-z])" + re.escape(title) + r"(?![A-Za-z])")
        if said.search(text) and not said.search(roles + " " + claims):
            fail("unsupported_title", f"'{title}' is not a title or claim career.json records for this role.", title,
                 [roles.strip()] if roles.strip() else [])

    for pattern in SCALE_WORDS:
        found = re.search(pattern, text, re.I)
        if found and not re.search(pattern, context, re.I):
            fail("unsupported_scale", f"'{found.group(0)}' asserts scale the cited evidence does not state.",
                 found.group(0), [r.claim for r in records if r.type == "scale"] or allowed_quantities)

    lowered = text.casefold()
    for word, support in OWNERSHIP_TERMS.items():
        if re.search(rf"\b{word}\b", lowered) and not re.search(support, ownership.casefold()):
            fail("unsupported_ownership", f"'{word}' is not supported by the cited evidence or project ownership.", word,
                 [r.claim for r in records if r.type == "ownership"])

    if existence_only:
        for term in store.concepts:
            if mentions(text, term) and not mentions(claims, term):
                fail("sparse_detail", f"{term} adds detail that existence-only evidence does not support.", term,
                     [r.claim for r in records])

    limit = MAX_SUMMARY_CHARS if summary else MAX_CHARS
    if len(text) > limit:
        fail("too_long", f"{len(text)} characters; the limit is {limit}. Shorten by removing detail.")
    return issues


def validate_document(document: ResumeDocument, store: CareerStore,
                      allowed_by_project: dict[str, set[str]] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if document.store_digest != store.digest:
        issues.append(ValidationIssue(bullet_id="document", code="stale_store",
                                      message="career.json changed after this resume was generated. Regenerate."))
    for section in document.sections:
        job = store.employment.get(section.employment_id)
        if section.employment_id != "personal":
            if job is None:
                issues.append(ValidationIssue(bullet_id=section.employment_id, code="unknown_employment",
                                              message="Section does not match a canonical employment record."))
                continue
            for field in ("company", "role", "start", "end"):
                if str(getattr(section, field)) != str(job.get(field) or ""):
                    code = "date_mismatch" if field in ("start", "end") else "non_canonical_header"
                    issues.append(ValidationIssue(bullet_id=section.employment_id, code=code,
                                                  message=f"{field} must come from career.json.",
                                                  claim=str(getattr(section, field)),
                                                  allowed_evidence=[str(job.get(field) or "")]))
        for bullet in section.bullets:
            if bullet.employment_id != section.employment_id:
                issues.append(ValidationIssue(bullet_id=bullet.id, code="wrong_company",
                                              message="Bullet is filed under a different employer."))
            allowed = (allowed_by_project or {}).get(bullet.project_id)
            if allowed is None:
                allowed = {i for i in store.projects[bullet.project_id].evidence_ids} if bullet.project_id in store.projects else set()
            issues.extend(validate_bullet(bullet, store, allowed=allowed))
    for bullet in document.featured:
        project = store.projects.get(bullet.project_id)
        if project is None or not project.personal or bullet.name != project.name:
            issues.append(ValidationIssue(bullet_id=bullet.id, code="non_canonical_header",
                                          message="Featured project name must come from career.json."))
            continue
        issues.extend(validate_bullet(bullet, store, allowed=set(project.evidence_ids)))
    if document.summary:
        issues.extend(validate_bullet(document.summary, store, summary=True))
    return issues
