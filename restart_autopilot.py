import sys
sys.path.insert(0, 'apps/api')

from app.services.application_assistant.autopilot_runner import AutopilotRunner
import asyncio

async def main():
    runner = AutopilotRunner.get_instance()
    print("Stopping current run...")
    result = await runner.stop()
    print(f"Stop result: {result}")
    
    # Recover stranded jobs
    from app.services.application_assistant.autopilot_runner import recover_stranded_applying_jobs
    recovered = await asyncio.to_thread(recover_stranded_applying_jobs)
    print(f"Recovered: {recovered}")
    
    # Start new run
    print("\nStarting new run...")
    run = await runner.start(options={
        "targetProcessCount": 100,
        "minMatchScore": 50.0,
        "tierGuardrails": True,
        "submittableBoardsOnly": True,
        "submittableBoardsStrict": False,
        "selfHealing": True,
        "aiModel": "qwen3:4b-instruct",
        "tailoringMode": "honest"
    })
    print(f"Started: {run}")

asyncio.run(main())