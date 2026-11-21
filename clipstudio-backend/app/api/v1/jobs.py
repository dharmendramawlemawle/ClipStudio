from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import EntityNotFoundException
from app.database import get_db
from app.models.job import ProcessingJob
from app.schemas.job import JobCreate, JobRead
from app.services.job_queue import job_queue

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/test", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def trigger_test_job(payload: dict | None = None) -> JobRead:
    """Convenience endpoint to launch an end-to-end verification test job."""
    job = await job_queue.create_job(
        job_type="test_job",
        entity_type="test",
        payload=payload or {"test_initiator": "verification_suite"},
    )
    return JobRead.model_validate(job)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(request: JobCreate) -> JobRead:
    """Submits a generic persistent job to the execution queue."""
    job = await job_queue.create_job(
        job_type=request.job_type,
        entity_type=request.entity_type,
        entity_id=request.entity_id,
        payload=request.payload,
    )
    return JobRead.model_validate(job)


@router.get("", response_model=list[JobRead])
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[JobRead]:
    """Retrieves all historical and active processing jobs, sorted newest first."""
    stmt = select(ProcessingJob).order_by(desc(ProcessingJob.created_at)).limit(limit)
    if status_filter:
        stmt = stmt.where(ProcessingJob.status == status_filter)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return [JobRead.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)) -> JobRead:
    """Fetches full metadata and status for a single job by UUID."""
    job = await db.get(ProcessingJob, job_id)
    if not job:
        raise EntityNotFoundException("ProcessingJob", job_id)
    return JobRead.model_validate(job)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """Attempts to cancel an active or queued job."""
    success = await job_queue.cancel_job(job_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found or not in a cancellable state.",
        )
    return {"message": f"Cancellation requested for job {job_id}."}
