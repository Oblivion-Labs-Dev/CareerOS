"""The jobs list classifies every job (ATS, failure reason) on each request.

That work dominated /autopilot/jobs latency, so it is memoized per job-list
object. These tests pin that it runs once per list and again when the read
cache hands out a new list after a write.
"""
from app.routers.application_assistant import autopilot
from app.services import diagnostic_outcomes


def _count_reason_calls(monkeypatch):
    calls = {"n": 0}
    real = diagnostic_outcomes.reason_category

    def counting(job):
        calls["n"] += 1
        return real(job)

    monkeypatch.setattr(diagnostic_outcomes, "reason_category", counting)
    monkeypatch.setattr(autopilot, "_job_labels_cache", {})
    return calls


def test_labels_computed_once_per_list(monkeypatch):
    calls = _count_reason_calls(monkeypatch)
    jobs = [
        {"id": "a", "status": "FAILED", "url": "https://boards.greenhouse.io/x/jobs/1", "error": "timeout"},
        {"id": "b", "status": "QUEUED", "url": "https://jobs.lever.co/x/2"},
    ]
    ats1, reasons1 = autopilot._job_labels(jobs)
    ats2, reasons2 = autopilot._job_labels(jobs)
    assert calls["n"] == 2
    assert (ats1, reasons1) == (ats2, reasons2)
    assert set(ats1) == {id(j) for j in jobs}


def test_new_list_recomputes(monkeypatch):
    calls = _count_reason_calls(monkeypatch)
    jobs = [{"id": "a", "status": "QUEUED", "url": "https://jobs.lever.co/x/2"}]
    autopilot._job_labels(jobs)
    fresh = [dict(jobs[0]), {"id": "c", "status": "QUEUED"}]
    _, reasons = autopilot._job_labels(fresh)
    assert calls["n"] == 3
    assert set(reasons) == {id(j) for j in fresh}


def test_refreshed_list_reuses_classification(monkeypatch):
    """The read cache rebuilds the list every few seconds even when nothing
    changed; the regex scans must not rerun for texts and URLs already seen."""
    from app.services.application_assistant import ats_plugin_reference

    monkeypatch.setattr(autopilot, "_job_labels_cache", {})
    job = {"id": "z", "status": "FAILED", "url": "https://boards.greenhouse.io/memo/jobs/9",
           "lastError": "memo-test unique error text 7f3a"}
    autopilot._job_labels([job])
    known_before = diagnostic_outcomes._known_category.cache_info()
    ats_before = ats_plugin_reference.ats_from_url.cache_info()
    autopilot._job_labels([dict(job)])
    assert diagnostic_outcomes._known_category.cache_info().misses == known_before.misses
    assert ats_plugin_reference.ats_from_url.cache_info().misses == ats_before.misses
