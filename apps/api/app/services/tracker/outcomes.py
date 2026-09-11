"""Dashboard projections with explicit cohorts and no inferred response dates."""
from datetime import UTC, datetime, timedelta
from statistics import median

from app.db.store import get_kv, list_entities
from app.services.application_assistant.application_journey import assess_receipt
from app.services.tracker.pipeline import _parse_dt


def summarize_outcomes(jobs, applications, receipts, now=None):
    now = now or datetime.now(UTC)
    start = now - timedelta(days=30)
    submitted = [j for j in jobs if j.get("status") == "SUBMITTED"]
    linked = {a["id"]: a for a in applications if a.get("id")}
    cohort = [j for j in submitted if (date := _parse_dt(j.get("submittedAt"))) and start <= date <= now]
    covered = responses = interviews = 0
    delays, events = [], []
    for job in submitted:
        at = _parse_dt(job.get("submittedAt"))
        if at and at <= now:
            events.append({"kind": "submissions", "at": at.isoformat(), "id": job["id"], "company": job.get("company"), "title": job.get("title")})
        app = linked.get(job.get("applicationId"), {})
        response = _parse_dt(app.get("firstResponseAt"))
        interview = _parse_dt(app.get("interviewAt"))
        for kind, date in (("responses", response), ("interviews", interview)):
            if at and date and at <= date <= now:
                events.append({"kind": kind, "at": date.isoformat(), "id": job["id"], "company": job.get("company"), "title": job.get("title")})
        if job not in cohort:
            continue
        covered += bool(app)
        if response and at <= response <= now:
            responses += 1
            delays.append((response - at).total_seconds() / 86400)
        if interview and at <= interview <= now:
            interviews += 1
    awaiting = sum(assess_receipt(j, receipts.get(j["id"]))["state"] != "confirmed" for j in submitted)
    unresolved = sum(j.get("status") in {"NEEDS_REVIEW", "STAGED", "MANUAL_REVIEW"} for j in jobs)
    upcoming = sum(bool((date := _parse_dt(a.get("interviewAt"))) and now <= date <= now + timedelta(days=7)) for a in applications)
    return {"totalSubmitted": len(submitted), "awaitingConfirmation": awaiting,
            "cohortSize": len(cohort), "linkedRecords": covered,
            "responses": responses, "interviews": interviews,
            "medianResponseDays": round(median(delays), 1) if delays else None,
            "datedSubmissions": sum(bool(_parse_dt(j.get("submittedAt"))) for j in submitted),
            "events": events, "windowDays": 30,
            "attention": [{"label": "Applications need your review", "count": unresolved, "href": "/applications?tab=all"},
                          {"label": "Submissions awaiting evidence", "count": awaiting, "href": "/applications?tab=submitted"},
                          {"label": "Interviews in the next 7 days", "count": upcoming, "href": "/applications?tab=pipeline"}]}


def dashboard_outcomes(db):
    return summarize_outcomes(list_entities(db, "aa_autopilot_job"), list_entities(db, "application"),
                              get_kv(db, "autopilot_submission_receipts") or {})
