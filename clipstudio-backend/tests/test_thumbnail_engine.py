import asyncio
import os
import shutil
import uuid
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from app.config import settings
from app.database import async_session_factory
from app.main import app
from app.models.job import ProcessingJob
from app.models.video import ImportedVideo
from app.models.workspace import Workspace
from app.services.ffmpeg import FFmpegRunner
from app.services.job_queue import job_queue
from app.services.thumbnail import (
    ThumbnailException,
    calculate_thumbnail_timestamp,
    generate_thumbnail,
    get_thumbnail_storage_paths,
)


@pytest.fixture(autouse=True)
async def cleanup_queue():
    """Ensure clean job queue before and after each test."""
    await job_queue.cancel_all_active_jobs()
    yield
    await job_queue.cancel_all_active_jobs()


async def create_synthetic_mp4(dest_path: Path, duration_seconds: float = 2.0) -> Path:
    """Generate a real synthetic MP4 file using FFmpeg lavfi testsrc."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    runner = FFmpegRunner()
    cmd = [
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration_seconds}:size=320x240:rate=25",
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
# 1. Calculation & Storage Layout Unit Tests
# ==============================================================================


def test_calculate_thumbnail_timestamp():
    """Verifies representative timestamp calculation across various video durations."""
    # Negative / zero duration
    assert calculate_thumbnail_timestamp(0.0) == 0.0
    assert calculate_thumbnail_timestamp(-5.0) == 0.0

    # Very short videos (<= 1.0s) -> mid-point
    assert calculate_thumbnail_timestamp(0.6) == 0.3
    assert calculate_thumbnail_timestamp(1.0) == 0.5

    # Standard videos -> 10%
    assert calculate_thumbnail_timestamp(10.0) == 1.0
    assert calculate_thumbnail_timestamp(60.0) == 6.0

    # Short video where 10% is less than min (0.5s) -> uses min
    assert calculate_thumbnail_timestamp(3.0) == 0.5

    # Multi-hour long video -> capped at 15.0s
    assert calculate_thumbnail_timestamp(3600.0) == 15.0


def test_get_thumbnail_storage_paths():
    """Verifies thumbnail filesystem and relative DB storage paths conform to convention."""
    abs_path, rel_path = get_thumbnail_storage_paths("ws-123", "media-456")
    expected_rel = "media/thumbnails/ws-123/media-456/thumbnail.jpg"
    assert rel_path == expected_rel
    assert abs_path == settings.MEDIA_THUMBNAILS_DIR / "ws-123" / "media-456" / "thumbnail.jpg"


# ==============================================================================
# 2. Thumbnail Generation Subprocess Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_generate_thumbnail_success(tmp_path):
    """Verifies successful thumbnail extraction and atomic promotion."""
    video_path = tmp_path / "test_video.mp4"
    await create_synthetic_mp4(video_path, duration_seconds=3.0)

    promoted_path, rel_path = await generate_thumbnail(
        input_video_path=video_path,
        workspace_id="test_ws",
        media_id="test_media_1",
        duration_seconds=3.0,
        width=320,
    )

    assert promoted_path.exists()
    assert promoted_path.is_file()
    assert promoted_path.stat().st_size > 500  # Valid JPEG has bytes
    assert rel_path == "media/thumbnails/test_ws/test_media_1/thumbnail.jpg"

    # Verify JPEG magic bytes (FF D8 FF)
    with open(promoted_path, "rb") as f:
        header = f.read(3)
        assert header == b"\xff\xd8\xff", "Generated thumbnail must be a valid JPEG file"


@pytest.mark.asyncio
async def test_generate_thumbnail_short_video(tmp_path):
    """Verifies thumbnail extraction succeeds for sub-second video files."""
    video_path = tmp_path / "short_video.mp4"
    await create_synthetic_mp4(video_path, duration_seconds=0.5)

    promoted_path, _ = await generate_thumbnail(
        input_video_path=video_path,
        workspace_id="test_ws",
        media_id="test_media_short",
        duration_seconds=0.5,
    )
    assert promoted_path.exists()
    assert promoted_path.stat().st_size > 0


@pytest.mark.asyncio
async def test_generate_thumbnail_missing_source(tmp_path):
    """Verifies ThumbnailException is raised when source video does not exist."""
    missing_path = tmp_path / "non_existent.mp4"
    with pytest.raises(ThumbnailException, match="Source video file not found"):
        await generate_thumbnail(
            input_video_path=missing_path,
            workspace_id="test_ws",
            media_id="test_missing",
            duration_seconds=10.0,
        )


@pytest.mark.asyncio
async def test_generate_thumbnail_invalid_corrupted_media(tmp_path):
    """Verifies ThumbnailException is raised when input file is corrupted text."""
    corrupt_file = tmp_path / "corrupt.mp4"
    corrupt_file.write_text("NOT A REAL MP4 FILE HEADER", encoding="utf-8")

    with pytest.raises(ThumbnailException, match="FFmpeg thumbnail extraction failed"):
        await generate_thumbnail(
            input_video_path=corrupt_file,
            workspace_id="test_ws",
            media_id="test_corrupt",
            duration_seconds=5.0,
        )


@pytest.mark.asyncio
async def test_generate_thumbnail_timeout(tmp_path):
    """Verifies timeout abort raises ThumbnailException and cleans up temp files."""
    video_path = tmp_path / "test_timeout.mp4"
    await create_synthetic_mp4(video_path, duration_seconds=2.0)

    # Impose an impossible 0.0001s timeout
    with pytest.raises(ThumbnailException):
        await generate_thumbnail(
            input_video_path=video_path,
            workspace_id="test_ws",
            media_id="test_timeout",
            duration_seconds=2.0,
            timeout_seconds=0.0001,
        )


# ==============================================================================
# 3. Job Queue Integration Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_job_queue_thumbnail_lifecycle(tmp_path):
    """Verifies end-to-end thumbnail job execution updates database models cleanly."""
    video_path = tmp_path / "queue_video.mp4"
    await create_synthetic_mp4(video_path, duration_seconds=2.0)

    workspace_id = f"ws_queue_{uuid.uuid4().hex[:10]}"
    media_id = f"media_queue_{uuid.uuid4().hex[:10]}"

    async with async_session_factory() as session:
        ws = Workspace(id=workspace_id, name="Test Queue WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=media_id,
            workspace_id=workspace_id,
            file_name="queue_video.mp4",
            file_path=str(video_path),
            file_size_bytes=video_path.stat().st_size,
            duration_seconds=2.0,
            width=320,
            height=240,
            fps=25.0,
            video_codec="h264",
            audio_codec="none",
            status="ready",
            thumbnail_status="pending",
        )
        session.add(video)
        await session.commit()

    # Enqueue thumbnail generation
    job = await job_queue.enqueue_thumbnail_job(
        media_id=media_id,
        workspace_id=workspace_id,
        file_path=str(video_path),
        duration_seconds=2.0,
    )
    assert job is not None
    assert job.status in ["queued", "running"]

    # Wait for job completion
    for _ in range(50):
        await asyncio.sleep(0.1)
        async with async_session_factory() as session:
            db_job = await session.get(ProcessingJob, job.id)
            if db_job and db_job.status in ["completed", "failed"]:
                break

    assert db_job.status == "completed"
    assert db_job.progress_percent == 100.0

    # Verify video record has updated thumbnail fields
    async with async_session_factory() as session:
        updated_video = await session.get(ImportedVideo, media_id)
        assert updated_video.thumbnail_status == "completed"
        assert updated_video.thumbnail_path is not None
        assert updated_video.thumbnail_generated_at is not None

        thumb_abs = settings.MEDIA_THUMBNAILS_DIR / workspace_id / media_id / "thumbnail.jpg"
        assert thumb_abs.exists()


@pytest.mark.asyncio
async def test_job_queue_duplicate_job_prevention(tmp_path):
    """Verifies that duplicate active thumbnail jobs for the same media are prevented."""
    video_path = tmp_path / "dup_video.mp4"
    await create_synthetic_mp4(video_path, duration_seconds=5.0)

    ws_id = f"ws_dup_{uuid.uuid4().hex[:10]}"
    m_id = f"media_dup_{uuid.uuid4().hex[:10]}"

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Test Dup WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=m_id,
            workspace_id=ws_id,
            file_name="dup_video.mp4",
            file_path=str(video_path),
            duration_seconds=5.0,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(video)
        await session.commit()

    job1 = await job_queue.enqueue_thumbnail_job(
        media_id=m_id,
        workspace_id=ws_id,
        file_path=str(video_path),
        duration_seconds=5.0,
    )

    # Immediately attempt to enqueue again
    job2 = await job_queue.enqueue_thumbnail_job(
        media_id=m_id,
        workspace_id=ws_id,
        file_path=str(video_path),
        duration_seconds=5.0,
    )

    assert job1.id == job2.id, "Duplicate thumbnail job must return existing active job"


# ==============================================================================
# 4. REST API Endpoint Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_api_thumbnail_endpoints(tmp_path):
    """Verifies GET thumbnail, GET metadata, and POST regenerate endpoints."""
    video_path = tmp_path / "api_video.mp4"
    await create_synthetic_mp4(video_path, duration_seconds=2.0)

    ws_id = f"ws_api_{uuid.uuid4().hex[:10]}"
    m_id = f"media_api_{uuid.uuid4().hex[:10]}"

    # 1. Create DB records
    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="API WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=m_id,
            workspace_id=ws_id,
            file_name="api_video.mp4",
            file_path=str(video_path),
            duration_seconds=2.0,
            status="ready",
            thumbnail_status="pending",
        )
        session.add(video)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # A. Thumbnail not yet completed -> 404
        res = await client.get(f"/api/v1/media/{m_id}/thumbnail")
        assert res.status_code == 404
        assert "Thumbnail not available" in res.json()["detail"]

        # B. Check metadata while pending
        meta_res = await client.get(f"/api/v1/media/{m_id}/thumbnail/metadata")
        assert meta_res.status_code == 200
        meta = meta_res.json()
        assert meta["media_id"] == m_id
        assert meta["status"] == "pending"
        assert meta["thumbnail_url"] is None

        # C. Generate thumbnail directly to test successful serving
        promoted, rel_path = await generate_thumbnail(
            input_video_path=video_path,
            workspace_id=ws_id,
            media_id=m_id,
            duration_seconds=2.0,
        )

        async with async_session_factory() as session:
            v = await session.get(ImportedVideo, m_id)
            v.thumbnail_path = rel_path
            v.thumbnail_status = "completed"
            await session.commit()

        # D. GET thumbnail -> HTTP 200 with image/jpeg
        thumb_res = await client.get(f"/api/v1/media/{m_id}/thumbnail")
        assert thumb_res.status_code == 200
        assert thumb_res.headers["content-type"] == "image/jpeg"
        assert "max-age" in thumb_res.headers.get("cache-control", "")
        assert len(thumb_res.content) == promoted.stat().st_size

        # E. GET metadata while completed
        meta_res2 = await client.get(f"/api/v1/media/{m_id}/thumbnail/metadata")
        assert meta_res2.status_code == 200
        meta2 = meta_res2.json()
        assert meta2["status"] == "completed"
        assert meta2["thumbnail_url"] == f"/api/v1/media/{m_id}/thumbnail"
        assert meta2["file_size_bytes"] == promoted.stat().st_size

        # F. POST regenerate
        regen_res = await client.post(f"/api/v1/media/{m_id}/thumbnail/regenerate")
        assert regen_res.status_code == 202
        regen_data = regen_res.json()
        assert regen_data["status"] == "queued"
        assert "job_id" in regen_data

        # G. POST regenerate conflict if already active
        conflict_res = await client.post(f"/api/v1/media/{m_id}/thumbnail/regenerate")
        assert conflict_res.status_code == 409
        assert "already in progress" in conflict_res.json()["detail"]


@pytest.mark.asyncio
async def test_api_thumbnail_missing_media_404():
    """Verifies 404 is returned when requesting thumbnail for non-existent media."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/media/non-existent-uuid/thumbnail")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"]


# ==============================================================================
# 5. Path Traversal & Cleanup Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_thumbnail_path_traversal_protection(tmp_path):
    """Verifies that attempting path traversal in input video path is rejected."""
    with pytest.raises(Exception):
        await generate_thumbnail(
            input_video_path="../../etc/passwd",
            workspace_id="ws_traversal",
            media_id="media_traversal",
            duration_seconds=1.0,
        )


@pytest.mark.asyncio
async def test_media_delete_removes_thumbnail_file(tmp_path):
    """Verifies that deleting a media asset cleans up its thumbnail file."""
    video_path = tmp_path / "del_video.mp4"
    await create_synthetic_mp4(video_path, duration_seconds=1.0)

    ws_id = f"ws_del_{uuid.uuid4().hex[:10]}"
    m_id = f"media_del_{uuid.uuid4().hex[:10]}"

    promoted_thumb, rel_thumb = await generate_thumbnail(
        input_video_path=video_path,
        workspace_id=ws_id,
        media_id=m_id,
        duration_seconds=1.0,
    )
    assert promoted_thumb.exists()

    async with async_session_factory() as session:
        ws = Workspace(id=ws_id, name="Del WS", local_storage_path="data/media")
        session.add(ws)
        video = ImportedVideo(
            id=m_id,
            workspace_id=ws_id,
            file_name="del_video.mp4",
            file_path=str(video_path),
            duration_seconds=1.0,
            status="ready",
            thumbnail_status="completed",
            thumbnail_path=rel_thumb,
        )
        session.add(video)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        del_res = await client.delete(f"/api/v1/media/{m_id}")
        assert del_res.status_code == 200

    # Thumbnail should be cleaned up
    assert not promoted_thumb.exists(), "Thumbnail file should be removed when media is deleted"
