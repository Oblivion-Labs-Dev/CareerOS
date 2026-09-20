"""Read a résumé's structure, not just four regexes over the whole document.

``resume_parser.parse_resume_fields`` extracts an email, a phone number, a
years-of-experience figure, and **the first line of the document as the
candidate's name**. Nothing else. That is why a profile built by uploading a
résumé still had no employment history, no education and no dates — every one of
which an application form asks for, and all of which were then entered by hand.

This module adds the missing half: find the sections, then read the entries
inside them.

Two deliberate limits.

**It never invents.** A field it cannot read with confidence is absent from the
result rather than guessed at. Everything here ends up on a real application, so
a wrong company name or a fabricated date is worse than a blank the user fills
in themselves.

**It never overwrites.** The result is a *proposal*. ``resume_parser`` merges it
only into keys the profile has not already set, and the UI is expected to show
what changed before it is accepted. A résumé is evidence about the candidate;
the profile is the record they have approved.
"""

from __future__ import annotations

import re
from typing import Any

#: Section headings as résumés actually write them. Matched on a line of its own
#: (optionally styled with punctuation or caps), never mid-sentence — "my
#: education" inside a summary paragraph must not open the education section.
_SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "experience": re.compile(
        r"^\W*(work\s+|professional\s+|employment\s+|relevant\s+)?"
        r"(experience|history|employment)\W*$",
        re.I,
    ),
    "education": re.compile(r"^\W*education(\s+(and|&)\s+training)?\W*$", re.I),
    "skills": re.compile(r"^\W*(technical\s+)?(skills|technologies|competencies)\W*$", re.I),
    "projects": re.compile(r"^\W*(personal\s+|side\s+)?projects\W*$", re.I),
    "summary": re.compile(r"^\W*(summary|profile|objective|about)\W*$", re.I),
}

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)

#: A date range as résumés write them: "Sept 2016 - July 2017", "09/2016 –
#: 07/2017", "2012 to 2016", "Aug 2019 - Present". The separator set covers the
#: hyphen, en dash, em dash and the word "to", because all four appear in the
#: wild and a parser that handles only the hyphen silently drops the rest.
_DATE_RANGE = re.compile(
    rf"(?P<start>(?:(?:{_MONTHS})\.?\s+)?\d{{1,2}}[/-]?\d{{0,4}}|\d{{4}}|(?:{_MONTHS})\.?\s*\d{{4}})"
    r"\s*(?:[-–—]|\bto\b)\s*"
    rf"(?P<end>present|current|now|(?:(?:{_MONTHS})\.?\s+)?\d{{1,2}}[/-]?\d{{0,4}}|\d{{4}}|(?:{_MONTHS})\.?\s*\d{{4}})",
    re.I,
)

_MONTH_NUMBER = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DEGREE = re.compile(
    r"\b(ph\.?d|doctorate|m\.?b\.?a|master'?s?|m\.?s(?:c)?|m\.?eng|m\.?tech"
    r"|bachelor'?s?|b\.?s(?:c)?|b\.?e(?:ng)?|b\.?tech|b\.?a|associate'?s?)\b",
    re.I,
)

_DEGREE_CANONICAL = (
    ("phd", "Doctorate"), ("doctorate", "Doctorate"),
    ("mba", "MBA"),
    ("master", "Master's Degree"), ("ms", "Master's Degree"), ("msc", "Master's Degree"),
    ("meng", "Master's Degree"), ("mtech", "Master's Degree"),
    ("bachelor", "Bachelor's Degree"), ("bs", "Bachelor's Degree"),
    ("bsc", "Bachelor's Degree"), ("be", "Bachelor's Degree"),
    ("beng", "Bachelor's Degree"), ("btech", "Bachelor's Degree"),
    ("ba", "Bachelor's Degree"),
    ("associate", "Associate Degree"),
)

_SCHOOL_HINT = re.compile(r"\b(university|college|institute|school|academy|polytechnic)\b", re.I)

#: Lines that are decoration or contact details, never an entry.
_NOISE = re.compile(
    r"^\W*$|^\W*(page\s+\d+|curriculum vitae|r[ée]sum[ée])\W*$"
    r"|^[\W_]{3,}$"
    r"|^\s*(https?://|www\.|linkedin\.com|github\.com)",
    re.I,
)


def _normalise_month_year(value: str) -> str:
    """"Sept 2016" / "09/2016" / "2016" -> "MM/YYYY" or "YYYY".

    Returns "" rather than a guess when the text does not clearly carry a date,
    since a wrong employment date on an application is a factual error.
    """
    raw = (value or "").strip().lower()
    if not raw or raw in ("present", "current", "now"):
        return "Present" if raw else ""

    slash = re.fullmatch(r"(\d{1,2})[/-](\d{4})", raw)
    if slash:
        return f"{int(slash.group(1)):02d}/{slash.group(2)}"

    named = re.fullmatch(rf"({_MONTHS})\.?\s*,?\s*(\d{{4}})", raw)
    if named:
        month = _MONTH_NUMBER.get(named.group(1)[:3], 0)
        return f"{month:02d}/{named.group(2)}" if month else named.group(2)

    year = re.fullmatch(r"(19|20)\d{2}", raw)
    if year:
        return raw
    return ""


def split_sections(text: str) -> dict[str, list[str]]:
    """The résumé's lines, grouped under the heading that introduced them.

    Everything before the first recognised heading lands in ``header``, which is
    where the name and contact details live.
    """
    sections: dict[str, list[str]] = {"header": []}
    current = "header"

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matched = next(
            (name for name, pattern in _SECTION_PATTERNS.items() if pattern.match(line)),
            None,
        )
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    return sections


def _canonical_degree(line: str) -> str:
    match = _DEGREE.search(line)
    if not match:
        return ""
    token = re.sub(r"[^a-z]", "", match.group(1).lower())
    for prefix, canonical in _DEGREE_CANONICAL:
        if token == prefix:
            return canonical
    return ""


def parse_education(lines: list[str]) -> list[dict[str, Any]]:
    """Education entries, most recent first as résumés list them.

    An entry is anchored on the line naming a school, because that is the one
    part essentially every résumé states explicitly; the degree, field and dates
    are then read from that line and the two around it.
    """
    entries: list[dict[str, Any]] = []

    for index, line in enumerate(lines):
        if _NOISE.match(line) or not _SCHOOL_HINT.search(line):
            continue

        # The entry's own line, plus continuation lines beneath it — but never
        # into the next entry. A fixed three-line window bled the following
        # school's field of study onto this one, which is a factual error on an
        # application rather than a cosmetic one.
        window_lines = [line]
        for following in lines[index + 1 : index + 3]:
            if _SCHOOL_HINT.search(following) or _NOISE.match(following):
                break
            window_lines.append(following)
        window = " | ".join(window_lines)

        # The school is one field on a line that often also carries the degree
        # and the dates, separated by any of several punctuation styles. Split
        # on all of them and keep the fragment that actually names a school,
        # rather than assuming it comes first.
        fragments = [
            fragment.strip()
            for fragment in re.split(r"\s{2,}|\s*[|,]\s*|\s+[-–—]\s+", line)
            if fragment.strip()
        ]
        school = next(
            (fragment for fragment in fragments if _SCHOOL_HINT.search(fragment)),
            fragments[0] if fragments else line,
        )
        entry: dict[str, Any] = {"school": school}

        degree = _canonical_degree(window)
        if degree:
            entry["degree"] = degree

        # Ends at punctuation, a run of spaces, or the start of a date - a field
        # of study is never followed directly by a digit, and without that last
        # case "Computer Science    2017 - 2019" swallowed the years.
        # The *last* "in/of X", not the first. "Master of Science in Computer
        # Science" has two, and the first one yields "Science in Computer
        # Science" — the degree's own name swallowing the field of study.
        field_matches = list(
            re.finditer(
                r"\b(?:in|of)\s+([A-Z][A-Za-z&\s]{2,40}?)"
                r"(?=\s*(?:[|,.]|\s{2,}|\s+(?:19|20)\d{2}|$))",
                window,
            )
        )
        if field_matches:
            discipline = field_matches[-1].group(1).strip()
            # "Master of Science in Computer Science" matches once, from "of",
            # and the capture swallows the "in" clause — finditer cannot return
            # the inner match because it overlaps. The field of study is what
            # follows the last "in".
            tail = re.split(r"\s+\bin\b\s+", discipline)
            entry["discipline"] = tail[-1].strip()

        dates = _DATE_RANGE.search(window)
        if dates:
            start = _normalise_month_year(dates.group("start"))
            end = _normalise_month_year(dates.group("end"))
            if start:
                entry["startDate"] = start
            if end:
                entry["endDate"] = end
        else:
            lone_year = re.search(r"\b(19|20)\d{2}\b", window)
            if lone_year:
                entry["endDate"] = lone_year.group(0)

        entries.append(entry)

    return entries


def parse_experience(lines: list[str]) -> list[dict[str, Any]]:
    """Employment entries.

    Anchored on a line carrying a date range, because that is what reliably
    separates one role from the next — bullet points, titles and company names
    are all styled too variably to key on. The company and title are then read
    from that line and the one above it.
    """
    entries: list[dict[str, Any]] = []

    for index, line in enumerate(lines):
        if _NOISE.match(line):
            continue
        dates = _DATE_RANGE.search(line)
        if not dates:
            continue

        start = _normalise_month_year(dates.group("start"))
        end = _normalise_month_year(dates.group("end"))

        # Strip the date out; what remains on the line is company and/or title.
        remainder = _DATE_RANGE.sub("", line).strip(" |,-–—\t")
        parts = [p.strip() for p in re.split(r"\s{2,}|\s*[|·•]\s*|\s+[-–—]\s+", remainder) if p.strip()]

        # Only look upward when the date line did not already carry both the
        # company and the title. Otherwise the line above is a bullet belonging
        # to the *previous* role, and prepending it made "- Built things" the
        # employer on the next one.
        if len(parts) < 2:
            previous = lines[index - 1].strip() if index > 0 else ""
            is_bullet = bool(re.match(r"^[-–—•*·]\s+", previous))
            if (
                previous
                and not is_bullet
                and not _NOISE.match(previous)
                and not _DATE_RANGE.search(previous)
                and len(previous) < 90
            ):
                parts = [
                    p.strip() for p in re.split(r"\s{2,}|\s*[|·•]\s*", previous) if p.strip()
                ] + parts

        entry: dict[str, Any] = {}
        if parts:
            entry["company"] = parts[0]
        if len(parts) > 1:
            entry["title"] = parts[1]
        if start:
            entry["startDate"] = start
        if end and end != "Present":
            entry["endDate"] = end
        elif end == "Present":
            entry["endDate"] = ""
            entry["currentlyEmployed"] = True

        if entry.get("company"):
            entries.append(entry)

    return entries


def parse_skills(lines: list[str]) -> list[str]:
    """Skills, split on the separators résumés actually use."""
    skills: list[str] = []
    for line in lines:
        if _NOISE.match(line):
            continue
        body = re.sub(r"^[A-Za-z /&]{3,30}:\s*", "", line)  # drop "Languages:" style prefixes
        for token in re.split(r"[,;|•·]|\s{3,}", body):
            cleaned = token.strip(" .\t")
            if 1 < len(cleaned) <= 40:
                skills.append(cleaned)
    seen: set[str] = set()
    unique = []
    for skill in skills:
        key = skill.lower()
        if key not in seen:
            seen.add(key)
            unique.append(skill)
    return unique


def parse_structure(text: str) -> dict[str, Any]:
    """Everything readable from the résumé, as a proposal to be reviewed.

    Keys are omitted entirely when nothing could be read, so a caller can tell
    "found none" from "found an empty one" — the difference between leaving the
    profile alone and wiping it.
    """
    sections = split_sections(text)
    result: dict[str, Any] = {}

    education = parse_education(sections.get("education", []))
    if education:
        result["education"] = education

    experience = parse_experience(sections.get("experience", []))
    if experience:
        result["workExperience"] = experience

    skills = parse_skills(sections.get("skills", []))
    if skills:
        result["skills"] = skills

    return result
