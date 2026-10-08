"""Job link validation for the Markets page.

Every opportunity link is opened (HEAD, then GET) and classified:
``ok`` - the posting page answered; ``dead`` - 404/410 or the page says the job
is gone; ``unknown`` - the site blocked the check or did not answer, so the
link is neither trusted nor hidden. Results are cached per market in the KV
store and rechecked after RECHECK_HOURS, so a refresh only re-opens stale links.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.db.store import get_kv, now_iso, session_scope, set_kv
from app.services.job_discover.freshness import check_job_url_freshness

logger = logging.getLogger("career_os.markets.links")

OK, DEAD, UNKNOWN = "ok", "dead", "unknown"
RECHECK_HOURS = 24
_CONCURRENCY = 16
_PER_HOST = 2
# Greenhouse answers 403 to a burst of job-page requests; its public board API does not.
_GREENHOUSE = re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/([^/?#]+)/jobs/(\d+)", re.I)
# Several career sites answer a non-browser agent with 403 for pages that exist.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

_progress: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task[Any]] = {}


def _key(market_id: str) -> str:
    return f"markets:links:{market_id}"


def get_links(db: Session, market_id: str) -> dict[str, dict[str, Any]]:
    return dict(get_kv(db, _key(market_id)) or {})


def workday_boards(companies: list[dict[str, Any]]) -> dict[str, str]:
    boards: dict[str, str] = {}
    for company in companies:
        career = company.get("career") or {}
        config = career.get("config") or {}
        if career.get("provider") == "workday" and config.get("host") and config.get("board"):
            boards[str(config["host"]).lower()] = str(config["board"])
    return boards


def repair_url(url: str, boards: dict[str, str]) -> str:
    """Workday postings live at /{site}/job/...; the same path on the bare host is a 404."""
    parts = urlsplit(url or "")
    board = boards.get(parts.netloc.lower())
    if board and parts.path.startswith("/job/"):
        return parts._replace(path=f"/{board}{parts.path}").geturl()
    return url


def repair_stored_urls(db: Session, companies: list[dict[str, Any]]) -> int:
    from app.services.job_discover.store import rewrite_job_urls

    boards = workday_boards(companies)
    return rewrite_job_urls(db, partial(repair_url, boards=boards)) if boards else 0


def probe_url(url: str) -> str:
    match = _GREENHOUSE.match(url)
    return f"https://boards-api.greenhouse.io/v1/boards/{match[1]}/jobs/{match[2]}" if match else url


def verdict(result: dict[str, Any]) -> dict[str, Any]:
    code = result.get("statusCode")
    if result.get("closed"):
        status = DEAD
    elif isinstance(code, int) and 200 <= code < 300:
        status = OK
    else:
        status = UNKNOWN
    reason = result.get("reason") or ""
    if status == UNKNOWN and isinstance(code, int):
        reason = f"The site answered HTTP {code} to the check"
    return {"status": status, "reason": reason, "checkedAt": now_iso()}


def _stale(entry: dict[str, Any] | None, now: datetime) -> bool:
    if not entry or not entry.get("checkedAt") or entry.get("status") == UNKNOWN:
        return True
    try:
        checked = datetime.fromisoformat(str(entry["checkedAt"]).replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - checked > timedelta(hours=RECHECK_HOURS)


async def check_links(market_id: str, urls: list[str], *, force: bool = False, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Check the stale links among ``urls`` (the market's full current list; others are forgotten)."""
    with session_scope() as db:
        known = get_links(db, market_id)
    now = datetime.now(UTC)
    todo = sorted({u for u in urls if u and (force or _stale(known.get(u), now))})
    progress = _progress[market_id] = {
        "running": True, "total": len(todo), "done": 0, "dead": 0, "startedAt": now_iso(), "finishedAt": None, "error": None,
    }
    own_client = client is None
    if own_client:
        from app.services.job_discover.scraper_service import build_verified_ssl_context

        client = httpx.AsyncClient(
            verify=build_verified_ssl_context(), headers=_HEADERS, follow_redirects=True,
            timeout=httpx.Timeout(15.0, connect=8.0), limits=httpx.Limits(max_connections=_CONCURRENCY),
        )
    results: dict[str, dict[str, Any]] = {}
    sem = asyncio.Semaphore(_CONCURRENCY)
    hosts: dict[str, asyncio.Semaphore] = {}

    async def one(url: str) -> None:
        probe = probe_url(url)
        host = hosts.setdefault(urlsplit(probe).netloc.lower(), asyncio.Semaphore(_PER_HOST))
        async with host, sem:
            results[url] = verdict(await check_job_url_freshness(probe, client))
            progress["done"] += 1
            progress["dead"] += results[url]["status"] == DEAD

    try:
        await asyncio.gather(*(one(u) for u in todo))
    finally:
        if own_client:
            await client.aclose()
        listed = set(urls)
        with session_scope() as db:
            merged = {**get_links(db, market_id), **results}
            set_kv(db, _key(market_id), {u: v for u, v in merged.items() if u in listed})
        progress.update(running=False, finishedAt=now_iso())
    return progress


async def run_check(market_id: str, *, force: bool = False) -> dict[str, Any]:
    from app.services.markets import registry, views
    from app.services.markets.config import get_market

    market = get_market(market_id)
    if market is None:
        raise ValueError(f"Unknown market {market_id}")

    def current_urls() -> list[str]:
        with session_scope() as db:
            companies = registry.list_companies(db, market_id)
            repair_stored_urls(db, companies)
            return [o["url"] for o in views.opportunities(db, market, companies) if o.get("url")]

    return await check_links(market_id, await asyncio.to_thread(current_urls), force=force)


def get_progress(market_id: str) -> dict[str, Any]:
    return _progress.get(market_id) or {"running": False}


def is_running(market_id: str) -> bool:
    task = _tasks.get(market_id)
    return bool(task and not task.done())


def start_check(market_id: str, *, force: bool = False) -> dict[str, Any]:
    if is_running(market_id):
        return {"started": False, "progress": get_progress(market_id)}

    async def _run() -> None:
        try:
            await run_check(market_id, force=force)
        except Exception as exc:
            logger.exception("Link check for %s failed", market_id)
            _progress[market_id] = {**get_progress(market_id), "running": False, "error": f"{type(exc).__name__}: {exc}"}

    _progress[market_id] = {"running": True, "total": 0, "done": 0, "dead": 0}
    _tasks[market_id] = asyncio.get_running_loop().create_task(_run())
    return {"started": True, "progress": get_progress(market_id)}
