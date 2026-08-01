"""One-off: print autofill saved state per application."""
from app.db.store import session_scope
from app.services.application_assistant.persistence import get_active_browser_run_for_app, list_application_drafts
from app.services.application_assistant.browser_replay import (
    has_persisted_autofill_plan,
    list_autofill_states,
    reconcile_stale_browser_run,
)
from app.services.application_assistant.worker import task_status

with session_scope() as db:
    drafts = [reconcile_stale_browser_run(db, d) for d in list_application_drafts(db)]
    for row in list_autofill_states(drafts):
        d = next(x for x in drafts if x.get("id") == row["applicationId"])
        run = get_active_browser_run_for_app(db, d["id"])
        prep = task_status(f"qwen_prep_{d['id']}")
        open_r = task_status(f"open_review_{d['id']}")
        print(
            row.get("companyName"),
            "| applicationId:", row["applicationId"],
            "| jobId:", row["jobId"],
            "| hasSavedAutofillState:", row["hasSavedAutofillState"],
            "| steps:", row["autofillStepCount"],
            "| status:", row.get("status"),
            "| browserRun:", (run or {}).get("status"),
            "| prep:", prep,
            "| open:", open_r,
            "| persisted:", has_persisted_autofill_plan(d),
        )
