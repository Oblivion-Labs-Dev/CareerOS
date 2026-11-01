import sys
sys.path.insert(0, 'apps/api')

import asyncio
from app.services.application_assistant.autopilot_runner import AutopilotRunner
from app.services.application_assistant.queue_preprocessor import get_preprocessor

async def main():
    runner = AutopilotRunner.get_instance()
    
    # Start queue preprocessor first
    print("Starting queue preprocessor...")
    preprocessor = get_preprocessor()
    await preprocessor.start()
    print("Queue preprocessor started")
    
    # Wait a bit for it to score some jobs
    print("Waiting for initial scoring...")
    await asyncio.sleep(10)
    
    # Check stats
    from app.services.application_assistant.queue_preprocessor import get_stats
    stats = get_stats()
    print(f"Queue preprocessor stats: {stats}")
    
    # Start autopilot with lower match floor (50%) for 100 jobs
    print("\nStarting autopilot run...")
    run = await runner.start(options={
        "targetProcessCount": 100,
        "minMatchScore": 50.0,  # Lower floor to allow more jobs through
        "tierGuardrails": True,
        "submittableBoardsOnly": True,
        "submittableBoardsStrict": True,
        "tailoringMode": "honest"
    })
    print(f"Autopilot started: {run}")
    
    # Monitor for a bit
    for i in range(30):
        await asyncio.sleep(10)
        status = runner.get_status(None)  # This needs a db session
        print(f"Status: {status.get('status')}, processed: {status.get('cumulative', {}).get('processed', 0)}, queue: {status.get('queueSize', 0)}")
        if status.get('status') in ('STOPPED', 'PAUSED', 'ERROR'):
            break

asyncio.run(main())