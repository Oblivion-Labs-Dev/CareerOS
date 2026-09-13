"""Autonomous Night Batch Runner for CareerOS.

Runs 10 consecutive batches of 10 applications in Night Mode,
streaming progress, tracking receipts, detecting issues, and reporting milestones.
"""

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 output with instant unbuffered flushing
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True, write_through=True)

# Add API to path
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.config import settings
from app.services.auth import SESSION_COOKIE_NAME, create_session_token

BASE_URL = "http://127.0.0.1:4000"


def get_headers() -> dict[str, str]:
    token = create_session_token(settings.career_os_admin_username)
    return {
        "Content-Type": "application/json",
        "Cookie": f"{SESSION_COOKIE_NAME}={token}",
    }


def api_request(path: str, data: dict | None = None, method: str = "GET") -> dict:
    url = f"{BASE_URL}{path}"
    headers = get_headers()
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        print(f"API Error [{e.code}] on {path}: {err_msg}", flush=True)
        return {"error": err_msg, "status_code": e.code}
    except Exception as e:
        print(f"Request Error on {path}: {e}", flush=True)
        return {"error": str(e)}


def get_status() -> dict:
    return api_request("/application-assistant/autopilot/status")


def trigger_start_batch(batch_size: int = 10, min_match_score: float = 60.0) -> dict:
    payload = {
        "targetProcessCount": batch_size,
        "batchSize": batch_size,
        "concurrency": 1,
        "minMatchScore": min_match_score,
        "tierGuardrails": True,
        "selfHealing": True,
        "aiModel": "qwen3:4b-instruct",
    }
    return api_request("/application-assistant/autopilot/start", data=payload, method="POST")


def inspect_recent_jobs(since_iso: str) -> list[dict]:
    import sqlite3
    db_path = API_DIR / "data" / "career_os.db"
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, json_extract(payload, '$.company'), json_extract(payload, '$.title'),
                   json_extract(payload, '$.status'),
                   COALESCE(json_extract(payload, '$.submissionEvidence.receipt.receiptId'), json_extract(payload, '$.submissionReceipt.receiptId')),
                   json_extract(payload, '$.lastError'), json_extract(payload, '$.updatedAt')
            FROM entities
            WHERE entity_type='aa_autopilot_job'
              AND json_extract(payload, '$.updatedAt') >= ?
              AND json_extract(payload, '$.status') != 'QUEUED'
            ORDER BY json_extract(payload, '$.updatedAt') ASC
            """,
            (since_iso,),
        )
        results = []
        for r in cur.fetchall():
            results.append({
                "id": r[0],
                "company": r[1] or "Unknown",
                "title": r[2] or "Unknown",
                "status": r[3] or "UNKNOWN",
                "receipt": r[4],
                "error": r[5],
                "updatedAt": r[6],
            })
        conn.close()
        return results
    except Exception as e:
        print(f"Error inspecting recent jobs: {e}", flush=True)
        return []


def run_night_mode(total_batches: int = 10, batch_size: int = 10, start_batch_idx: int = 1):
    print("=" * 70, flush=True)
    print(f"  CAREEROS NIGHT MODE RUNNER: {total_batches} BATCHES OF {batch_size} JOBS", flush=True)
    print(f"  Starting at Batch {start_batch_idx} of {total_batches}", flush=True)
    print(f"  Target ATS: Greenhouse, Lever, Ashby", flush=True)
    print(f"  Priority: Senior SWE WA (+100) -> Senior SWE US (+70) -> Staff/Princ (+30-40)", flush=True)
    print(f"  Model: qwen3:4b-instruct | Min Match Floor: 60%", flush=True)
    print("=" * 70, flush=True)

    cumulative_submitted = 0
    cumulative_staged = 0
    cumulative_skipped = 0
    cumulative_failed = 0

    for batch_idx in range(start_batch_idx, total_batches + 1):
        batch_start_time = datetime.now(timezone.utc).isoformat()
        print(f"\n>>> STARTING BATCH {batch_idx} OF {total_batches} at {datetime.now().strftime('%H:%M:%S')} <<<", flush=True)

        # Check if a batch is genuinely actively being processed by a worker
        status = get_status()
        active_workers = sum(1 for w in (status.get("workers") or []) if w.get("status") not in ("idle", "done"))
        if status.get("running") and status.get("run") and active_workers > 0:
            run_info = status.get("run") or {}
            run_id = run_info.get("id", "unknown")
            print(f"Attached to active running worker for Batch {batch_idx}. Run ID: {run_id}", flush=True)
        else:
            start_res = trigger_start_batch(batch_size=batch_size, min_match_score=60.0)
            if start_res.get("error") or not start_res.get("success"):
                time.sleep(2)
                check_st = get_status()
                if check_st.get("running") and check_st.get("run"):
                    start_res = {"success": True, "run": check_st.get("run")}
                else:
                    print(f"Initial start for batch {batch_idx} returned {start_res}, attempting stop/recovery...", flush=True)
                    api_request("/application-assistant/autopilot/stop", method="POST")
                    time.sleep(2)
                    start_res = trigger_start_batch(batch_size=batch_size, min_match_score=60.0)
                    if not start_res.get("success"):
                        print(f"Abort batch {batch_idx}: could not start run.", flush=True)
                        continue

            run_info = start_res.get("run") or {}
            run_id = run_info.get("id", "unknown")
            print(f"Batch {batch_idx} launched. Run ID: {run_id}", flush=True)

        # 2. Monitor batch until completion
        last_processed = -1
        last_job_name = ""
        seen_logs = set()
        stuck_ticks = 0
        ticks = 0

        while True:
            time.sleep(5)
            ticks += 1
            status = get_status()
            if status.get("error"):
                print(f"  [Warn] Status check failed: {status.get('error')}", flush=True)
                continue

            is_running = status.get("running", False)
            run = status.get("run") or {}
            run_status = run.get("status", "")
            processed = run.get("processedCount", 0)
            target = run.get("targetProcessCount", batch_size)
            submitted = run.get("submittedCount", 0)
            staged = run.get("stagedCount", 0)
            skipped = run.get("skippedCount", 0)
            failed = run.get("failedCount", 0)

            active_job = status.get("activeJob") or {}
            job_name = f"{active_job.get('company', '')} - {active_job.get('title', '')}".strip(" -")
            step = active_job.get("step") or active_job.get("currentStep") or "Processing"

            # Log step changes
            if job_name and (job_name != last_job_name or processed != last_processed):
                print(f"  [{processed}/{target}] Active: [{job_name}] | Step: {step}", flush=True)
                last_job_name = job_name
                last_processed = processed
                stuck_ticks = 0
            else:
                stuck_ticks += 1

            # Print new activity logs
            recent_logs = status.get("recentLogs") or []
            for log in recent_logs:
                log_id = log.get("id") or log.get("timestamp") or str(log)
                if log_id not in seen_logs:
                    seen_logs.add(log_id)
                    msg = log.get("message", "")
                    lvl = log.get("level", "info").upper()
                    print(f"    [{lvl}] {msg}", flush=True)

            # Check if self-healing is in progress
            healing = status.get("selfHealing") or {}
            if healing.get("status") == "healing":
                print(f"  [Healing] Self-healing round {healing.get('currentRound')}/{healing.get('maxRounds')} in progress...", flush=True)

            # Allow at least 2 ticks (10s) before evaluating completion to bypass any status cache staleness
            if ticks >= 2:
                # Normal completion or stopped
                if not is_running or run_status in ("COMPLETED", "STOPPED", "DONE"):
                    print(f"\n--- Batch {batch_idx} Run Completed ({run_status or 'DONE'}) ---", flush=True)
                    print(f"Batch {batch_idx} Results: Processed={processed}/{target} | Submitted={submitted} | Staged={staged} | Skipped={skipped} | Failed={failed}", flush=True)
                    break

            # Watchdog: if stuck with no log change for > 600s (120 ticks), log warning and attempt recovery
            if stuck_ticks >= 120:
                print(f"  [Watchdog] Batch {batch_idx} has shown no progress for 600s. Attempting graceful stop and recovery...", flush=True)
                api_request("/application-assistant/autopilot/stop", method="POST")
                time.sleep(5)
                break

        # 3. Inspect jobs touched during this batch
        touched = inspect_recent_jobs(batch_start_time)
        print(f"\n--- Touch Summary for Batch {batch_idx} ({len(touched)} applications processed) ---", flush=True)
        batch_sub = 0
        batch_stg = 0
        batch_skp = 0
        batch_fld = 0
        for j in touched:
            stat = j["status"]
            co = j["company"]
            title = j["title"]
            rcpt = j["receipt"] or "No receipt"
            err = (str(j["error"]) if j["error"] else "").replace("\n", " ")[:120]
            if stat == "SUBMITTED":
                print(f"  [✓ SUBMITTED] {co} - {title} | Receipt: {rcpt}", flush=True)
                batch_sub += 1
            elif stat in ("STAGED", "NEEDS_REVIEW"):
                print(f"  [? STAGED]    {co} - {title} | Pending Human Review", flush=True)
                batch_stg += 1
            elif stat in ("MANUAL_REVIEW", "INELIGIBLE"):
                print(f"  [🛡 MANUAL]   {co} - {title} | Guardrail / Manual Review", flush=True)
                batch_skp += 1
            elif stat == "SKIPPED":
                print(f"  [- SKIPPED]   {co} - {title} | Reason: {err}", flush=True)
                batch_skp += 1
            elif stat in ("FAILED", "ERROR"):
                print(f"  [✗ FAILED]    {co} - {title} | Error: {err}", flush=True)
                batch_fld += 1

        cumulative_submitted += batch_sub
        cumulative_staged += batch_stg
        cumulative_skipped += batch_skp
        cumulative_failed += batch_fld

        print(f"\nCumulative after Batch {batch_idx}: Submitted={cumulative_submitted} | Staged={cumulative_staged} | Skipped={cumulative_skipped} | Failed={cumulative_failed}", flush=True)

        # Short cool-down between batches
        if batch_idx < total_batches:
            print("Cooling down 6 seconds before next batch...\n", flush=True)
            time.sleep(6)

    print("\n" + "=" * 70, flush=True)
    print("  ALL REQUESTED NIGHT MODE BATCHES FINISHED!", flush=True)
    print(f"  Total Batches: {total_batches}", flush=True)
    print(f"  Total Submitted: {cumulative_submitted}", flush=True)
    print(f"  Total Staged: {cumulative_staged}", flush=True)
    print(f"  Total Skipped: {cumulative_skipped}", flush=True)
    print(f"  Total Failed: {cumulative_failed}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    batches = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    cli_start_batch = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    run_night_mode(total_batches=batches, batch_size=size, start_batch_idx=cli_start_batch)
