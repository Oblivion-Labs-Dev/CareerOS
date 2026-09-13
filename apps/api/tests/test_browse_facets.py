from app.services.job_discover.browse_filters import filter_options, filter_facets
from app.services.diagnostic_series import build_series
from datetime import datetime, timezone

JOBS = [
 {"title":"Senior Product Manager", "companyName":"Acme, Inc", "location":"Remote", "description":"5+ years of experience"},
 {"title":"Business Intelligence Engineer", "companyName":"Orbit", "location":"Hybrid", "description":"3 years experience"},
 {"title":"Software Engineer", "companyName":"North", "location":"Seattle"},
]

def test_options_are_only_database_values():
    options = filter_options(JOBS)
    assert set(options["titles"]) == {j["title"] for j in JOBS}
    assert "BIE" not in options["titles"]
    assert {"pm", "bie", "swe"} <= {o["value"] for o in options["specialties"]}
    assert "hw" not in {o["value"] for o in options["specialties"]}
    assert "onsite" not in options["workModes"]
    assert filter_options([])["titles"] == []
    assert filter_options([])["specialties"] == []


def test_multi_choice_or_and_between_groups():
    assert len(filter_facets(JOBS, specialties="pm,bie")) == 2
    assert filter_facets(JOBS, specialties="pm,bie", seniorities="senior", work_modes="remote", experience="3-5", companies='["Acme, Inc"]') == [JOBS[0]]
    assert filter_facets(JOBS, experience="unspecified", work_modes="unspecified") == [JOBS[2]]
    assert filter_facets(JOBS, specialties="bie") == [JOBS[1]]


def test_series_boundaries_missing_durations_and_future_records():
    now=datetime(2026,9,12,12,tzinfo=timezone.utc)
    jobs=[{"status":"SUBMITTED","updatedAt":"2026-09-12T11:00:00Z","checkpointHistory":[{"timestamp":"2026-09-12T10:59:00Z"},{"timestamp":"2026-09-12T11:00:00Z"}]}, {"status":"FAILED","updatedAt":"2026-09-12T12:00:00Z"}, {"status":"FAILED","updatedAt":"2026-09-12T12:01:00Z"}, {"status":"SUBMITTED","updatedAt":"bad"}]
    result=build_series(jobs,"1h",now)
    assert len(result["buckets"]) == 12
    assert result["buckets"][0]["submitted"] == 1
    assert result["buckets"][0]["durationSec"] == 60
    assert result["buckets"][-1]["failed"] == 1
    assert result["buckets"][-1]["durationSec"] is None
    assert sum(b["failed"] for b in result["buckets"]) == 1
    assert all(b["durationSec"] is None for b in build_series([],"7d",now)["buckets"])


def test_saved_search_round_trip():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.application_assistant.browse_searches import router
    app=FastAPI()
    app.include_router(router)
    client=TestClient(app)
    payload={"name":"Product and BI", "filters":{"specialties":["pm","bie"],"companies":["Acme, Inc"],"experience":"3-5"}}
    response=client.post("/application-assistant/browse-searches",json=payload)
    assert response.status_code == 200
    record=next(r for r in response.json()["searches"] if r["name"] == payload["name"])
    assert record["filters"]["companies"] == ["Acme, Inc"]
    payload["name"]="My roles"
    assert client.put(f"/application-assistant/browse-searches/{record['id']}",json=payload).status_code == 200
    assert any(r["name"] == "My roles" for r in client.get("/application-assistant/browse-searches").json()["searches"])
    assert client.delete(f"/application-assistant/browse-searches/{record['id']}").status_code == 200
    assert client.post("/application-assistant/browse-searches",json={"name":"   ","filters":{}}).status_code == 422


def test_options_exclude_queued_and_dismissed(monkeypatch):
    from app.routers import api
    from app.services.application_assistant import scraper_import
    monkeypatch.setattr(api.job_discover,"get_snapshot",lambda db:{"jobs":[{**JOBS[0],"id":"available"},{**JOBS[1],"id":"queued"},{**JOBS[2],"id":"hidden"}],"dismissedIds":["hidden"]})
    monkeypatch.setattr(scraper_import,"get_synced_scraper_job_ids",lambda db:{"queued"})
    result=api.browse_filter_options(None)
    assert result["titles"] == ["Senior Product Manager"]
    assert result["companies"] == ["Acme, Inc"]


def test_diagnostics_do_not_invent_timings_or_unrelated_run_jobs(monkeypatch):
    from app.routers import diagnostic
    monkeypatch.setattr(diagnostic,"list_entities",lambda db,kind:[])
    metrics=diagnostic.get_autopilot_metrics(period="24h",db=None)
    assert metrics["avgApplicationDurationSec"] is None
    assert metrics["avgResumeTailoringDurationSec"] is None
    assert metrics["jobsDiscovered"] == 0
    assert diagnostic.get_run_timeline("missing-run",db=None)["timeline"] == []
    monkeypatch.setattr(diagnostic,"list_entities",lambda db,kind:[{"lastAttemptRunId":"different-run","status":"SUBMITTED","checkpointHistory":[{"step":"SUBMIT","timestamp":"2026-09-12T12:00:00Z"}]}])
    assert diagnostic.get_run_timeline("missing-run",db=None)["timeline"] == []
