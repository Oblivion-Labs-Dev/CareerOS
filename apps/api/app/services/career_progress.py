"""Single-user career progress. Evidence-derived milestones, explicit task check-ins.

No XP, inferred email outcomes, submission mutations, or penalized streaks.
Week boundaries use the saved IANA timezone; task IDs make retries idempotent.
"""
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app.db.store import get_entity, get_kv, list_entities, set_kv, upsert_entity
from app.services.application_assistant.application_journey import assess_receipt
from app.services.tracker.pipeline import _parse_dt

QUESTS = [
    {"id": "resume", "title": "Polish your story", "detail": "Review your resume and refine one achievement with a concrete example.", "href": "/profile", "action": "Open resume & profile", "symbol": "✦"},
    {"id": "shortlist", "title": "Choose with intention", "detail": "Review your shortlist and identify the roles you actually want to pursue.", "href": "/applications?tab=queued", "action": "Review your shortlist", "symbol": "◎"},
    {"id": "prepare", "title": "Practice your next conversation", "detail": "Rehearse one interview story aloud: the situation, your action, and the result.", "href": "/applications?tab=pipeline", "action": "Open your pipeline", "symbol": "◇"},
]


def week_key(date, zone):
    local = date.astimezone(ZoneInfo(zone)).date()
    return (local - timedelta(days=local.weekday())).isoformat()


def record_once(db, identifier, payload):
    existing = get_entity(db, "career_progress_event", identifier)
    if existing:
        return existing
    try:
        with db.begin_nested():
            return upsert_entity(db, "career_progress_event", {**payload, "id": identifier})
    except IntegrityError:
        existing = get_entity(db, "career_progress_event", identifier)
        if existing:
            return existing
        raise


def preferences(db):
    return {"weeklyGoal": 3, "timezone": "UTC", **(get_kv(db, "career_progress_preferences") or {})}


def save_preferences(db, goal, timezone):
    ZoneInfo(timezone)
    set_kv(db, "career_progress_preferences", {"weeklyGoal": goal, "timezone": timezone})


def complete_quest(db, quest_id, week, now=None):
    now = now or datetime.now(UTC)
    if quest_id not in {q["id"] for q in QUESTS}:
        raise ValueError("Unknown quest")
    if week != week_key(now, preferences(db)["timezone"]):
        raise ValueError("A new week has started. Refresh before completing this quest.")
    return record_once(db, f"quest:{week}:{quest_id}", {"kind": "quest_completed", "questId": quest_id,
                       "week": week, "at": now.isoformat(), "source": "user_check_in"})


def progress_snapshot(db, now=None):
    now = now or datetime.now(UTC)
    prefs = preferences(db)
    zone = prefs["timezone"]
    week = week_key(now, zone)
    events = list_entities(db, "career_progress_event")
    completed = {e["questId"]: e for e in events if e.get("kind") == "quest_completed" and e.get("week") == week}
    receipts = get_kv(db, "autopilot_submission_receipts") or {}
    jobs = list_entities(db, "aa_autopilot_job")
    confirmed = [j for j in jobs if j.get("status") == "SUBMITTED" and assess_receipt(j, receipts.get(j["id"]))["state"] == "confirmed"]
    dates = sorted(date for j in confirmed if (date := _parse_dt(j.get("submittedAt"))) and date <= now)
    weekly = Counter(week_key(date, zone) for date in dates)
    daily = Counter(date.astimezone(ZoneInfo(zone)).date().isoformat() for date in dates)
    best_count = max(weekly.values(), default=0)
    best_weeks = sorted(key for key, count in weekly.items() if count == best_count)
    applications = {a["id"]: a for a in list_entities(db, "application")}
    linked = [(applications[j["applicationId"]], _parse_dt(j.get("submittedAt"))) for j in confirmed if j.get("applicationId") in applications]

    def earliest(field):
        values = [date for a, submitted in linked if submitted and (date := _parse_dt(a.get(field))) and submitted <= date <= now]
        return min(values).isoformat() if values else None

    quest_dates = sorted(e["at"] for e in events if e.get("kind") == "quest_completed" and e.get("at"))
    milestones = [
        {"id": "first_step", "title": "Intent into action", "description": "Your first completed career quest", "symbol": "✦", "earnedAt": quest_dates[0] if quest_dates else None},
        {"id": "first_submission", "title": "Out in the world", "description": "First dated submission with recorded ATS evidence", "symbol": "↗", "earnedAt": dates[0].isoformat() if dates else None},
        {"id": "first_reply", "title": "A conversation begins", "description": "First dated reply on a linked application", "symbol": "◌", "earnedAt": earliest("firstResponseAt")},
        {"id": "first_interview", "title": "Your seat at the table", "description": "First dated interview on a linked application", "symbol": "◇", "earnedAt": earliest("interviewAt")},
        {"id": "first_offer", "title": "A new chapter", "description": "First dated offer on a linked application", "symbol": "✧", "earnedAt": earliest("offerAt")},
    ]
    seen = {e.get("milestoneId") for e in events if e.get("kind") == "milestone_seen"}
    profile = get_kv(db, "profile") or {}
    return {"week": week, "preferences": prefs, "completedCount": len(completed),
            "goalReached": len(completed) >= prefs["weeklyGoal"],
            "player": {"name": profile.get("fullName") or "Your career", "specialty": profile.get("targetRole") or profile.get("currentTitle") or "Write your next chapter"},
            "quests": [{**q, "completedAt": completed.get(q["id"], {}).get("at")} for q in QUESTS],
            "milestones": [{**m, "seen": m["id"] in seen} for m in milestones],
            "records": {"confirmedTotal": len(confirmed), "datedConfirmed": len(dates), "bestWeekCount": best_count,
                        "bestWeek": best_weeks[-1] if best_weeks else None, "thisWeekCount": weekly[week],
                        "bestDayCount": max(daily.values(), default=0),
                        "bestDays": sorted(key for key, count in daily.items() if count == max(daily.values(), default=0))},
            "history": sorted([e for e in events if e.get("kind") == "quest_completed"], key=lambda e: e.get("at", ""), reverse=True)[:20]}


def acknowledge_milestone(db, milestone_id):
    milestone = next((m for m in progress_snapshot(db)["milestones"] if m["id"] == milestone_id and m["earnedAt"]), None)
    if not milestone:
        raise ValueError("This milestone has not been earned")
    return record_once(db, f"milestone-seen:{milestone_id}", {"kind": "milestone_seen", "milestoneId": milestone_id, "at": datetime.now(UTC).isoformat()})
