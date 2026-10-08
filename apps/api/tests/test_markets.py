"""Markets: seed import, identity, geography, source detection, enumeration,
refresh bookkeeping and the API - all offline (httpx.MockTransport)."""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.store import delete_entity, list_entities, session_scope, set_kv
from app.services.markets import refresh, registry
from app.services.markets.config import get_market
from app.services.markets.detector import detect, is_aggregator_for, provider_from_url
from app.services.markets.enumerate import enumerate_company
from app.services.markets.geo import match_location
from app.services.markets.identity import CompanyIndex, name_key, split_name
from app.services.markets.importer import h1b_strength, import_seed
from app.services.markets.relevance import assess
from app.services.markets.sources import status_bucket

HEADER = [
    "Apply #", "Company", "Tier", "Category", "Local Presence", "Commute Zone from Auburn",
    "H-1B Strength /10", "H-1B Activity", "H-1B Evidence", "Fit /10", "Career Site",
    "Career Parseability", "Verification / Source", "Why It Fits", "Notes",
]


def _row(n: int, name: str, tier: str = "1 - Apply first", presence: str = "Seattle, WA", score: str = "9",
         evidence: str = "Verified local LCA filings", url: str = "", zone: str = "B - Practical") -> list[str]:
    return [str(n), name, tier, "Cloud", presence, zone, score, "High", evidence, "8", url, "PARSABLE", "Verified", "Fits", ""]


def _col(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        out = chr(65 + rem) + out
    return out


def write_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    """A minimal workbook with inline strings - enough for the stdlib reader."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        sheet_tags, rels = [], []
        for i, (name, rows) in enumerate(sheets.items(), start=1):
            sheet_tags.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
            rels.append(f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>')
            body = "".join(
                f'<row r="{r}">' + "".join(
                    f'<c r="{_col(c)}{r}" t="inlineStr"><is><t>{escape(v)}</t></is></c>' for c, v in enumerate(cells) if v != ""
                ) + "</row>"
                for r, cells in enumerate(rows, start=1)
            )
            z.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{body}</sheetData></worksheet>')
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + "".join(sheet_tags) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>")
    return path


SEED_ROWS = [
    _row(1, "Amazon / AWS", url="https://www.amazon.jobs/en/search", score="10"),
    _row(2, "Acme Cloud", url="https://job-boards.greenhouse.io/acmecloud", presence="Bellevue, WA"),
    _row(3, "Widgets Inc.", tier="2 - Strong", score="7", evidence="Historical sponsor", url=""),
    _row(4, "Acme Cloud", url="https://job-boards.greenhouse.io/acmecloud"),
    _row(5, "Convoy alumni/startup ecosystem", tier="4 - Network", score="", evidence=""),
    _row(6, "Listing Co", url="https://www.indeed.com/cmp/listing-co/jobs"),
]


@pytest.fixture
def market_db(tmp_path):
    """A clean registry for the Seattle market and a seed file with the six rows above."""
    with session_scope() as db:
        for entity in list_entities(db, registry.COMPANY_ENTITY):
            delete_entity(db, registry.COMPANY_ENTITY, entity["id"])
        set_kv(db, "markets:scan:seattle", {"companies": {}, "runs": []})
    seed = write_xlsx(tmp_path / "seed.xlsx", {"Application Queue": [HEADER, *SEED_ROWS], "Sources & Method": [["Label", "URL"], ["Widgets careers", "https://careers.widgets.example/jobs"]]})
    return seed


def _import(seed: Path):
    with session_scope() as db:
        return import_seed(db, get_market("seattle"), path=seed)


# ── Import ──────────────────────────────────────────────────────────────────


def test_import_creates_one_company_per_employer_with_provenance(market_db):
    report = _import(market_db)
    assert report.rows == 6
    assert report.created == 5
    assert [d["name"] for d in report.duplicates] == ["Acme Cloud"]

    with session_scope() as db:
        amazon = registry.get_company(db, "amazon")
        acme = registry.get_company(db, "acme-cloud")
        widgets = registry.get_company(db, "widgets")
    assert amazon["name"] == "Amazon" and "aws" in amazon["aliasKeys"]
    assert amazon["source"] == "seattle_company_seed"
    assert amazon["seeds"]["seattle_company_seed"]["row"] == 2
    assert amazon["markets"]["seattle"]["applicationPriority"] == 1
    assert amazon["h1b"] == {**amazon["h1b"], "strength": "strong", "scope": "company"}
    assert acme["markets"]["seattle"]["areas"] == ["Bellevue"]
    assert widgets["h1b"]["strength"] == "moderate"
    assert [a["url"] for a in widgets["career"]["alternateUrls"]] == ["https://careers.widgets.example/jobs"]


def test_reimport_is_idempotent_and_keeps_discovered_urls(market_db):
    _import(market_db)
    with session_scope() as db:
        widgets = registry.get_company(db, "widgets")
        widgets["career"].update({"url": "https://careers.widgets.example/jobs", "urlSource": "domain_verified"})
        registry.save_company(db, widgets)
    report = _import(market_db)
    assert report.created == 0 and report.updated == 0 and report.unchanged == 5
    with session_scope() as db:
        assert registry.get_company(db, "widgets")["career"]["url"] == "https://careers.widgets.example/jobs"
        assert len(registry.list_companies(db, "seattle")) == 5


def test_company_dropped_from_seed_is_marked_not_deleted(market_db, tmp_path):
    _import(market_db)
    smaller = write_xlsx(tmp_path / "smaller.xlsx", {"Application Queue": [HEADER, *SEED_ROWS[:2]]})
    report = _import(smaller)
    assert "Widgets Inc." in report.removed
    with session_scope() as db:
        assert registry.get_company(db, "widgets")["markets"]["seattle"]["removedFromSeedAt"]
        assert {c["id"] for c in registry.list_companies(db, "seattle")} == {"amazon", "acme-cloud"}


def test_h1b_strength_needs_verified_evidence_for_strong():
    assert h1b_strength(10, "", "Verified recent LCAs") == "strong"
    assert h1b_strength(10, "", "Historical sponsor") == "moderate"
    assert h1b_strength(7, "", "") == "moderate"
    assert h1b_strength(4, "", "Verified") == "weak"
    assert h1b_strength(None, "Medium", "") == "moderate"
    assert h1b_strength(None, "", "") == "weak"


# ── Identity and geography ──────────────────────────────────────────────────


def test_name_normalization_and_resolution():
    assert name_key("OpenAI, Inc.") == name_key("Open AI") == "openai"
    assert split_name("Amazon / AWS") == ("Amazon", ["AWS"])
    companies = [
        {"id": "amazon", "name": "Amazon", "aliasKeys": ["amazon", "aws"]},
        {"id": "apple", "name": "Apple", "aliasKeys": ["apple"]},
    ]
    index = CompanyIndex(companies)
    assert index.resolve("Amazon Web Services") == "amazon"
    assert index.resolve("AWS") == "amazon"
    assert index.resolve("Apple Inc.") == "apple"
    assert index.resolve("Apple Leisure Group") is None


@pytest.mark.parametrize(
    ("location", "in_market", "areas"),
    [
        ("Seattle, WA", True, ["Seattle"]),
        ("Redmond, Washington, United States", True, ["Redmond"]),
        ("US-Seattle-3rd | San Francisco, California", True, ["Seattle"]),
        ("Kent, OH", False, []),
        ("Bellevue, NE", False, []),
        ("Washington, DC", False, []),
        ("Remote - US", False, []),
        ("Greater Seattle Area", True, []),
    ],
)
def test_market_membership(location, in_market, areas):
    match = match_location(location, get_market("seattle"))
    assert match.in_market is in_market
    if areas:
        assert match.areas == areas


# ── Relevance ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "relevant"),
    [
        ("Senior Software Engineer", True),
        ("SDE III, AWS Bedrock", True),
        ("Staff Engineer, Distributed Systems", True),
        ("Senior AI Engineer - Agentic Platform", True),
        ("Software Engineer II", False),
        ("New Grad Software Engineer", False),
        ("Senior Product Manager", False),
        ("Recruiter, Engineering", False),
    ],
)
def test_relevance(title, relevant):
    assert assess(title, "").relevant is relevant


def test_relevance_tags():
    tags = assess("Senior Backend Engineer, LLM Platform", "").tags
    assert "AI/ML" in tags or "Platform" in tags


# ── Detection ───────────────────────────────────────────────────────────────


def test_provider_fingerprints():
    assert provider_from_url("https://job-boards.greenhouse.io/acmecloud")[:2] == ("greenhouse", {"slug": "acmecloud"})
    assert provider_from_url("https://jobs.lever.co/zoox")[:2] == ("lever", {"slug": "zoox"})
    assert provider_from_url("https://jobs.ashbyhq.com/openai")[:2] == ("ashby", {"slug": "openai"})
    provider, config, *_ = provider_from_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite")
    assert provider == "workday" and config["board"] == "NVIDIAExternalCareerSite" and config["tenant"] == "nvidia"
    assert provider_from_url("https://www.amazon.jobs/en/search")[0] == "amazon"
    assert provider_from_url("https://www.icims.com/legal/privacy")[0] is None
    provider, config, *_ = provider_from_url("https://eeho.fa.us2.oraclecloud.com:443/hcmUI/x?siteNumber=CX_45001")
    assert provider == "oracle" and config == {"host": "eeho.fa.us2.oraclecloud.com", "site": "CX_45001"}


def test_aggregator_is_never_an_official_career_url():
    assert is_aggregator_for("https://www.indeed.com/cmp/acme/jobs", "Acme")
    assert is_aggregator_for("https://www.linkedin.com/company/acme/jobs", "Acme")
    assert not is_aggregator_for("https://www.indeed.com/careers", "Indeed")
    assert not is_aggregator_for("https://job-boards.greenhouse.io/acme", "Acme")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_detect_reads_ats_link_from_career_page():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.acme.example":
            return httpx.Response(200, text='<a href="https://job-boards.greenhouse.io/acme">Open roles</a>')
        return httpx.Response(404)

    company = {"id": "acme", "name": "Acme", "career": {"url": "https://careers.acme.example/"}}
    det = asyncio.run(_detect(handler, company))
    assert (det.provider, det.method, det.source_type) == ("greenhouse", "html_embed", "ATS_API")


def test_detect_rejects_aggregator_and_falls_back_to_unknown():
    company = {"id": "listing-co", "name": "Listing Co", "career": {"url": "https://www.indeed.com/cmp/listing-co/jobs"}}
    det = asyncio.run(_detect(lambda r: httpx.Response(404), company))
    assert det.career_url == ""
    assert det.source_type == "UNKNOWN"
    assert any(s["step"] == "career_url" and s["outcome"] == "rejected" for s in det.steps)


def test_detect_ecosystem_row_is_manual_without_network():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no request expected")

    det = asyncio.run(_detect(handler, {"id": "convoy", "name": "Convoy alumni", "kind": "ecosystem", "career": {}}))
    assert det.source_type == "MANUAL" and det.method == "not_an_employer"


def test_detect_blocked_site():
    company = {"id": "multicare", "name": "MultiCare", "career": {"url": "https://jobs.multicare.example/"}}
    det = asyncio.run(_detect(lambda r: httpx.Response(403), company))
    assert det.source_type == "BLOCKED" and "403" in det.failure_reason


def test_unreadable_ats_link_yields_to_a_readable_board_under_the_name():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.acme.example":
            return httpx.Response(200, text='<a href="https://acme.eightfold.ai/careers">Jobs</a>')
        if request.url.host == "boards-api.greenhouse.io" and request.url.path.endswith("/acme"):
            return httpx.Response(200, json={"name": "Acme"})
        return httpx.Response(404)

    company = {"id": "acme", "name": "Acme", "career": {"url": "https://careers.acme.example/"}}
    det = asyncio.run(_detect(handler, company))
    assert (det.provider, det.method, det.source_type) == ("greenhouse", "ats_probe", "ATS_API")


def test_unreadable_ats_is_kept_when_nothing_better_exists():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.acme.example":
            return httpx.Response(200, text='<a href="https://acme.eightfold.ai/careers">Jobs</a>')
        return httpx.Response(404)

    company = {"id": "acme", "name": "Acme", "career": {"url": "https://careers.acme.example/"}}
    det = asyncio.run(_detect(handler, company))
    assert (det.provider, det.source_type) == ("eightfold", "MANUAL")


def test_first_word_slug_needs_the_board_to_carry_the_full_name():
    def handler(name: str):
        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.host == "boards-api.greenhouse.io" and request.url.path.endswith("/liberty"):
                return httpx.Response(200, json={"name": name})
            return httpx.Response(404)
        return respond

    company = {"id": "liberty-mutual", "name": "Liberty Mutual", "career": {}}
    assert asyncio.run(_detect(handler("Liberty Fitness"), company)).provider is None
    assert asyncio.run(_detect(handler("Liberty Mutual"), company)).provider == "greenhouse"


def test_known_source_is_used_with_its_evidence():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no request expected")

    company = {"id": "salesforce", "name": "Salesforce", "career": {"url": "https://careers.salesforce.com/"}}
    det = asyncio.run(_detect(handler, company))
    assert (det.provider, det.method) == ("workday", "known_source")
    assert det.config["board"] == "External_Career_Site"
    assert det.career_url == "https://careers.salesforce.com/"


def test_new_means_recently_opened_not_first_scanned():
    from datetime import UTC, datetime, timedelta

    from app.services.markets.views import _is_new

    now = datetime.now(UTC)
    ago = lambda **kw: (now - timedelta(**kw)).isoformat()  # noqa: E731
    first_scan = now - timedelta(days=2)
    # The employer's date decides when there is one.
    assert _is_new(ago(days=2), ago(hours=1), first_scan)
    assert not _is_new(ago(days=40), ago(hours=1), first_scan)
    # Undated: the first scan's postings were already open; later ones are new.
    assert not _is_new(None, (first_scan + timedelta(minutes=5)).isoformat(), first_scan)
    assert _is_new(None, ago(hours=3), first_scan)
    assert not _is_new(None, ago(days=9), None)


def test_posting_dates_in_english_month_format_parse():
    from app.services.job_discover.job_verification_engine import parse_posting_date

    assert parse_posting_date("October 3, 2026")[0] == "2026-10-03T00:00:00+00:00"
    assert parse_posting_date("Oct 03, 2026")[0] == "2026-10-03T00:00:00+00:00"
    assert parse_posting_date("Posted 3 Days Ago")[0] is None


async def _detect(handler, company):
    async with _client(handler) as client:
        return await detect(client, company, browser=None)


# ── Enumeration and failure != zero ─────────────────────────────────────────


GREENHOUSE_JOBS = {
    "jobs": [
        {"id": 1, "title": "Senior Software Engineer, Platform", "location": {"name": "Seattle, WA"}, "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1", "updated_at": "2026-09-30T00:00:00Z", "content": "Build distributed systems"},
        {"id": 2, "title": "Software Engineer II", "location": {"name": "Seattle, WA"}, "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2", "updated_at": "2026-09-30T00:00:00Z", "content": ""},
        {"id": 3, "title": "Senior Software Engineer", "location": {"name": "New York, NY"}, "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3", "updated_at": "2026-09-30T00:00:00Z", "content": ""},
    ]
}
ACME = {"id": "acme", "name": "Acme", "career": {"provider": "greenhouse", "config": {"slug": "acme"}, "sourceType": "ATS_API"}}


def test_enumeration_counts_total_market_and_relevant():
    async def run():
        async with _client(lambda r: httpx.Response(200, json=GREENHOUSE_JOBS)) as client:
            return await enumerate_company(client, ACME, get_market("seattle"))

    result = asyncio.run(run())
    assert result.ok
    assert result.counts()["totalOpen"] == 3
    assert result.counts()["inMarket"] == 2
    assert [j["title"] for j in result.relevant_jobs] == ["Senior Software Engineer, Platform"]
    assert result.relevant_jobs[0]["companyName"] == "Acme"


def test_failed_read_is_not_zero_jobs():
    async def run():
        async with _client(lambda r: httpx.Response(500)) as client:
            return await enumerate_company(client, ACME, get_market("seattle"))

    failed = asyncio.run(run())
    assert failed.ok is False and failed.total_open is None and failed.error

    company = {"id": "acme", "name": "Acme", "career": {"health": "HEALTHY", "lastSuccessAt": "2020-01-01T00:00:00+00:00"}}
    state: dict[str, Any] = {"companies": {"acme": {"counts": {"totalOpen": 12, "relevant": 3}, "relevantKeys": ["a"], "lastSuccessAt": "x"}}}
    refresh.apply_enumeration(company, failed)
    entry = refresh.record_scan(state, company, failed, "run-1")
    assert company["career"]["health"] == "FAILED"
    assert status_bucket(company["career"]) == "failed"
    assert entry["counts"] == {"totalOpen": 12, "relevant": 3}  # last good counts kept
    assert entry["ok"] is False


def test_empty_board_is_healthy_zero():
    async def run():
        async with _client(lambda r: httpx.Response(200, json={"jobs": []})) as client:
            return await enumerate_company(client, ACME, get_market("seattle"))

    result = asyncio.run(run())
    assert result.ok and result.total_open == 0
    company: dict[str, Any] = {"id": "acme", "name": "Acme", "career": {}}
    refresh.apply_enumeration(company, result)
    assert company["career"]["health"] == "HEALTHY"


def test_nearly_empty_board_found_by_name_is_degraded_not_healthy():
    from app.services.markets.enumerate import Enumeration
    from app.services.markets.refresh import apply_enumeration

    def scan(career, total):
        result = Enumeration(ok=True, provider="smartrecruiters", total_open=total)
        return apply_enumeration({"career": dict(career)}, result)["career"]

    side = {"method": "ats_probe", "urlSource": "seed", "url": "https://jobs.bytedance.example/", "provider": "smartrecruiters"}
    assert scan(side, 2)["health"] == "DEGRADED"
    assert "2 postings" in scan(side, 2)["failureReason"]
    assert scan(side, 40)["health"] == "HEALTHY"
    # The page itself linked the board: a small board is just a small company.
    assert scan({**side, "method": "html_embed"}, 2)["health"] == "HEALTHY"


def test_status_buckets_keep_manual_separate_from_broken():
    assert status_bucket({"sourceType": "MANUAL", "health": "UNVERIFIED"}) == "manual"
    assert status_bucket({"sourceType": "BLOCKED", "health": "UNVERIFIED"}) == "manual"
    assert status_bucket({"sourceType": "ATS_API", "health": "FAILED"}) == "failed"
    assert status_bucket({"sourceType": "ATS_API", "health": "HEALTHY"}) == "healthy"
    assert status_bucket({"sourceType": "ATS_API", "health": "UNVERIFIED"}) == "pending"


# ── Dedup ───────────────────────────────────────────────────────────────────


def test_same_source_requisitions_with_boilerplate_descriptions_stay_separate():
    from app.services.job_discover.dedup import cross_source_deduplicate

    boiler = "Company Overview Acme brings agreements to life. " * 10
    base = {"companyName": "Acme", "location": "Seattle, WA", "description": boiler, "source": "jibe"}
    jobs = [
        {**base, "id": "a", "externalId": "100", "title": "Senior Software Engineer", "url": "https://acme.example/jobs/100"},
        {**base, "id": "b", "externalId": "200", "title": "Software Engineer", "url": "https://acme.example/jobs/200"},
    ]
    assert len(cross_source_deduplicate(jobs)) == 2


def test_aggregator_copy_merges_into_the_official_posting():
    from app.services.job_discover.dedup import cross_source_deduplicate

    official = {"id": "a", "companyName": "Acme", "title": "Senior Software Engineer", "location": "Seattle, WA",
                "url": "https://job-boards.greenhouse.io/acme/jobs/1", "source": "greenhouse", "description": "x"}
    indeed = {"id": "b", "companyName": "Acme", "title": "Senior Software Engineer", "location": "Seattle, WA",
              "url": "https://www.indeed.com/viewjob?jk=1", "source": "indeed", "description": "y"}
    assert len(cross_source_deduplicate([official, indeed])) == 1


# ── Refresh orchestration ───────────────────────────────────────────────────


def test_canonical_job_keeps_every_listed_location():
    from app.services.job_discover.store import _normalize_scraped_job

    job = _normalize_scraped_job({
        "company": "Acme", "title": "Senior Software Engineer", "location": "San Francisco, CA",
        "locations": ["San Francisco, CA", "Seattle, WA"], "url": "https://jobs.ashbyhq.com/acme/1", "source": "ashby",
    })
    assert job["location"] == "San Francisco, CA"
    assert job["locations"] == ["Seattle, WA"]


def test_rescan_backfills_locations_and_posting_date_on_an_existing_job():
    from app.services.job_discover.dedup import merge_job_records

    existing = {"id": "j1", "source": "ashby", "sourcePriority": 95, "location": "San Francisco, CA", "locations": [], "postingDate": None}
    incoming = {"id": "j1", "source": "ashby", "sourcePriority": 95, "location": "San Francisco, CA", "locations": ["Seattle, WA"],
                "postingDate": "2026-10-03T00:00:00+00:00", "postingDateConfidence": "MEDIUM"}
    merged = merge_job_records(existing, incoming)
    assert merged["locations"] == ["Seattle, WA"]
    assert merged["postingDate"] == "2026-10-03T00:00:00+00:00"


def test_refresh_skips_fresh_companies_unless_forced(market_db, monkeypatch):
    _import(market_db)
    with session_scope() as db:
        for company in registry.list_companies(db, "seattle"):
            company["career"].update({"provider": "greenhouse", "config": {"slug": "acme"}, "sourceType": "ATS_API",
                                      "detectedAt": "2999-01-01T00:00:00+00:00", "detectedUrl": company["career"].get("url") or ""})
            if company["id"] != "acme-cloud":
                company["career"].update({"provider": None, "sourceType": "MANUAL"})
            registry.save_company(db, company)

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=GREENHOUSE_JOBS)

    async def run(force: bool):
        async with _client(handler) as client:
            return await refresh.run_refresh("seattle", force=force, allow_browser=False, client=client)

    monkeypatch.setattr(refresh, "needs_detection", lambda company, market, force: False)
    first = asyncio.run(run(False))
    assert first["succeeded"] == 1 and first["skipped"] == 0
    second = asyncio.run(run(False))
    assert second["succeeded"] == 0 and second["skipped"] == 1
    third = asyncio.run(run(True))
    assert third["succeeded"] == 1

    with session_scope() as db:
        state = registry.get_scan_state(db, "seattle")
    entry = state["companies"]["acme-cloud"]
    assert entry["counts"]["relevant"] == 1
    assert state["lastRun"]["runId"] == third["runId"]


# ── API ─────────────────────────────────────────────────────────────────────


def test_api_contract(market_db, monkeypatch):
    from app.main import app

    _import(market_db)
    client = TestClient(app)

    markets = client.get("/markets").json()["markets"]
    assert any(m["id"] == "seattle" and m["companies"] == 5 for m in markets)

    overview = client.get("/markets/seattle").json()
    assert set(overview) >= {"market", "pulse", "companies", "opportunities", "health", "refresh"}
    assert [c["priority"] for c in overview["companies"]] == sorted(c["priority"] for c in overview["companies"])
    widgets = next(c for c in overview["companies"] if c["id"] == "widgets")
    assert widgets["h1b"]["label"] == "Moderate"
    assert widgets["h1b"]["note"].startswith("Company-level")
    assert widgets["jobs"]["state"] == "unknown" and widgets["jobs"]["totalOpen"] is None

    detail = client.get("/markets/seattle/companies/amazon").json()
    assert detail["name"] == "Amazon" and "opportunities" in detail

    assert client.get("/markets/nowhere").status_code == 404
    assert client.get("/markets/seattle/companies/not-a-company").status_code == 404
    assert "needsAttention" in client.get("/markets/seattle/health").json()
    assert client.get("/markets/seattle/refresh").json()["marketId"] == "seattle"
