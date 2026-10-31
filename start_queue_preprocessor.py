import sys
sys.path.insert(0, 'apps/api')

import asyncio
from app.services.application_assistant.queue_preprocessor import get_preprocessor

async def main():
    preprocessor = get_preprocessor()
    print(f"Preprocessor running: {preprocessor.is_running()}")
    
    result = await preprocessor.start()
    print(f"Start result: {result}")
    
    # Wait and check stats
    for i in range(10):
        await asyncio.sleep(5)
        from app.services.application_assistant.queue_preprocessor import get_stats
        stats = get_stats()
        print(f"Stats: running={stats.get('running')}, cycles={stats.get('cycles')}, jobsEnqueued={stats.get('jobsEnqueued')}, queueSize={stats.get('queueSize')}, lastError={stats.get('lastError')}")
        if stats.get('cycles', 0) > 0:
            break

asyncio.run(main())