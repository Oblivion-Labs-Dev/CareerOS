import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.autopilot_runner import AutopilotRunner
import asyncio

async def main():
    runner = AutopilotRunner.get_instance()
    
    # Configure for broader board support and higher caps
    print("Starting autopilot with relaxed settings...")
    run = await runner.start(options={
        "targetProcessCount": 100,
        "minMatchScore": 50.0,
        "tierGuardrails": True,
        "submittableBoardsOnly": True,   # Only boards we know
        "submittableBoardsStrict": False, # <-- RELAXED: try boards even if not in guaranteed list
        "selfHealing": True,
        "aiModel": "qwen3:4b-instruct",
        "tailoringMode": "honest"
    })
    print(f"Started: {run.get('id')}")
    
    # Monitor for a bit
    for i in range(60):
        await asyncio.sleep(10)
        with session_scope() as db:
            from app.services.application_assistant.persistence import get_autopilot_run
            run = get_autopilot_run(db, runner.active_run_id)
            if run:
                print(f"  [{i*10}s] Status: {run.get('status')}, Processed: {run.get('processedCount')}/{run.get('targetProcessCount')}, Submitted: {run.get('submittedCount')}, Queue: {run.get('queueSize', '?')}")
                if run.get('status') in ('STOPPED', 'PAUSED', 'COMPLETED'):
                    print(f"Run {run.get('status')}: {run.get('submittedCount')} submitted, {run.get('stagedCount')} staged")
                    break

asyncio.run(main())