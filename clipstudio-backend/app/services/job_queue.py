import asyncio
import json
import time
from datetime import datetime, timezone
from sqlalchemy import select, update
from app.api.websockets.connection import ws_manager
from app.config import settings
from app.core.logging import logger
from app.database import async_session_factory
from app.models.job import ProcessingJob
from app.services.ffmpeg import (
    FFmpegExecutionException,
    FFmpegExecutionResult,
    FFmpegProgress,
    FFmpegRunner,
)

TERMINAL_JOB_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


class JobQueueService:
    """Persistent in-process durable job queue with SQLite backing and WebSocket telemetry."""

    def __init__(self):
        self._semaphore: asyncio.Semaphore | None = None
        self._current_loop = None
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._active_runners: dict[str, FFmpegRunner] = {}
        self._cancellation_requested: set[str] = set()

    def _get_semaphore(self) -> asyncio.Semaphore:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._semaphore is None or self._current_loop != loop:
            self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_HEAVY_JOBS)
            self._current_loop = loop
        return self._semaphore

    async def reconcile_interrupted_jobs(self):
        """Scans database on startup and marks stale running/queued jobs as failed."""
        async with async_session_factory() as session:
            stmt = select(ProcessingJob).where(
                ProcessingJob.status.in_(["running", "queued"])
            )
            result = await session.execute(stmt)
            stale_jobs = result.scalars().all()

            if stale_jobs:
                logger.warning(f"Reconciling {len(stale_jobs)} interrupted job(s) from previous server run...")
                for job in stale_jobs:
                    job.status = "failed"
                    job.error_message = "Job interrupted by server shutdown or restart."
                    job.completed_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("Interrupted jobs reconciliation complete.")
            else:
                logger.info("No interrupted jobs found during startup reconciliation.")

    async def create_job(
        self,
        job_type: str,
        entity_type: str = "test",
        entity_id: str | None = None,
        payload: dict | None = None,
    ) -> ProcessingJob:
        """Creates and persists a new job record, then schedules execution."""
        async with async_session_factory() as session:
            job = ProcessingJob(
                job_type=job_type,
                entity_type=entity_type,
                entity_id=entity_id,
                status="queued",
                progress_percent=0.0,
                current_step="Queued in scheduler",
                result_data=json.dumps(payload) if payload else None,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

            job_id = job.id

        # Broadcast initial queued status
        await ws_manager.broadcast_job_progress(
            job_id=job_id,
            status="queued",
            progress_percent=0.0,
            current_step="Queued in scheduler",
            message=f"Job {job_type} has been queued.",
        )

        # Dispatch async execution task
        task = asyncio.create_task(self._execute_job_wrapper(job_id, job_type, payload))
        self._active_tasks[job_id] = task

        # Re-fetch fresh model to return
        async with async_session_factory() as session:
            return await session.get(ProcessingJob, job_id)

    async def _update_job_progress(
        self,
        job_id: str,
        status: str,
        progress_percent: float,
        current_step: str,
        message: str,
        result_data: dict | None = None,
        error_message: str | None = None,
    ):
        """Updates persistent database record and emits WebSocket broadcast."""
        now = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if not job:
                return

            # CS-AUDIT-2B1-001: Prevent stale progress updates from reverting terminal job states
            if job.status in TERMINAL_JOB_STATES and status != job.status:
                logger.debug(
                    f"Rejecting stale progress update (status='{status}') for job {job_id} "
                    f"already in terminal state '{job.status}'."
                )
                return

            job.status = status
            job.progress_percent = progress_percent
            job.current_step = current_step
            if status == "running" and not job.started_at:
                job.started_at = now
            if status in TERMINAL_JOB_STATES:
                job.completed_at = now
            if result_data:
                job.result_data = json.dumps(result_data)
            if error_message:
                job.error_message = error_message

            await session.commit()

        # Emit over WebSocket (non-blocking for DB)
        await ws_manager.broadcast_job_progress(
            job_id=job_id,
            status=status,
            progress_percent=progress_percent,
            current_step=current_step,
            message=message,
        )

    async def _execute_job_wrapper(self, job_id: str, job_type: str, payload: dict | None):
        """Wraps job execution with semaphore concurrency control and error handling."""
        try:
            async with self._get_semaphore():
                if job_id in self._cancellation_requested:
                    await self._update_job_progress(
                        job_id=job_id,
                        status="cancelled",
                        progress_percent=0.0,
                        current_step="Cancelled before execution",
                        message="Job was cancelled while queued.",
                    )
                    return

                await self._update_job_progress(
                    job_id=job_id,
                    status="running",
                    progress_percent=0.0,
                    current_step="Started execution",
                    message=f"Beginning execution of {job_type}.",
                )

                if job_type == "test_job":
                    await self._run_test_job(job_id, payload)
                elif job_type == "ffmpeg_job":
                    args = payload.get("args", []) if payload else []
                    duration = payload.get("total_duration_seconds") if payload else None
                    desc = payload.get("description", "FFmpeg Processing") if payload else "FFmpeg Processing"
                    timeout = payload.get("timeout_seconds") if payload else None
                    await self.run_ffmpeg_job(
                        job_id=job_id,
                        cmd_args=args,
                        total_duration_seconds=duration,
                        step_description=desc,
                        timeout_seconds=timeout,
                    )
                else:
                    # Generic placeholder for future phases
                    await asyncio.sleep(1)
                    await self._update_job_progress(
                        job_id=job_id,
                        status="completed",
                        progress_percent=100.0,
                        current_step="Completed",
                        message=f"Job {job_type} finished successfully.",
                    )

        except asyncio.CancelledError:
            logger.info(f"Job {job_id} was cancelled.")
            await self._update_job_progress(
                job_id=job_id,
                status="cancelled",
                progress_percent=0.0,
                current_step="Cancelled",
                message="Job execution was aborted by user request.",
            )
        except Exception as exc:
            logger.error(f"Error executing job {job_id}: {exc}", exc_info=True)
            await self._update_job_progress(
                job_id=job_id,
                status="failed",
                progress_percent=0.0,
                current_step="Failed with error",
                message=str(exc),
                error_message=str(exc),
            )
        finally:
            self._active_tasks.pop(job_id, None)
            self._cancellation_requested.discard(job_id)

    async def _run_test_job(self, job_id: str, payload: dict | None):
        """Simulates a multi-stage workload verifying progress persistence and WebSocket broadcast."""
        steps = [
            ("Initializing test workspace environment", 20.0),
            ("Synthesizing audio/video metadata mock stream", 40.0),
            ("Simulating local speech recognition pipeline", 65.0),
            ("Evaluating viral highlight scoring heuristics", 85.0),
            ("Assembling final verification summary", 100.0),
        ]

        for step_name, progress in steps:
            if job_id in self._cancellation_requested:
                raise asyncio.CancelledError()

            await asyncio.sleep(1.0)  # 1 second per step
            await self._update_job_progress(
                job_id=job_id,
                status="running",
                progress_percent=progress,
                current_step=step_name,
                message=f"Processing: {step_name} ({progress:.0f}%)",
            )

        # Mark finished
        await self._update_job_progress(
            job_id=job_id,
            status="completed",
            progress_percent=100.0,
            current_step="Completed",
            message="Test job successfully completed all execution stages.",
            result_data={
                "verified": True,
                "stages_passed": len(steps),
                "duration_seconds": len(steps) * 1.0,
            },
        )

    async def run_ffmpeg_job(
        self,
        job_id: str,
        cmd_args: list[str],
        total_duration_seconds: float | None = None,
        step_description: str = "FFmpeg Processing",
        timeout_seconds: float | None = None,
    ) -> FFmpegExecutionResult:
        """Executes an FFmpeg command within a managed job lifecycle with progress streaming."""
        if job_id in self._cancellation_requested:
            raise asyncio.CancelledError()

        runner = FFmpegRunner()
        self._active_runners[job_id] = runner

        last_broadcast_time = 0.0
        last_broadcast_pct = -1.0

        async def on_ffmpeg_progress(prog: FFmpegProgress):
            nonlocal last_broadcast_time, last_broadcast_pct
            if job_id in self._cancellation_requested:
                raise asyncio.CancelledError()

            now = time.monotonic()
            pct = prog.percent if prog.percent is not None else 0.0
            is_end = (prog.progress_status == "end")

            # Throttle progress updates to avoid SQLite lock contention
            if is_end or (now - last_broadcast_time >= 0.3) or (abs(pct - last_broadcast_pct) >= 1.0):
                last_broadcast_time = now
                last_broadcast_pct = pct
                speed_text = f" ({prog.speed_str})" if prog.speed_str and prog.speed_str != "N/A" else ""
                step_text = f"{step_description} [{prog.out_time_str}]"
                msg = f"Processed time: {prog.out_time_str}{speed_text}"
                await self._update_job_progress(
                    job_id=job_id,
                    status="running",
                    progress_percent=pct,
                    current_step=step_text,
                    message=msg,
                )

        try:
            result = await runner.run(
                args=cmd_args,
                total_duration_seconds=total_duration_seconds,
                progress_callback=on_ffmpeg_progress,
                timeout_seconds=timeout_seconds,
            )

            if not result.success:
                raise FFmpegExecutionException(
                    result.error_message or "FFmpeg execution failed.",
                    returncode=result.returncode,
                    stderr_tail=result.stderr,
                )

            await self._update_job_progress(
                job_id=job_id,
                status="completed",
                progress_percent=100.0,
                current_step="Completed",
                message="FFmpeg processing completed successfully.",
                result_data={
                    "returncode": result.returncode,
                    "duration_seconds": result.duration_seconds,
                    "pid": result.pid,
                },
            )
            return result
        finally:
            self._active_runners.pop(job_id, None)

    async def cancel_job(self, job_id: str) -> bool:
        """Requests cancellation for an active or queued job."""
        if job_id in self._active_tasks:
            self._cancellation_requested.add(job_id)
            task = self._active_tasks[job_id]
            task.cancel()
            return True

        # If already queued in DB but not active
        async with async_session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job and job.status in ["queued", "running"]:
                job.status = "cancelled"
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = "Cancelled by user request."
                await session.commit()
                await ws_manager.broadcast_job_progress(
                    job_id=job_id,
                    status="cancelled",
                    progress_percent=job.progress_percent,
                    current_step="Cancelled",
                    message="Job was cancelled.",
                )
                return True
        return False

    def get_active_job_count(self) -> int:
        self._active_tasks = {
            jid: t for jid, t in self._active_tasks.items() if not t.done()
        }
        return len(self._active_tasks)

    async def cancel_all_active_jobs(self) -> None:
        """Cancels all active jobs (used during test teardown or graceful shutdown)."""
        active_ids = list(self._active_tasks.keys())
        for jid in active_ids:
            try:
                await self.cancel_job(jid)
            except Exception as exc:
                logger.warning(f"Error cancelling job {jid}: {exc}")


job_queue = JobQueueService()
