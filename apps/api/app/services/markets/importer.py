"""Seed importer: a spreadsheet of companies -> the company registry.

Idempotent: a company is matched by its identity key (or an unambiguous alias),
seed-owned fields are rewritten only when they changed, and runtime fields
(detected career source, health, scan history) are never touched. Re-running
the same file reports every company as unchanged and writes nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import now_iso
from app.services.markets import registry
from app.services.markets.config import Market, MarketSeed, resolve_seed_path
from app.services.markets.geo import areas_from_text
from app.services.markets.identity import build_alias_keys, is_ecosystem, name_key, slugify, split_name
from app.services.markets.xlsx import read_workbook, table


class SeedImportError(ValueError):
    pass


@dataclass
class ImportReport:
    marketId: str
    seedId: str
    file: str
    importedAt: str
    rows: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    companies: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _int(value: Any) -> int | None:
    match = re.search(r"-?\d+", str(value or ""))
    return int(match.group()) if match else None


def _tier(raw: str) -> tuple[int | None, str]:
    match = re.search(r"tier\s*(\d)", raw or "", re.I)
    number = int(match.group(1)) if match else None
    label = re.split(r"\s+[—-]\s+", raw or "", maxsplit=1)
    return number, (label[1].strip() if len(label) > 1 else "")


def _zone(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.lower().startswith("peripheral"):
        return "P"
    match = re.match(r"([A-D])\b", text)
    return match.group(1) if match else None


def h1b_strength(score: int | None, activity: str, evidence: str) -> str:
    """Strong / moderate / weak, from the seed's company-level evidence.

    "Strong" needs a verified recent local filing: a historical or likely
    sponsor is at most moderate however high its score.
    """
    verified = "verified" in (evidence or "").lower()
    act = (activity or "").lower()
    if score is not None:
        level = "strong" if score >= 9 else "moderate" if score >= 7 else "weak"
    elif act in ("very high", "high"):
        level = "strong"
    elif act.startswith("medium"):
        level = "moderate"
    else:
        level = "weak"
    if level == "strong" and not verified:
        level = "moderate"
    return level


def _url(value: str) -> str:
    text = (value or "").strip()
    return text if re.match(r"https?://", text, re.I) else ""


def _seed_fields(row: dict[str, str], market: Market, seed: MarketSeed) -> dict[str, Any]:
    tier, tier_label = _tier(row.get("Tier", ""))
    presence = row.get("Local Presence", "")
    score = _int(row.get("H-1B Strength /10"))
    activity = row.get("H-1B Activity", "")
    evidence = row.get("H-1B Evidence", "")
    return {
        "membership": {
            "tier": tier,
            "tierLabel": tier_label,
            "applicationPriority": _int(row.get("Apply #")),
            "category": row.get("Category", ""),
            "localPresence": presence,
            "areas": areas_from_text(presence, market),
            "remoteInState": bool(re.search(r"remote", presence, re.I)),
            "zone": _zone(row.get("Commute Zone from Auburn", "")),
            "zoneLabel": row.get("Commute Zone from Auburn", ""),
            "fitScore": _int(row.get("Fit /10")),
            "priorityScore": _int(row.get("Priority Score")),
            "whyFits": row.get("Why It Fits", ""),
            "notes": row.get("Notes", ""),
            "applicationStatus": row.get("Status", ""),
            "dateApplied": row.get("Date Applied", ""),
        },
        "h1b": {
            "strength": h1b_strength(score, activity, evidence),
            "score": score,
            "activity": activity,
            "localLcaCount": _int(row.get("Recent Local LCA Count*")),
            "lcaArea": row.get("LCA Area", ""),
            "evidence": evidence,
            "scope": "company",
            "source": seed.h1b_source or seed.id,
        },
        "careerSeed": {
            "url": _url(row.get("Career Site", "")),
            "parseability": row.get("Career Parseability", ""),
            "verification": row.get("Verification / Source", ""),
        },
    }


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _reference_links(rows: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    """('careers' | 'h1b', company words, url) from the reference sheet."""
    links = []
    for row in rows:
        values = list(row.values())
        label, url = (values[0] if values else ""), _url(values[1] if len(values) > 1 else "")
        if not url:
            continue
        match = re.match(r"(.+?)\s+(?:(\w+)\s+)?careers$", label, re.I)
        if match:
            links.append(("careers", label, url))
        elif re.search(r"h-?1b evidence$", label, re.I):
            links.append(("h1b", label, url))
    return links


def import_seed(
    db: Session,
    market: Market,
    *,
    seed: MarketSeed | None = None,
    path: str | Path | None = None,
) -> ImportReport:
    seed = seed or (market.seeds[0] if market.seeds else None)
    if seed is None:
        raise SeedImportError(f"Market {market.id} has no seed configured")
    source_path = Path(path) if path else resolve_seed_path(seed)
    if not source_path or not source_path.is_file():
        raise SeedImportError(f"Seed file {seed.file} not found")

    sheets = read_workbook(source_path)
    if seed.sheet not in sheets:
        raise SeedImportError(f"Seed file has no sheet named '{seed.sheet}'")
    rows = table(sheets[seed.sheet])
    reference = table(sheets.get(seed.reference_sheet, [])) if seed.reference_sheet else []
    imported_at = now_iso()
    report = ImportReport(marketId=market.id, seedId=seed.id, file=source_path.name, importedAt=imported_at, rows=len(rows))

    existing = registry.list_companies(db)
    by_id = {c["id"]: c for c in existing}
    alias_owner: dict[str, set[str]] = {}
    for company in existing:
        for key in company.get("aliasKeys") or [company.get("nameKey", "")]:
            alias_owner.setdefault(key, set()).add(company["id"])

    parsed = []
    for row in rows:
        raw_name = (row.get("Company") or "").strip()
        if not raw_name:
            report.skipped.append({"row": row.get("_row"), "reason": "No company name"})
            continue
        primary, related = split_name(raw_name)
        parsed.append((row, raw_name, primary, related))
    taken_primaries = {name_key(p) for _r, _n, p, _rel in parsed} | {c.get("nameKey", "") for c in existing}

    seen: dict[str, dict[str, Any]] = {}
    for row, raw_name, primary, related in parsed:
        key = name_key(primary)
        if key in seen:
            report.duplicates.append({"row": row.get("_row"), "name": raw_name, "mergedInto": seen[key]["name"]})
            continue
        owners = alias_owner.get(key, set())
        company = by_id.get(next(iter(owners))) if len(owners) == 1 else None
        fields = _seed_fields(row, market, seed)
        alias_keys = build_alias_keys(primary, related, taken_primaries - {key})
        seed_state = {"rawName": raw_name, "aliasKeys": alias_keys, **fields}
        seed_hash = _hash(seed_state)

        if company is None:
            company = {
                "id": slugify(primary),
                "name": primary,
                "nameKey": key,
                "displayName": raw_name,
                "kind": "ecosystem" if is_ecosystem(raw_name) else "employer",
                "career": {},
                "markets": {},
                "seeds": {},
                "source": seed.id,
                "firstImportedAt": imported_at,
            }
            while company["id"] in by_id:
                company["id"] = f"{company['id']}-{key[:4]}"
            report.created += 1
        else:
            previous = (company.get("seeds") or {}).get(seed.id) or {}
            membership = (company.get("markets") or {}).get(market.id) or {}
            if previous.get("hash") == seed_hash and not membership.get("removedFromSeedAt"):
                report.unchanged += 1
                seen[key] = company
                continue
            report.updated += 1

        company["displayName"] = raw_name
        company["relatedNames"] = related
        company["aliasKeys"] = alias_keys
        company["h1b"] = {**(company.get("h1b") or {}), **fields["h1b"]}
        company.setdefault("markets", {})[market.id] = {**fields["membership"], "removedFromSeedAt": None}
        career = company.setdefault("career", {})
        seed_url = fields["careerSeed"]["url"]
        previous_seed_url = career.get("seedUrl")
        career.update({
            "seedUrl": seed_url,
            "seedParseability": fields["careerSeed"]["parseability"],
            "seedVerification": fields["careerSeed"]["verification"],
        })
        # The seed URL is the official URL until discovery verifies a better one;
        # a URL CareerOS resolved itself is kept unless the seed changes under it.
        if not career.get("url") or career.get("urlSource") == "seed" or (seed_url and seed_url != previous_seed_url):
            if career.get("url") and seed_url and career.get("url") != seed_url:
                career["previousUrl"] = career.get("url")
                career["urlChangedAt"] = imported_at
            career["url"] = seed_url or career.get("url") or ""
            career["urlSource"] = "seed" if seed_url else career.get("urlSource")
        company.setdefault("seeds", {})[seed.id] = {
            "row": _int(row.get("_row")),
            "file": source_path.name,
            "importedAt": imported_at,
            "hash": seed_hash,
        }
        company["sourceImportedAt"] = imported_at
        seen[key] = company
        by_id[company["id"]] = company

    for kind, label, url in _reference_links(reference):
        words = re.sub(r"\s+(?:h-?1b evidence|careers)$", "", label, flags=re.I).split()
        target = None
        for size in range(len(words), 0, -1):
            target = seen.get(name_key(" ".join(words[:size])))
            if target:
                break
        if not target:
            continue
        changed = False
        if kind == "careers":
            alternates = target.setdefault("career", {}).setdefault("alternateUrls", [])
            if url not in [a.get("url") for a in alternates]:
                alternates.append({"label": label, "url": url, "source": seed.id})
                changed = True
        else:
            urls = target.setdefault("h1b", {}).setdefault("evidenceUrls", [])
            if url not in urls:
                urls.append(url)
                changed = True
        if changed:
            target["_dirty"] = True

    seen_ids = {c["id"] for c in seen.values()}
    for company in seen.values():
        dirty = company.pop("_dirty", False)
        stored = registry.get_company(db, company["id"])
        if stored != company or dirty:
            registry.save_company(db, company)
    for company in existing:
        membership = (company.get("markets") or {}).get(market.id)
        if membership and seed.id in (company.get("seeds") or {}) and company["id"] not in seen_ids and not membership.get("removedFromSeedAt"):
            membership["removedFromSeedAt"] = imported_at
            registry.save_company(db, company)
            report.removed.append(company["name"])
    db.flush()
    report.companies = len(registry.list_companies(db, market.id))
    return report
