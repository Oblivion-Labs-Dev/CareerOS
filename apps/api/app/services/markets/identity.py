"""Company identity: one record per employer however its name is spelled.

The seed writes names like "Amazon / AWS", "Project Kuiper / Amazon", "Bill.com",
"AT&T" and "Convoy alumni/startup ecosystem". The first segment is the
employer; later segments are aliases unless another tracked company already
owns that name (then it is the parent, e.g. Kuiper's "Amazon"), or they only
describe an ecosystem.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_LEGAL_SUFFIX = re.compile(
    r"\b(incorporated|inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|plc|gmbh|holdings|group)\b\.?",
    re.I,
)
_ECOSYSTEM = re.compile(r"\b(ecosystem|alumni)\b", re.I)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def clean_name(name: str) -> str:
    """Lowercase words with legal suffixes and punctuation removed: 'AT&T Inc.' -> 'at and t'."""
    text = _ascii(name or "").lower().replace("&", " and ")
    text = _LEGAL_SUFFIX.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_key(name: str) -> str:
    """Spacing- and punctuation-insensitive identity key: 'Open AI' == 'OpenAI' == 'openai, inc.'."""
    return clean_name(name).replace(" ", "")


def slugify(name: str) -> str:
    return clean_name(name).replace(" ", "-") or "company"


def split_name(raw: str) -> tuple[str, list[str]]:
    """('Amazon / AWS') -> ('Amazon', ['AWS'])."""
    parts = [p.strip() for p in re.split(r"\s+/\s+|/(?=\s*[A-Z])", raw or "") if p.strip()]
    if not parts:
        return (raw or "").strip(), []
    return parts[0], parts[1:]


def is_ecosystem(raw: str) -> bool:
    return bool(_ECOSYSTEM.search(raw or ""))


def build_alias_keys(primary: str, related: Iterable[str], taken_primaries: set[str]) -> list[str]:
    """Identity keys this company answers to, excluding other companies' primary names."""
    keys = [name_key(primary)]
    for name in related:
        if is_ecosystem(name):
            continue
        key = name_key(name)
        if key and key not in keys and key not in taken_primaries:
            keys.append(key)
    return [k for k in keys if k]


class CompanyIndex:
    """Map an arbitrary employer string (a job's companyName) to a company id.

    An alias claimed by two companies maps to neither: a wrong attribution is
    worse than none.
    """

    def __init__(self, companies: Iterable[dict]) -> None:
        owners: dict[str, set[str]] = {}
        for company in companies:
            for key in company.get("aliasKeys") or [name_key(company.get("name", ""))]:
                owners.setdefault(key, set()).add(company["id"])
        self._index = {key: next(iter(ids)) for key, ids in owners.items() if len(ids) == 1}

    def resolve(self, employer: str) -> str | None:
        key = name_key(employer)
        if not key:
            return None
        if key in self._index:
            return self._index[key]
        # Legal suffixes are already gone; strip trailing descriptors only
        # ("Amazon Web Services", "Zillow Group", "Expedia Careers"). A bare
        # prefix match would send "Apple Leisure Group" to Apple.
        words = clean_name(employer).split()
        if len(words) > 2 and " ".join(words[-2:]) in _DESCRIPTOR_PAIRS:
            words = words[:-2]
            if "".join(words) in self._index:
                return self._index["".join(words)]
        while len(words) > 1 and words[-1] in _DESCRIPTORS:
            words.pop()
            if "".join(words) in self._index:
                return self._index["".join(words)]
        return None


_DESCRIPTORS = {
    "careers", "jobs", "usa", "us", "america", "international", "global",
    "technologies", "technology", "labs", "services", "solutions",
}
_DESCRIPTOR_PAIRS = {"web services", "north america", "united states"}
