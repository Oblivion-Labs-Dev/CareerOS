"""Market refresh: detect each company's career source, enumerate it, feed the canonical store.

Runs in the background with bounded concurrency, cheapest sources first
(public ATS JSON, then paginated/proprietary APIs, then browser detection).
Results are persisted company by company, so the Markets page stays usable and
fills in while a refresh is running. Relevant in-market jobs go through
``import_jobs_batch`` - the same normalize/score/dedupe path a scrape uses - so
there is exactly one job record per posting across every source.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.db.store import new_id, now_iso, session_scope
from app.services.job_discover.dedup import canonicalize_url
from app.services.markets import registry
from app.services.markets.config import Market, get_market
from app.services.markets.detector import BrowserProbe, Detection, detect
from app.services.markets.enumerate import ADAPTERS, PROPRIETARY, Enumeration, enumerate_company
from app.services.markets.sources import AUTOMATIC_TYPES, PROVIDERS, Health, SourceType, provider_label

logger = logging.getLogger("career_os.markets.refresh")

GROUPS = (
    ("ats", "ATS APIs"),
    ("proprietary", "Company APIs"),
    ("heavy", "Workday / iCIMS / Oracle"),
    ("pages", "Career pages"),
    ("detect", "Source detection"),
    ("manual", "Manual (skipped)"),
)
_CONCURRENCY = {"ats": 8, "proprietary": 2, "heavy": 3, "pages": 4}
# Each flush rewrites the whole canonical job snapshot (tens of MB, holding the
# GIL while it serializes), so fewer, larger batches keep the API responsive.
_IMPORT_BATCH = 400
_RUNS_KEPT = 20

_progress: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task[Any]] = {}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _age_hours(ts: str | None) -> float | None:
    dt = _parse(ts)
    return None if dt is None else (datetime.now(UTC) - dt).total_seconds() / 3600


def group_for(career: dict[str, Any]) -> str:
    provider = career.get("provider") or ""
    source_type = career.get("sourceType")
    if provider in PROPRIETARY:
        return "proprietary"
    if provider in ADAPTERS or provider == "jibe":
        return "ats" if PROVIDERS[provider].cost <= 1 else "heavy"
    if provider == "jsonld":
        return "pages"
    if source_type in {SourceType.MANUAL.value, SourceType.BLOCKED.value, SourceType.BROWSER.value} and career.get("detectedAt"):
        return "manual"
    return "detect"


def needs_detection(company: dict[str, Any], market: Market, *, force: bool) -> bool:
    career = company.get("career") or {}
    if force or not career.get("detectedAt"):
        return True
    if (career.get("detectedUrl") or "") != (career.get("url") or ""):
        return True
    if (career.get("httpStatus") or 0) in (404, 410):
        return True
    age = _age_hours(career.get("detectedAt"))
    return age is None or age > market.detection_ttl_hours


def apply_detection(company: dict[str, Any], det: Detection) -> dict[str, Any]:
    career = company.setdefault("career", {})
    previous_provider = career.get("provider")
    if det.career_url and not career.get("url"):
        career["url"] = det.career_url
        career["urlSource"] = det.url_source or "detected"
    if det.career_url == "" and career.get("url") and any(s.get("outcome") == "rejected" for s in det.steps):
        career["rejectedUrl"] = career["url"]
        career["url"] = ""
        career["urlSource"] = ""
    career.update({
        "sourceType": det.source_type,
        "provider": det.provider,
        "providerLabel": provider_label(det.provider, det.source_type),
        "config": det.config,
        "method": det.method,
        "confidence": det.confidence,
        "evidence": det.evidence,
        "detectionSteps": det.steps,
        "detectedAt": now_iso(),
        "detectedUrl": career.get("url") or "",
        "httpStatus": det.http_status,
        "finalUrl": det.final_url,
    })
    if previous_provider and det.provider and previous_provider != det.provider:
        career["sourceChange"] = {"from": provider_label(previous_provider, None), "to": career["providerLabel"], "at": now_iso()}
    spec = PROVIDERS.get(det.provider or "")
    automatic = det.source_type in {t.value for t in AUTOMATIC_TYPES} and (spec is None or spec.supported)
    if not automatic:
        career["failureReason"] = det.failure_reason
        career["lastAttemptAt"] = now_iso()
        if not career.get("lastSuccessAt"):
            career["health"] = Health.UNVERIFIED.value
    else:
        career.setdefault("health", Health.UNVERIFIED.value)
    return company


_SIDE_BOARD_MAX = 5


def _side_board_warning(career: dict[str, Any], result: Enumeration) -> str:
    """A board found only by probing the company's name, nearly empty, while the
    company runs its own career site that never pointed to it, is a side board
    (ByteDance's 2-posting SmartRecruiters page), not where its jobs live."""
    if career.get("method") != "ats_probe" or career.get("urlSource") != "seed" or not career.get("url"):
        return ""
    total = result.counts().get("totalOpen") or 0
    if total >= _SIDE_BOARD_MAX:
        return ""
    return (f"Only {total} posting{'s' if total != 1 else ''} on the {provider_label(career.get('provider'), career.get('sourceType'))} "
            f"board found under the company's name; its own career site is not readable unattended, so counts are likely incomplete")


def apply_enumeration(company: dict[str, Any], result: Enumeration) -> dict[str, Any]:
    career = company.setdefault("career", {})
    now = now_iso()
    career["lastAttemptAt"] = now
    career["lastDurationMs"] = result.duration_ms
    if result.ok:
        warning = result.error or _side_board_warning(career, result)
        career["health"] = Health.DEGRADED.value if warning else Health.HEALTHY.value
        career["lastSuccessAt"] = now
        career["failureReason"] = warning or ""
        career["consecutiveFailures"] = 0
    else:
        career["consecutiveFailures"] = int(career.get("consecutiveFailures") or 0) + 1
        career["failureReason"] = result.error or "Scan failed"
        career["httpStatus"] = result.http_status or career.get("httpStatus")
        recent = _age_hours(career.get("lastSuccessAt"))
        career["health"] = Health.DEGRADED.value if recent is not None and recent < 72 else Health.FAILED.value
    return company


JOB_KEY_VERSION = 2


def job_key(job: dict[str, Any]) -> str:
    """Per-posting key shared by scanned jobs and canonical store jobs (the
    store keeps canonicalize_url(url)). The query stays: company-hosted ATS
    pages share one path and differ only in ?gh_jid=."""
    url = canonicalize_url(job.get("url") or "")
    return (url or f"{job.get('source')}:{job.get('external_id') or job.get('externalId')}").lower()


def record_scan(state: dict[str, Any], company: dict[str, Any], result: Enumeration, run_id: str) -> dict[str, Any]:
    entries = state.setdefault("companies", {})
    previous = entries.get(company["id"]) or {}
    entry = dict(previous)
    entry.update({"runId": run_id, "scannedAt": now_iso(), "ok": result.ok, "error": result.error, "provider": result.provider})
    if result.ok:
        relevant = sorted({job_key(j) for j in result.relevant_jobs})
        # Keys from an older format cannot be compared: rebaseline.
        prior = previous.get("relevantKeys") if previous.get("keyVersion") == JOB_KEY_VERSION else None
        entry.update({
            "firstSuccessAt": previous.get("firstSuccessAt") or previous.get("lastSuccessAt") or entry["scannedAt"],
            "lastSuccessAt": entry["scannedAt"],
            "counts": result.counts(),
            "relevantKeys": relevant,
            "keyVersion": JOB_KEY_VERSION,
            "previousRelevantKeys": prior,
            # A first successful scan is a baseline, not "new".
            "newKeys": sorted(set(relevant) - set(prior)) if prior is not None else [],
            "closedKeys": sorted(set(prior) - set(relevant)) if prior is not None else [],
            "stale": False,
        })
    else:
        entry["stale"] = bool(previous.get("counts"))
    entries[company["id"]] = entry
    return entry


def _new_progress(market: Market, run_id: str, force: bool) -> dict[str, Any]:
    return {
        "marketId": market.id,
        "runId": run_id,
        "running": True,
        "phase": "starting",
        "force": force,
        "startedAt": now_iso(),
        "finishedAt": None,
        "total": 0,
        "done": 0,
        "current": [],
        "groups": {key: {"label": label, "total": 0, "done": 0} for key, label in GROUPS},
        "counts": {"succeeded": 0, "failed": 0, "skipped": 0, "detected": 0, "imported": 0},
        "error": None,
        "summary": None,
    }


def get_progress(market_id: str) -> dict[str, Any]:
    return _progress.get(market_id) or {"marketId": market_id, "running": False}


def is_running(market_id: str) -> bool:
    task = _tasks.get(market_id)
    return bool(task and not task.done())


class _Importer:
    """Buffers relevant jobs and feeds them to the canonical store in batches."""

    def __init__(self, progress: dict[str, Any]) -> None:
        self.buffer: list[tuple[str, dict[str, Any]]] = []
        self.job_ids: dict[str, list[str]] = {}
        self.progress = progress
        self.lock = asyncio.Lock()

    async def add(self, company_id: str, jobs: Iterable[dict[str, Any]]) -> None:
        self.buffer.extend((company_id, job) for job in jobs)
        if len(self.buffer) >= _IMPORT_BATCH:
            await self.flush()

    async def flush(self) -> None:
        async with self.lock:
            if not self.buffer:
                return
            batch, self.buffer = self.buffer, []
            from app.services.job_discover.store import import_jobs_batch

            raws = [{k: v for k, v in job.items() if not k.startswith("_")} for _cid, job in batch]
            with session_scope() as db:
                results = await import_jobs_batch(db, raws)
            for (company_id, _job), outcome in zip(batch, results):
                if outcome.get("jobId"):
                    self.job_ids.setdefault(company_id, []).append(outcome["jobId"])
                if outcome.get("status") in ("created", "updated"):
                    self.progress["counts"]["imported"] += 1


async def _detect_one(client: httpx.AsyncClient, company: dict[str, Any], browser: BrowserProbe | None, market: Market, progress: dict[str, Any], sem: asyncio.Semaphore) -> dict[str, Any]:
    async with sem:
        progress["current"] = (progress["current"] + [company["name"]])[-4:]
        try:
            det = await detect(client, company, browser=browser)
        except Exception as exc:
            logger.exception("Detection failed for %s", company["name"])
            det = Detection(source_type=SourceType.UNKNOWN.value, failure_reason=f"Detection error: {exc}")
        apply_detection(company, det)
        with session_scope() as db:
            registry.save_company(db, company)
        progress["counts"]["detected"] += 1
        progress["groups"]["detect"]["done"] += 1
        return company


async def _scan_one(client: httpx.AsyncClient, company: dict[str, Any], market: Market, run_id: str, progress: dict[str, Any], importer: _Importer, group: str, sem: asyncio.Semaphore) -> None:
    async with sem:
        progress["current"] = (progress["current"] + [company["name"]])[-4:]
        result = await enumerate_company(client, company, market)
        apply_enumeration(company, result)
        with session_scope() as db:
            registry.save_company(db, company)
            state = registry.get_scan_state(db, market.id)
            record_scan(state, company, result, run_id)
            registry.save_scan_state(db, market.id, state)
        if result.ok:
            progress["counts"]["succeeded"] += 1
            await importer.add(company["id"], result.relevant_jobs)
        else:
            progress["counts"]["failed"] += 1
        progress["groups"][group]["done"] += 1
        progress["done"] += 1


def _summarize(state: dict[str, Any], companies: dict[str, dict[str, Any]], run_id: str, progress: dict[str, Any], before: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entries = state.get("companies") or {}
    summary: dict[str, Any] = {
        "runId": run_id,
        "startedAt": progress["startedAt"],
        "finishedAt": now_iso(),
        "scanned": progress["counts"]["succeeded"] + progress["counts"]["failed"],
        "succeeded": progress["counts"]["succeeded"],
        "failed": progress["counts"]["failed"],
        "skipped": progress["counts"]["skipped"],
        "imported": progress["counts"]["imported"],
        "newJobs": 0,
        "closedJobs": 0,
        "newByCompany": {},
        "startedHiring": [],
        "stoppedHiring": [],
        "sourceChanges": [],
        "needsAttention": 0,
    }
    for company_id, entry in entries.items():
        if entry.get("runId") != run_id or not entry.get("ok"):
            continue
        name = (companies.get(company_id) or {}).get("name", company_id)
        new = entry.get("newKeys") or []
        summary["newJobs"] += len(new)
        summary["closedJobs"] += len(entry.get("closedKeys") or [])
        if new:
            summary["newByCompany"][company_id] = len(new)
        prior = entry.get("previousRelevantKeys")
        if prior is not None:
            if not prior and entry.get("relevantKeys"):
                summary["startedHiring"].append(name)
            if prior and not entry.get("relevantKeys"):
                summary["stoppedHiring"].append(name)
    for company_id, company in companies.items():
        change = (company.get("career") or {}).get("sourceChange")
        old = before.get(company_id) or {}
        if change and change != (old.get("career") or {}).get("sourceChange"):
            summary["sourceChanges"].append({"company": company["name"], **change})
        if (company.get("career") or {}).get("health") in (Health.FAILED.value, Health.DEGRADED.value):
            summary["needsAttention"] += 1
    return summary


async def run_refresh(
    market_id: str,
    *,
    force: bool = False,
    company_ids: list[str] | None = None,
    allow_browser: bool = True,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    market = get_market(market_id)
    if market is None:
        raise ValueError(f"Unknown market {market_id}")
    run_id = new_id("mrun_")
    progress = _new_progress(market, run_id, force)
    _progress[market_id] = progress
    browser = BrowserProbe() if allow_browser else None
    own_client = client is None
    if own_client:
        from app.services.job_discover.scraper_service import build_verified_ssl_context

        client = httpx.AsyncClient(
            verify=build_verified_ssl_context(),
            follow_redirects=True,
            timeout=httpx.Timeout(20.0, connect=10.0),
            limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
        )
    importer = _Importer(progress)
    try:
        with session_scope() as db:
            companies = registry.list_companies(db, market_id)
        if company_ids:
            wanted = set(company_ids)
            companies = [c for c in companies if c["id"] in wanted]
        before = {c["id"]: {"career": dict(c.get("career") or {})} for c in companies}
        by_id = {c["id"]: c for c in companies}
        companies.sort(key=lambda c: (c["markets"][market_id].get("applicationPriority") or 9999))
        progress["total"] = len(companies)

        # 1. Detection, where it is missing or stale. Cheap rungs run widely;
        # the browser rung is capped inside BrowserProbe use by this semaphore.
        progress["phase"] = "detecting"
        to_detect = [c for c in companies if needs_detection(c, market, force=force)]
        progress["groups"]["detect"]["total"] = len(to_detect)
        detect_sem = asyncio.Semaphore(10)
        await asyncio.gather(*(_detect_one(client, c, browser, market, progress, detect_sem) for c in to_detect))

        # 2. Enumeration, grouped by cost.
        progress["phase"] = "scanning"
        explicit = bool(company_ids)
        groups: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in GROUPS}
        for company in companies:
            group = group_for(company.get("career") or {})
            if group in ("manual", "detect"):
                groups["manual"].append(company)
                continue
            age = _age_hours((company.get("career") or {}).get("lastSuccessAt"))
            if not force and not explicit and age is not None and age < market.fresh_hours:
                progress["counts"]["skipped"] += 1
                progress["done"] += 1
                continue
            groups[group].append(company)
        progress["groups"]["manual"]["total"] = len(groups["manual"])
        progress["groups"]["manual"]["done"] = len(groups["manual"])
        progress["done"] += len(groups["manual"])
        for key in ("ats", "proprietary", "heavy", "pages"):
            progress["groups"][key]["total"] = len(groups[key])
        for key in ("ats", "proprietary", "heavy", "pages"):
            if not groups[key]:
                continue
            sem = asyncio.Semaphore(_CONCURRENCY[key])
            await asyncio.gather(*(_scan_one(client, c, market, run_id, progress, importer, key, sem) for c in groups[key]))

        progress["phase"] = "importing"
        await importer.flush()

        with session_scope() as db:
            state = registry.get_scan_state(db, market_id)
            for company_id, ids in importer.job_ids.items():
                entry = state["companies"].get(company_id)
                if entry is not None and entry.get("runId") == run_id:
                    entry["jobIds"] = sorted(set(ids))
            summary = _summarize(state, by_id, run_id, progress, before)
            if not explicit:
                state["lastRun"] = summary
                state["runs"] = ([summary] + [r for r in state.get("runs", []) if r.get("runId") != run_id])[:_RUNS_KEPT]
            registry.save_scan_state(db, market_id, state)
        progress["summary"] = summary
        progress["phase"] = "done"
        return summary
    except Exception as exc:
        logger.exception("Market refresh %s failed", market_id)
        progress["error"] = f"{type(exc).__name__}: {exc}"
        progress["phase"] = "failed"
        raise
    finally:
        progress["running"] = False
        progress["finishedAt"] = now_iso()
        progress["current"] = []
        if browser is not None:
            await browser.close()
        if own_client:
            await client.aclose()


def start_refresh(market_id: str, *, force: bool = False, allow_browser: bool = True) -> dict[str, Any]:
    if is_running(market_id):
        return {"started": False, "progress": get_progress(market_id)}

    async def _run() -> None:
        try:
            await run_refresh(market_id, force=force, allow_browser=allow_browser)
        except Exception:
            return  # recorded in progress
        from app.services.markets import links

        links.start_check(market_id)

    _progress[market_id] = {"marketId": market_id, "running": True, "phase": "starting", "done": 0, "total": 0}
    _tasks[market_id] = asyncio.get_running_loop().create_task(_run())
    return {"started": True, "progress": get_progress(market_id)}
