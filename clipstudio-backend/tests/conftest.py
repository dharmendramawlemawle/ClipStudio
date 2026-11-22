import asyncio
import pytest
from app.services.job_queue import job_queue

@pytest.fixture(autouse=True)
async def cleanup_background_tasks():
    yield
    # Safely cancel or await any pending background tasks before the event loop closes
    if job_queue._active_tasks:
        tasks = [t for t in job_queue._active_tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        job_queue._active_tasks.clear()
