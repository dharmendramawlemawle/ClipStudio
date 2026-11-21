from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.schemas.health import HealthResponse
from app.services.job_queue import job_queue

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def check_health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Verifies backend API, SQLite WAL database, and active runtime status."""
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"unhealthy: {exc}"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        timestamp=datetime.now(timezone.utc),
        database=db_status,
        active_jobs=job_queue.get_active_job_count(),
        hardware={
            "platform": "Windows",
            "cpu_threads_configured": settings.DEFAULT_CPU_THREADS,
            "max_concurrent_heavy_jobs": settings.MAX_CONCURRENT_HEAVY_JOBS,
        },
    )
