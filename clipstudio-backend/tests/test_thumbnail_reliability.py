import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from app.config import settings
from app.database import async_session_factory
from app.main import app
from app.models.job import ProcessingJob
from app.models.upload import UploadSession
from app.models.video import ImportedVideo
from app.models.workspace import Workspace
from app.services.ffmpeg import FFmpegRunner
from app.services.job_queue import job_queue
from app.services.thumbnail import (
    ThumbnailException,
    generate_thumbnail,
    get_jpeg_dimensions,
    get_thumbnail_storage_paths,
)


@pytest.fixture(autouse=True)
async def cleanup_queue():
    """Ensure clean job queue before and after each test."""
    await job_queue.cancel_all_active_jobs()
    job_queue._fault_injection_fail_enqueue = False
    yield
    await job_queue.cancel_all_active_jobs()
    job_queue._fault_injection_fail_enqueue = False


async def create_synthetic_video(
    dest_path: Path,
    width: int = 640,
    height: int = 360,
    duration_seconds: float = 2.0,
) -> Path:
    """Generate a synthetic MP4 file with specific dimensions and duration."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    runner = FFmpegRunner()
    cmd = [
        "-f", "lavfi",
        "-i", f"color=c=navy:s={width}x{height}:d={duration_seconds}:r=25",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-y",
        str(dest_path),
    ]
    res = await runner.run(cmd)
    assert res.success is True, f"Failed to generate synthetic test video: {res.stderr}"
    assert dest_path.exists()
    return dest_path


# ==============================================================================
# Finding CS-REV-2B2-001: Enqueue Failure Recovery & Reconciliation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_complete_upload_retry_with_pending_thumbnail_enqueues_job(tmp_path):
    """Scenario 1: Completed upload retry with pending thumbnail and no active job recovers and enqueues thumbnail (Deadlock Regression Test)."""
    async def _run_test():
        ws_id = f"ws_recov_{uuid.uuid4().hex[:10]}"
        media_id = f"m_recov_{uuid.uuid4().hex[:10]}"
        video_file = tmp_path / "existing_video.mp4"
        await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.5)

        async with async_session_factory() as session:
            ws = Workspace(id=ws_id, name="Test Recov WS", local_storage_path="data/media")
            session.add(ws)
            upload_session = UploadSession(
                id=media_id,
                workspace_id=ws_id,
                original_filename="existing_video.mp4",
                expected_size_bytes=video_file.stat().st_size,
                received_size_bytes=video_file.stat().st_size,
                chunk_count=1,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                temporary_path=str(video_file),
                sha256="test_sha_recov",
                status="completed",
            )
            session.add(upload_session)
            video = ImportedVideo(
                id=media_id,
                workspace_id=ws_id,
                file_name="existing_video.mp4",
                file_path=str(video_file),
                duration_seconds=1.5,
                status="ready",
                thumbnail_status="pending",  # orphaned pending without active job
                sha256="test_sha_recov",
            )
            session.add(video)
            await session.commit()

        # Verify no active job exists
        async with async_session_factory() as session:
            jobs = (await session.execute(select(ProcessingJob).where(ProcessingJob.entity_id == media_id))).scalars().all()
            assert len(jobs) == 0

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Retry complete_upload
            res = await client.post(f"/api/v1/media/uploads/{media_id}/complete", json={})
            assert res.status_code == 200
            assert res.json()["status"] == "completed"

        # Now verify an active or running/completed thumbnail job was enqueued
        async with async_session_factory() as session:
            job_res = await session.execute(
                select(ProcessingJob).where(
                    ProcessingJob.entity_id == media_id,
                    ProcessingJob.job_type == "thumbnail_generation",
                )
            )
            job = job_res.scalars().first()
            assert job is not None, "A thumbnail job should have been enqueued during complete_upload retry"

    # Enforce strict 10-second timeout to prevent indefinite hangs
    await asyncio.wait_for(_run_test(), timeout=10.0)


@pytest.mark.asyncio
async def test_concurrent_complete_upload_recovery_no_deadlock(tmp_path):
    """Scenario 1b: Multiple concurrent complete_upload retries for the same media resolve cleanly without deadlock."""
    async def _run_test():
        ws_id = f"ws_conc_{uuid.uuid4().hex[:10]}"
        media_id = f"m_conc_{uuid.uuid4().hex[:10]}"
        video_file = tmp_path / "concurrent_video.mp4"
        await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.5)

        async with async_session_factory() as session:
            ws = Workspace(id=ws_id, name="Test Conc WS", local_storage_path="data/media")
            session.add(ws)
            upload_session = UploadSession(
                id=media_id,
                workspace_id=ws_id,
                original_filename="concurrent_video.mp4",
                expected_size_bytes=video_file.stat().st_size,
                received_size_bytes=video_file.stat().st_size,
                chunk_count=1,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                temporary_path=str(video_file),
                sha256="test_sha_conc",
                status="completed",
            )
            session.add(upload_session)
            video = ImportedVideo(
                id=media_id,
                workspace_id=ws_id,
                file_name="concurrent_video.mp4",
                file_path=str(video_file),
                duration_seconds=1.5,
                status="ready",
                thumbnail_status="pending",
                sha256="test_sha_conc",
            )
            session.add(video)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Fire 4 concurrent retry requests simultaneously
            responses = await asyncio.gather(
                client.post(f"/api/v1/media/uploads/{media_id}/complete", json={}),
                client.post(f"/api/v1/media/uploads/{media_id}/complete", json={}),
                client.post(f"/api/v1/media/uploads/{media_id}/complete", json={}),
                client.post(f"/api/v1/media/uploads/{media_id}/complete", json={}),
            )
            for res in responses:
                assert res.status_code == 200
                assert res.json()["status"] == "completed"

        # Verify only 1 thumbnail job was created (no duplicate explosion)
        async with async_session_factory() as session:
            jobs = (
                await session.execute(
                    select(ProcessingJob).where(
                        ProcessingJob.entity_id == media_id,
                        ProcessingJob.job_type == "thumbnail_generation",
                    )
                )
            ).scalars().all()
            assert len(jobs) == 1, f"Expected exactly 1 thumbnail job, found {len(jobs)}"

    await asyncio.wait_for(_run_test(), timeout=10.0)


@pytest.mark.asyncio
async def test_complete_upload_retry_active_job_no_duplicate(tmp_path):
    """Scenario 2: Completed upload retry when an active thumbnail job already exists does not duplicate jobs."""
    ws_id = f"ws_act_{uuid.uuid4().hex[:10]}"
    media_id = f"m_act_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "act_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.5)

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Test Active WS", local_storage_path="data/media")
        session.add(ws)
        upload_session = UploadSession(
            id=media_id,
            workspace_id=ws_id,
            original_filename="act_video.mp4",
            expected_size_bytes=video_file.stat().st_size,
            received_size_bytes=video_file.stat().st_size,
            chunk_count=1,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            temporary_path=str(video_file),
            sha256="test_sha_active",
            status="completed",
        )
        session.add(upload_session)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="act_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.5,
            status="ready",
            thumbnail_status="pending",
            sha256="test_sha_active",
        )
        session.add(video)
        # Pre-existing active job
        job = ProcessingJob(
            job_type="thumbnail_generation",
            entity_type="media",
            entity_id=media_id,
            status="queued",
            progress_percent=0.0,
            current_step="Queued in scheduler",
        )
        session.add(job)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(f"/api/v1/media/uploads/{media_id}/complete", json={})
        assert res.status_code == 200

    # Ensure only 1 job remains
    async with async_session_factory() as session:
        jobs = (await session.execute(select(ProcessingJob).where(ProcessingJob.entity_id == media_id))).scalars().all()
        assert len(jobs) == 1, "Duplicate jobs must not be created on complete_upload retry"


@pytest.mark.asyncio
async def test_complete_upload_retry_when_thumbnail_already_completed(tmp_path):
    """Scenario 3: Completed upload retry when thumbnail is already generated does nothing."""
    ws_id = f"ws_done_{uuid.uuid4().hex[:10]}"
    media_id = f"m_done_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "done_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)

    promoted_thumb, rel_thumb = await generate_thumbnail(
        input_video_path=video_file,
        workspace_id=ws_id,
        media_id=media_id,
        duration_seconds=1.0,
    )
    assert promoted_thumb.exists()

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Test Done WS", local_storage_path="data/media")
        session.add(ws)
        upload_session = UploadSession(
            id=media_id,
            workspace_id=ws_id,
            original_filename="done_video.mp4",
            expected_size_bytes=video_file.stat().st_size,
            received_size_bytes=video_file.stat().st_size,
            chunk_count=1,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            temporary_path=str(video_file),
            sha256="test_sha_done",
            status="completed",
        )
        session.add(upload_session)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="done_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="completed",
            thumbnail_path=rel_thumb,
            sha256="test_sha_done",
        )
        session.add(video)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(f"/api/v1/media/uploads/{media_id}/complete", json={})
        assert res.status_code == 200

    # Ensure no new jobs were created
    async with async_session_factory() as session:
        jobs = (await session.execute(select(ProcessingJob).where(ProcessingJob.entity_id == media_id))).scalars().all()
        assert len(jobs) == 0


@pytest.mark.asyncio
async def test_enqueue_failure_followed_by_recovery(tmp_path):
    """Scenario 4: Enqueue failure during upload does not abort import, and subsequent recovery enqueues thumbnail."""
    ws_id = f"ws_fault_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "fault_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)
    video_bytes = video_file.read_bytes()

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Fault WS", local_storage_path="data/media")
        session.add(ws)
        await session.commit()

    # Step 1: Enable fault injection so initial thumbnail enqueue fails
    job_queue._fault_injection_fail_enqueue = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initiate upload
        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={
                "workspace_id": ws_id,
                "filename": "fault_video.mp4",
                "file_size_bytes": len(video_bytes),
                "chunk_size_bytes": len(video_bytes),
            },
        )
        assert init_res.status_code == 201
        upload_id = init_res.json()["id"]

        # Upload chunk
        chunk_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=video_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert chunk_res.status_code == 200

        # Complete upload while fault injection is active
        comp_res = await client.post(f"/api/v1/media/uploads/{upload_id}/complete", json={})
        assert comp_res.status_code == 200  # import still succeeds gracefully!
        assert comp_res.json()["status"] == "completed"
        # Issue A: Ensure thumbnail_status transitions to 'failed' rather than invalid 'pending'
        assert comp_res.json()["video"]["thumbnail_status"] == "failed"

    # Step 2: Verify in DB that video exists, thumbnail_status is 'failed', and no job was created
    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, upload_id)
        assert v is not None
        assert v.thumbnail_status == "failed"
        jobs = (await session.execute(select(ProcessingJob).where(ProcessingJob.entity_id == upload_id))).scalars().all()
        assert len(jobs) == 0

    # Step 3: Disable fault injection and trigger reconciliation
    job_queue._fault_injection_fail_enqueue = False
    recovered = await job_queue.reconcile_pending_thumbnails(workspace_id=ws_id)
    assert upload_id in recovered

    # Step 4: Verify job is now running/completed
    for _ in range(80):
        async with async_session_factory() as session:
            v = await session.get(ImportedVideo, upload_id)
            if v and v.thumbnail_status == "completed":
                break
        await asyncio.sleep(0.1)

    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, upload_id)
        assert v.thumbnail_status == "completed"


@pytest.mark.asyncio
async def test_startup_reconciliation_pending_thumbnails(tmp_path):
    """Scenario 5: Startup reconciliation detects and recovers pending thumbnails."""
    ws_id = f"ws_start_{uuid.uuid4().hex[:10]}"
    media_id = f"m_start_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "start_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Startup WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="start_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(video)
        await session.commit()

    # Trigger reconciliation for the test workspace
    await job_queue.reconcile_pending_thumbnails(workspace_id=ws_id)

    # Wait for thumbnail to be generated
    for _ in range(50):
        async with async_session_factory() as session:
            v = await session.get(ImportedVideo, media_id)
            if v and v.thumbnail_status == "completed":
                break
        await asyncio.sleep(0.05)

    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, media_id)
        assert v.thumbnail_status == "completed"


@pytest.mark.asyncio
async def test_recovery_after_interrupted_thumbnail_job(tmp_path):
    """Scenario 6: Recovery after an interrupted thumbnail job."""
    ws_id = f"ws_int_{uuid.uuid4().hex[:10]}"
    media_id = f"m_int_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "int_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Interrupted WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="int_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="processing",  # was interrupted mid-run
        )
        session.add(video)
        # Interrupted running job in database
        stale_job = ProcessingJob(
            job_type="thumbnail_generation",
            entity_type="media",
            entity_id=media_id,
            status="running",
            progress_percent=25.0,
            current_step="Extracting frame",
        )
        session.add(stale_job)
        await session.commit()

    # Reconcile interrupted jobs (fails stale job and re-enqueues thumbnail for workspace)
    await job_queue.reconcile_interrupted_jobs()
    await job_queue.reconcile_pending_thumbnails(workspace_id=ws_id)

    # Wait for recovery to complete
    for _ in range(80):
        async with async_session_factory() as session:
            v = await session.get(ImportedVideo, media_id)
            if v and v.thumbnail_status == "completed":
                break
        await asyncio.sleep(0.1)

    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, media_id)
        assert v.thumbnail_status == "completed"


@pytest.mark.asyncio
async def test_concurrent_reconciliation_without_duplicates(tmp_path):
    """Scenario 7: Concurrent reconciliation calls do not schedule duplicate jobs."""
    ws_id = f"ws_conc_{uuid.uuid4().hex[:10]}"
    media_id = f"m_conc_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "conc_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Concurrent WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="conc_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(video)
        await session.commit()

    # Run 3 concurrent reconciliations
    t1 = job_queue.reconcile_pending_thumbnails(workspace_id=ws_id)
    t2 = job_queue.reconcile_pending_thumbnails(workspace_id=ws_id)
    t3 = job_queue.reconcile_pending_thumbnails(workspace_id=ws_id)
    await asyncio.gather(t1, t2, t3)

    # Check that at most 1 job was created
    async with async_session_factory() as session:
        jobs = (await session.execute(select(ProcessingJob).where(ProcessingJob.entity_id == media_id))).scalars().all()
        assert len(jobs) == 1, f"Expected exactly 1 job, got {len(jobs)}"


@pytest.mark.asyncio
async def test_reconciliation_skips_and_marks_failed_when_source_missing():
    """Scenario 8: Reconciliation skips missing original file and marks failed to avoid retry loops."""
    ws_id = f"ws_miss_{uuid.uuid4().hex[:10]}"
    media_id = f"m_miss_{uuid.uuid4().hex[:10]}"

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Missing Source WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="nonexistent.mp4",
            file_path="media/nonexistent/missing.mp4",
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(video)
        await session.commit()

    recovered = await job_queue.reconcile_pending_thumbnails(workspace_id=ws_id)
    assert media_id not in recovered

    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, media_id)
        assert v.thumbnail_status == "failed"


@pytest.mark.asyncio
async def test_thumbnail_generation_corrupt_original_marks_failed(tmp_path):
    """Scenario 9: Corrupt original media file safely transitions thumbnail job to failed."""
    ws_id = f"ws_corrupt_{uuid.uuid4().hex[:10]}"
    media_id = f"m_corrupt_{uuid.uuid4().hex[:10]}"
    corrupt_file = tmp_path / "corrupt_video.mp4"
    corrupt_file.write_bytes(b"NOT A REAL VIDEO STREAM 1234567890")

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Corrupt WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="corrupt_video.mp4",
            file_path=str(corrupt_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(video)
        await session.commit()

    await job_queue.enqueue_thumbnail_job(
        media_id=media_id,
        workspace_id=ws_id,
        file_path=str(corrupt_file),
        duration_seconds=1.0,
    )

    # Wait for job to process and fail
    for _ in range(50):
        async with async_session_factory() as session:
            v = await session.get(ImportedVideo, media_id)
            if v and v.thumbnail_status == "failed":
                break
        await asyncio.sleep(0.05)

    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, media_id)
        assert v.thumbnail_status == "failed"


@pytest.mark.asyncio
async def test_failed_thumbnail_retry_behavior(tmp_path):
    """Scenario 10: Failed thumbnail can be manually retried after fixing the issue."""
    ws_id = f"ws_retry_{uuid.uuid4().hex[:10]}"
    media_id = f"m_retry_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "retry_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Retry WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="retry_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="failed",
        )
        session.add(video)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        regen_res = await client.post(f"/api/v1/media/{media_id}/thumbnail/regenerate")
        assert regen_res.status_code == 202
        assert regen_res.json()["status"] == "queued"

    # Wait for completion
    for _ in range(50):
        async with async_session_factory() as session:
            v = await session.get(ImportedVideo, media_id)
            if v and v.thumbnail_status == "completed":
                break
        await asyncio.sleep(0.05)

    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, media_id)
        assert v.thumbnail_status == "completed"


# ==============================================================================
# Finding CS-REV-2B2-002: Actual Thumbnail Dimensions Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_jpeg_dimensions_landscape(tmp_path):
    """Scenario 11: Correct actual JPEG dimensions extracted for landscape video (1920x1080 -> 640x360)."""
    ws_id = f"ws_land_{uuid.uuid4().hex[:10]}"
    media_id = f"m_land_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "landscape.mp4"
    await create_synthetic_video(video_file, width=1920, height=1080, duration_seconds=1.0)

    promoted_thumb, rel_thumb = await generate_thumbnail(
        input_video_path=video_file,
        workspace_id=ws_id,
        media_id=media_id,
        duration_seconds=1.0,
    )

    dims = get_jpeg_dimensions(promoted_thumb)
    assert dims == (640, 360), f"Expected (640, 360), got {dims}"

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Land WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="landscape.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="completed",
            thumbnail_path=rel_thumb,
        )
        session.add(video)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        meta_res = await client.get(f"/api/v1/media/{media_id}/thumbnail/metadata")
        assert meta_res.status_code == 200
        data = meta_res.json()
        assert data["width"] == 640
        assert data["height"] == 360


@pytest.mark.asyncio
async def test_jpeg_dimensions_portrait(tmp_path):
    """Scenario 12: Correct actual JPEG dimensions extracted for vertical/portrait video (1080x1920 -> 640x1138)."""
    ws_id = f"ws_port_{uuid.uuid4().hex[:10]}"
    media_id = f"m_port_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "portrait.mp4"
    await create_synthetic_video(video_file, width=1080, height=1920, duration_seconds=1.0)

    promoted_thumb, rel_thumb = await generate_thumbnail(
        input_video_path=video_file,
        workspace_id=ws_id,
        media_id=media_id,
        duration_seconds=1.0,
    )

    dims = get_jpeg_dimensions(promoted_thumb)
    assert dims == (640, 1138), f"Expected (640, 1138), got {dims}"

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Port WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="portrait.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="completed",
            thumbnail_path=rel_thumb,
        )
        session.add(video)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        meta_res = await client.get(f"/api/v1/media/{media_id}/thumbnail/metadata")
        assert meta_res.status_code == 200
        data = meta_res.json()
        assert data["width"] == 640
        assert data["height"] == 1138


@pytest.mark.asyncio
async def test_jpeg_dimensions_non_standard_aspect_ratio(tmp_path):
    """Scenario 13: Correct actual JPEG dimensions for non-standard aspect ratio video (720x576 PAL 5:4 -> 640x512)."""
    ws_id = f"ws_pal_{uuid.uuid4().hex[:10]}"
    media_id = f"m_pal_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "pal.mp4"
    await create_synthetic_video(video_file, width=720, height=576, duration_seconds=1.0)

    promoted_thumb, rel_thumb = await generate_thumbnail(
        input_video_path=video_file,
        workspace_id=ws_id,
        media_id=media_id,
        duration_seconds=1.0,
    )

    dims = get_jpeg_dimensions(promoted_thumb)
    assert dims == (640, 512), f"Expected (640, 512), got {dims}"

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="PAL WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="pal.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="completed",
            thumbnail_path=rel_thumb,
        )
        session.add(video)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        meta_res = await client.get(f"/api/v1/media/{media_id}/thumbnail/metadata")
        assert meta_res.status_code == 200
        data = meta_res.json()
        assert data["width"] == 640
        assert data["height"] == 512


@pytest.mark.asyncio
async def test_thumbnail_metadata_missing_or_corrupt_file():
    """Scenario 14: Missing or corrupt thumbnail returns width=None, height=None safely."""
    # Non-existent file
    assert get_jpeg_dimensions("non_existent_file.jpg") == (None, None)

    # Empty file
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"")
        empty_path = Path(f.name)
    assert get_jpeg_dimensions(empty_path) == (None, None)
    empty_path.unlink()

    # Corrupt / not a JPEG file
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"CORRUPT DATA NOT JPEG")
        corrupt_path = Path(f.name)
    assert get_jpeg_dimensions(corrupt_path) == (None, None)
    corrupt_path.unlink()


@pytest.mark.asyncio
async def test_thumbnail_job_cancellation_and_terminal_state(tmp_path):
    """Scenario 15: Existing thumbnail generation cancellation and terminal-state regression."""
    ws_id = f"ws_term_{uuid.uuid4().hex[:10]}"
    media_id = f"m_term_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "term_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)

    job = await job_queue.enqueue_thumbnail_job(
        media_id=media_id,
        workspace_id=ws_id,
        file_path=str(video_file),
        duration_seconds=1.0,
    )
    assert job.status in ("queued", "running", "completed")

    # Cancel job
    res = await job_queue.cancel_job(job.id)
    assert res is True or job.status == "completed"


@pytest.mark.asyncio
async def test_thumbnail_job_result_data_captures_actual_dimensions(tmp_path):
    """Scenario 16: Completed thumbnail generation job persists actual width, height, and file size in result_data."""
    ws_id = f"ws_dim_{uuid.uuid4().hex[:10]}"
    media_id = f"m_dim_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "dim_video.mp4"
    # Create 1920x1080 video -> generated thumbnail scaled to 640x360
    await create_synthetic_video(video_file, width=1920, height=1080, duration_seconds=1.5)

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Dim WS", local_storage_path="data/media")
        session.add(ws)
        v = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="dim_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.5,
            width=1920,
            height=1080,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(v)
        await session.commit()

    job = await job_queue.enqueue_thumbnail_job(
        media_id=media_id,
        workspace_id=ws_id,
        file_path=str(video_file),
        duration_seconds=1.5,
    )

    # Wait for completion
    for _ in range(80):
        async with async_session_factory() as session:
            j = await session.get(ProcessingJob, job.id)
            if j and j.status == "completed":
                break
        await asyncio.sleep(0.1)

    async with async_session_factory() as session:
        completed_job = await session.get(ProcessingJob, job.id)
        assert completed_job is not None
        assert completed_job.status == "completed"
        assert completed_job.result_data is not None
        result_info = json.loads(completed_job.result_data)
        assert result_info["width"] == 640
        assert result_info["height"] == 360
        assert result_info["file_size_bytes"] > 0


@pytest.mark.asyncio
async def test_direct_enqueue_failure_marks_media_failed(tmp_path):
    """Scenario 17: Direct enqueue_thumbnail_job failure transitions media record to failed rather than pending."""
    ws_id = f"ws_direct_{uuid.uuid4().hex[:10]}"
    media_id = f"m_direct_{uuid.uuid4().hex[:10]}"
    video_file = tmp_path / "direct_video.mp4"
    await create_synthetic_video(video_file, width=640, height=360, duration_seconds=1.0)

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Direct Fail WS", local_storage_path="data/media")
        session.add(ws)
        v = ImportedVideo(
            id=media_id,
            workspace_id=ws_id,
            file_name="direct_video.mp4",
            file_path=str(video_file),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(v)
        await session.commit()

    job_queue._fault_injection_fail_enqueue = True
    try:
        with pytest.raises(RuntimeError, match="Simulated thumbnail job enqueue failure"):
            await job_queue.enqueue_thumbnail_job(
                media_id=media_id,
                workspace_id=ws_id,
                file_path=str(video_file),
                duration_seconds=1.0,
            )
    finally:
        job_queue._fault_injection_fail_enqueue = False

    async with async_session_factory() as session:
        v = await session.get(ImportedVideo, media_id)
        assert v is not None
        assert v.thumbnail_status == "failed"

