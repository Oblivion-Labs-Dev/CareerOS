"""Read models for the Markets page.

Opportunities are a lens over the canonical job store, not a copy: every
active posting whose employer resolves to a tracked company, whose location is
in the market and whose title is relevant - whichever source found it (the
company's own ATS, Indeed, HN, ...). Per-company enumeration counts come from
the cached scan; a company whose source cannot be read shows "unknown", never
zero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.services.markets import registry
from app.services.markets.config import Market
from app.services.markets.detector import is_aggregator_for
from app.services.markets.geo import match_location
from app.services.markets.identity import CompanyIndex
from app.services.markets.relevance import assess
from app.services.markets.sources import AUTOMATIC_TYPES, PROVIDERS, Health, SourceType, provider_label, status_bucket

HIGH_MATCH = 80
NEW_DAYS = 7
H1B_LABELS = {"strong": "Strong", "moderate": "Moderate", "weak": "Unknown"}
H1B_NOTE = "Company-level sponsorship history. Individual roles may differ."

_opportunity_cache: dict[str, tuple[tuple[Any, ...], list[dict[str, Any]]]] = {}


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _age_hours(ts: str | None) -> float | None:
    dt = _parse_ts(ts)
    return None if dt is None else (datetime.now(UTC) - dt).total_seconds() / 3600


def _is_new(posted_at: str | None, first_seen: str | None, baseline: datetime | None) -> bool:
    """Opened in the last week. The employer's posting date decides when there
    is one. Otherwise first-seen does, except for postings the company's first
    scan found: CareerOS saw them first that day, but they were already open."""
    posted_age = _age_hours(posted_at)
    if posted_age is not None:
        return posted_age <= NEW_DAYS * 24
    seen = _parse_ts(first_seen)
    if seen is None or (datetime.now(UTC) - seen) > timedelta(days=NEW_DAYS):
        return False
    return baseline is None or seen > baseline + timedelta(hours=1)


def _active(job: dict[str, Any]) -> bool:
    return not job.get("closedAt") and str(job.get("jobStatus") or "ACTIVE").upper() not in ("CLOSED", "EXPIRED", "FILLED")


def opportunities(db: Session, market: Market, companies: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    from app.services.job_discover.store import get_snapshot

    companies = companies if companies is not None else registry.list_companies(db, market.id)
    snapshot = get_snapshot(db)
    jobs = snapshot.get("jobs") or []
    dismissed = set(snapshot.get("dismissedIds") or [])
    # Jobs a company's first scan found were already open, not new.
    baselines = {
        cid: _parse_ts(entry.get("firstSuccessAt") or entry.get("lastSuccessAt"))
        for cid, entry in (registry.get_scan_state(db, market.id).get("companies") or {}).items()
    }
    cache_key = (id(jobs), len(jobs), len(dismissed), tuple(sorted((c["id"], tuple(c.get("aliasKeys") or [])) for c in companies)),
                 tuple(sorted((k, str(v)) for k, v in baselines.items())))
    cached = _opportunity_cache.get(market.id)
    if cached and cached[0] == cache_key:
        return cached[1]

    index = CompanyIndex(companies)
    by_id = {c["id"]: c for c in companies}
    out: list[dict[str, Any]] = []
    for job in jobs:
        if job.get("id") in dismissed or not _active(job):
            continue
        company_id = index.resolve(job.get("companyName") or job.get("company") or "")
        if not company_id:
            continue
        where = match_location(" | ".join(l for l in [job.get("location") or "", *(job.get("locations") or [])] if l), market)
        if not where.in_market:
            continue
        rel = assess(job.get("title") or "", job.get("description") or "")
        if not rel.relevant:
            continue
        company = by_id[company_id]
        membership = company["markets"][market.id]
        first_seen = job.get("firstSeenAt") or job.get("first_seen_at")
        posted_at = job.get("postingDate") or job.get("updatedAt") or None
        out.append({
            "id": job.get("id"),
            "title": job.get("title"),
            "companyId": company_id,
            "company": company["name"],
            "tier": membership.get("tier"),
            "priority": membership.get("applicationPriority"),
            "h1b": (company.get("h1b") or {}).get("strength", "weak"),
            "location": job.get("location"),
            "areas": where.areas,
            "zone": where.zone,
            "score": int(job.get("relevancyScore") or 0),
            "level": rel.level,
            "tags": rel.tags,
            "postedAt": posted_at,
            "firstSeenAt": job.get("firstSeenAt"),
            "isNew": _is_new(posted_at, first_seen, baselines.get(company_id)),
            "url": job.get("url"),
            "applyUrl": job.get("applyUrl") or job.get("url"),
            "source": job.get("canonicalSource"),
            "official": not is_aggregator_for(job.get("url") or "", company["name"]) and (
                (job.get("canonicalSourceTier") or "") in ("OFFICIAL_ATS", "OFFICIAL_CAREERS")
                or int(job.get("sourcePriority") or 0) >= 95
            ),
            "roleSponsorship": job.get("h1bStatus"),
        })
    out.sort(key=lambda o: (-o["score"], o["priority"] or 9999))
    _opportunity_cache[market.id] = (cache_key, out)
    return out


def _jobs_view(company: dict[str, Any], scan: dict[str, Any], opps: list[dict[str, Any]], last_run_id: str | None) -> dict[str, Any]:
    career = company.get("career") or {}
    counts = scan.get("counts") or {}
    automatic = career.get("sourceType") in {t.value for t in AUTOMATIC_TYPES} and (PROVIDERS.get(career.get("provider") or "") is None or PROVIDERS[career.get("provider")].supported)
    known = bool(scan.get("lastSuccessAt"))
    state = "known" if known else ("pending" if automatic else "unknown")
    official = [o for o in opps if o["official"]]
    return {
        "state": state,
        "totalOpen": counts.get("totalOpen") if known else None,
        "inMarket": counts.get("inMarket") if known else None,
        "scope": counts.get("scope"),
        "scopeLabel": counts.get("scopeLabel"),
        "truncated": bool(counts.get("truncated")),
        "stale": bool(scan.get("stale")),
        "relevant": len(opps),
        "relevantOfficial": len(official),
        "scanRelevant": counts.get("relevant") if known else None,
        "highMatch": sum(1 for o in opps if o["score"] >= HIGH_MATCH),
        "newCount": sum(1 for o in opps if o["isNew"]),
        "newSinceLastScan": len(scan.get("newKeys") or []) if scan.get("runId") == last_run_id else 0,
        "otherSources": len(opps) - len(official),
        "lastScanAt": scan.get("scannedAt"),
        "lastSuccessAt": scan.get("lastSuccessAt"),
    }


def company_view(company: dict[str, Any], market: Market, scan: dict[str, Any], opps: list[dict[str, Any]], last_run_id: str | None = None) -> dict[str, Any]:
    membership = company["markets"][market.id]
    career = company.get("career") or {}
    h1b = company.get("h1b") or {}
    return {
        "id": company["id"],
        "name": company["name"],
        "displayName": company.get("displayName") or company["name"],
        "kind": company.get("kind", "employer"),
        "tier": membership.get("tier"),
        "tierLabel": membership.get("tierLabel"),
        "priority": membership.get("applicationPriority"),
        "category": membership.get("category"),
        "areas": membership.get("areas") or [],
        "localPresence": membership.get("localPresence"),
        "zone": membership.get("zone"),
        "zoneLabel": membership.get("zoneLabel"),
        "fitScore": membership.get("fitScore"),
        "whyFits": membership.get("whyFits"),
        "notes": membership.get("notes"),
        "h1b": {
            "strength": h1b.get("strength", "weak"),
            "label": H1B_LABELS.get(h1b.get("strength", "weak"), "Unknown"),
            "score": h1b.get("score"),
            "activity": h1b.get("activity"),
            "localLcaCount": h1b.get("localLcaCount"),
            "lcaArea": h1b.get("lcaArea"),
            "evidence": h1b.get("evidence"),
            "evidenceUrls": h1b.get("evidenceUrls") or [],
            "source": h1b.get("source"),
            "note": H1B_NOTE,
        },
        "career": {
            "url": career.get("url") or "",
            "urlSource": career.get("urlSource") or "",
            "seedUrl": career.get("seedUrl") or "",
            "rejectedUrl": career.get("rejectedUrl"),
            "alternateUrls": career.get("alternateUrls") or [],
            "provider": career.get("provider"),
            "label": career.get("providerLabel") or provider_label(career.get("provider"), career.get("sourceType")),
            "sourceType": career.get("sourceType") or SourceType.UNKNOWN.value,
            "health": career.get("health") or Health.UNVERIFIED.value,
            "status": status_bucket(career),
            "method": career.get("method"),
            "confidence": career.get("confidence"),
            "evidence": career.get("evidence"),
            "detectedAt": career.get("detectedAt"),
            "lastAttemptAt": career.get("lastAttemptAt"),
            "lastSuccessAt": career.get("lastSuccessAt"),
            "failureReason": career.get("failureReason") or "",
            "httpStatus": career.get("httpStatus"),
            "sourceChange": career.get("sourceChange"),
            "seedParseability": career.get("seedParseability"),
        },
        "jobs": _jobs_view(company, scan, opps, last_run_id),
        "provenance": {
            "source": company.get("source"),
            "seeds": company.get("seeds") or {},
            "sourceImportedAt": company.get("sourceImportedAt"),
            "firstImportedAt": company.get("firstImportedAt"),
        },
    }


def market_snapshot(db: Session, market: Market) -> dict[str, Any]:
    """Everything the Markets page needs in one read."""
    companies = registry.list_companies(db, market.id)
    state = registry.get_scan_state(db, market.id)
    opps = opportunities(db, market, companies)
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for opp in opps:
        by_company[opp["companyId"]].append(opp)
    last_run = state.get("lastRun") or {}
    views = [
        company_view(c, market, (state["companies"].get(c["id"]) or {}), by_company.get(c["id"], []), last_run.get("runId"))
        for c in companies
    ]
    views.sort(key=lambda v: v["priority"] or 9999)
    return {"companies": views, "opportunities": opps, "state": state}


def pulse(views: list[dict[str, Any]], opps: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    total = len(views) or 1
    buckets = defaultdict(int)
    for v in views:
        buckets[v["career"]["status"]] += 1
    automatic = sum(1 for v in views if v["jobs"]["state"] != "unknown")
    fresh = sum(1 for v in views if (_age_hours(v["career"]["lastSuccessAt"]) or 1e9) <= 24)
    hiring = [v for v in views if v["jobs"]["relevant"] > 0]
    last_run = state.get("lastRun") or {}
    return {
        "companies": len(views),
        "matches": len(opps),
        "highMatch": sum(1 for o in opps if o["score"] >= HIGH_MATCH),
        "newThisWeek": sum(1 for o in opps if o["isNew"]),
        "tier1Hiring": sum(1 for v in hiring if v["tier"] == 1),
        "hiringCompanies": len(hiring),
        "autoSearchable": automatic,
        "autoSearchablePct": round(100 * automatic / total),
        "fresh24h": fresh,
        "fresh24hPct": round(100 * fresh / total),
        "health": {k: buckets.get(k, 0) for k in ("healthy", "manual", "degraded", "failed", "pending")},
        "lastScanAt": last_run.get("finishedAt"),
        "lastRun": last_run or None,
    }


PROBLEM_ORDER = ("Scan failed", "Blocked", "Career URL changed", "ATS unsupported", "Browser required", "Unknown", "Manual")


def problem_for(view: dict[str, Any]) -> str | None:
    career = view["career"]
    status = career["status"]
    if status == "healthy" or status == "pending":
        return None
    if status in ("failed", "degraded"):
        if (career.get("httpStatus") or 0) in (404, 410):
            return "Career URL changed"
        return "Scan failed"
    source_type = career["sourceType"]
    if source_type == SourceType.BLOCKED.value:
        return "Blocked"
    if source_type == SourceType.BROWSER.value:
        return "Browser required"
    if career.get("provider") and not (PROVIDERS.get(career["provider"]) and PROVIDERS[career["provider"]].supported):
        return "ATS unsupported"
    if (career.get("httpStatus") or 0) in (404, 410):
        return "Career URL changed"
    if source_type == SourceType.UNKNOWN.value:
        return "Unknown"
    return "Manual"


def health_view(views: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    problems: dict[str, int] = defaultdict(int)
    attention = []
    for v in views:
        label = v["career"]["label"]
        by_source[label][v["career"]["status"]] += 1
        by_source[label]["total"] += 1
        problem = problem_for(v)
        if problem:
            problems[problem] += 1
            attention.append({
                "companyId": v["id"],
                "company": v["name"],
                "tier": v["tier"],
                "priority": v["priority"],
                "source": label,
                "problem": problem,
                "reason": v["career"]["failureReason"],
                "status": v["career"]["status"],
                "lastSuccessAt": v["career"]["lastSuccessAt"],
                "lastAttemptAt": v["career"]["lastAttemptAt"],
                "url": v["career"]["url"],
                "otherSources": v["jobs"]["otherSources"],
            })
    attention.sort(key=lambda a: (PROBLEM_ORDER.index(a["problem"]), a["priority"] or 9999))
    sources = sorted(
        ({"source": k, **{s: int(n) for s, n in v.items()}} for k, v in by_source.items()),
        key=lambda s: -s["total"],
    )
    return {
        "sources": sources,
        "problems": [{"problem": p, "count": problems[p]} for p in PROBLEM_ORDER if problems.get(p)],
        "needsAttention": attention,
    }
