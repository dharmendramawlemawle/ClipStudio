import asyncio
import hashlib
import os
import subprocess
from unittest.mock import patch
import pytest
from pathlib import Path
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import async_session_factory
from app.main import app
from app.models.job import ProcessingJob
from app.models.video import ImportedVideo
from app.services.storage import (
    sanitize_filename,
    safe_resolve_path,
    check_disk_space,
    compute_sha256_stream,
    StorageException,
)
from app.services.media_probe import (
    parse_fractional_fps,
    extract_media_specs,
    MediaValidationException,
    resolve_ffprobe_executable,
)


# --- 1. Unit Tests ---

def test_sanitize_filename():
    assert sanitize_filename("my video 2026.mp4") == "my_video_2026.mp4"
    assert sanitize_filename("../../etc/passwd.mov") == "etc_passwd.mov"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.mkv") == "windows_system32_cmd.mkv"
    assert sanitize_filename("weird!@#$%^&*()_+name.webm") == "weird_name.webm"
    assert sanitize_filename("...") == "imported_media.mp4"
    assert sanitize_filename("a" * 150 + ".mp4") == "a" * 100 + ".mp4"


def test_safe_resolve_path(tmp_path):
    root = tmp_path / "storage"
    root.mkdir()

    # Valid relative path
    valid = safe_resolve_path("media/video.mp4", storage_root=root)
    assert valid == (root / "media" / "video.mp4").resolve()

    # Traversal attempt
    with pytest.raises(StorageException):
        safe_resolve_path("../../secret.txt", storage_root=root)


def test_compute_sha256_stream(tmp_path):
    test_file = tmp_path / "test.bin"
    data = b"ClipStudio Phase 2A Streaming SHA-256 Test" * 1000
    test_file.write_bytes(data)

    expected = hashlib.sha256(data).hexdigest()
    actual = compute_sha256_stream(test_file)
    assert actual == expected


def test_check_disk_space(tmp_path):
    # Reasonable requirement
    is_ok, free, msg = check_disk_space(1024, storage_dir=tmp_path)
    assert is_ok is True

    # Impossible requirement (exceeding any drive)
    is_ok, free, msg = check_disk_space(10**18, storage_dir=tmp_path)
    assert is_ok is False
    assert "Insufficient disk space" in msg


def test_media_probe_helpers():
    assert parse_fractional_fps("30/1") == 30.0
    assert parse_fractional_fps("60000/1001") == 59.94
    assert parse_fractional_fps("25") == 25.0
    assert parse_fractional_fps("0/0") == 0.0

    # Test rejection of streams with no video
    with pytest.raises(MediaValidationException):
        extract_media_specs({"streams": [{"codec_type": "audio"}]})


# --- 2. Integration Tests ---

def generate_sample_video(output_path: Path, duration: int = 1) -> Path:
    """Generate a minimal valid H.264/AAC MP4 video for integration tests."""
    ffmpeg_cmd = "ffmpeg"
    cmd = [
        ffmpeg_cmd,
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size=320x240:rate=25",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


@pytest.mark.asyncio
async def test_full_media_upload_lifecycle(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create a workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={
                "name": "Media Upload Test Workspace",
                "local_storage_path": str(tmp_path),
            },
        )
        assert ws_res.status_code == 201
        ws_id = ws_res.json()["id"]

        # 2. Test upload initiate validation
        # Bad workspace
        bad_ws_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": "non-existent-id", "filename": "test.mp4", "file_size_bytes": 1000},
        )
        assert bad_ws_res.status_code == 404

        # Oversized file (> 5 GB limit)
        oversized_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "huge.mp4", "file_size_bytes": 6 * 1024 * 1024 * 1024},
        )
        assert oversized_res.status_code == 413

        # Zero size (Pydantic schema validation returns 422 for gt=0 constraint)
        zero_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "empty.mp4", "file_size_bytes": 0},
        )
        assert zero_res.status_code == 422

        # 3. Generate a real 1-second sample video
        sample_video_path = tmp_path / "valid_sample.mp4"
        generate_sample_video(sample_video_path, duration=1)
        video_bytes = sample_video_path.read_bytes()
        total_size = len(video_bytes)

        # 4. Initiate valid upload session
        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={
                "workspace_id": ws_id,
                "filename": "valid_sample.mp4",
                "file_size_bytes": total_size,
            },
        )
        assert init_res.status_code == 201
        session = init_res.json()
        upload_id = session["id"]
        assert session["status"] == "active"
        assert session["expected_size_bytes"] == total_size

        # 5. Upload in two chunks: split total_size in half
        mid = total_size // 2
        chunk0 = video_bytes[:mid]
        chunk1 = video_bytes[mid:]

        # Test chunk integrity: try sending chunk 1 first (out of order)
        out_of_order = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 1, "offset_bytes": 0},
            content=chunk0,
        )
        assert out_of_order.status_code == 400
        assert "Expected chunk index 0" in out_of_order.json()["detail"]

        # Send chunk 0
        c0_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=chunk0,
        )
        assert c0_res.status_code == 200
        c0_data = c0_res.json()
        assert c0_data["received_size_bytes"] == len(chunk0)
        assert c0_data["is_complete"] is False

        # Idempotent re-send of chunk 0
        c0_resend = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=chunk0,
        )
        assert c0_resend.status_code == 200
        assert c0_resend.json()["received_size_bytes"] == len(chunk0)

        # Send chunk 1 with wrong offset
        wrong_offset = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 1, "offset_bytes": 999999},
            content=chunk1,
        )
        assert wrong_offset.status_code == 400
        assert "offset mismatch" in wrong_offset.json()["detail"].lower()

        # Send chunk 1 with correct offset
        c1_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 1, "offset_bytes": len(chunk0)},
            content=chunk1,
        )
        assert c1_res.status_code == 200
        assert c1_res.json()["is_complete"] is True
        assert c1_res.json()["received_size_bytes"] == total_size

        # 6. Complete Upload
        complete_res = await client.post(
            f"/api/v1/media/uploads/{upload_id}/complete",
            json={"confirm_duplicate": False},
        )
        assert complete_res.status_code == 200
        comp_data = complete_res.json()
        assert comp_data["status"] == "completed"
        video = comp_data["video"]
        assert video is not None
        assert video["file_name"] == "valid_sample.mp4"
        assert video["width"] == 320
        assert video["height"] == 240
        assert video["status"] == "ready"
        assert len(video["sha256"]) == 64
        media_id = video["id"]

        # Verify permanent physical file exists
        abs_promoted_path = safe_resolve_path(video["file_path"])
        assert abs_promoted_path.exists()
        assert abs_promoted_path.stat().st_size == total_size

        # Verify temporary staging directory was cleaned up
        temp_dir = settings.UPLOADS_TEMP_DIR / upload_id
        assert not temp_dir.exists()

        # 7. Test duplicate detection: upload same video bytes into same workspace
        dup_init = await client.post(
            "/api/v1/media/uploads/initiate",
            json={
                "workspace_id": ws_id,
                "filename": "valid_sample_copy.mp4",
                "file_size_bytes": total_size,
            },
        )
        dup_upload_id = dup_init.json()["id"]
        # Upload in 1 chunk
        await client.put(
            f"/api/v1/media/uploads/{dup_upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=video_bytes,
        )
        # Complete without confirm_duplicate -> triggers duplicate detection
        dup_complete = await client.post(
            f"/api/v1/media/uploads/{dup_upload_id}/complete",
            json={"confirm_duplicate": False},
        )
        assert dup_complete.status_code == 200
        dup_data = dup_complete.json()
        assert dup_data["status"] == "duplicate_detected"
        assert dup_data["duplicate_video_id"] == media_id

        # Now complete WITH confirm_duplicate=True
        dup_confirm = await client.post(
            f"/api/v1/media/uploads/{dup_upload_id}/complete",
            json={"confirm_duplicate": True},
        )
        assert dup_confirm.status_code == 200
        assert dup_confirm.json()["status"] == "completed"

        # 8. List media
        list_res = await client.get("/api/v1/media", params={"workspace_id": ws_id})
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert len(items) >= 2

        # 9. Get individual media details
        get_res = await client.get(f"/api/v1/media/{media_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == media_id

        # 10. Wait for auto-enqueued thumbnail job before deleting
        for _ in range(60):
            meta = await client.get(f"/api/v1/media/{media_id}/thumbnail/metadata")
            if meta.status_code == 200 and meta.json().get("status") in ["completed", "failed"]:
                break
            await asyncio.sleep(0.05)

        del_res = await client.delete(f"/api/v1/media/{media_id}")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "deleted"

        # Verify 404 after deletion
        get_after = await client.get(f"/api/v1/media/{media_id}")
        assert get_after.status_code == 404


@pytest.mark.asyncio
async def test_corrupt_file_rejection(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Corrupt Media Test", "local_storage_path": str(tmp_path)},
        )
        ws_id = ws_res.json()["id"]

        # Fake MP4: random text content
        fake_content = b"THIS IS NOT A VALID MP4 FILE! IT HAS NO VIDEO STREAM."
        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "fake.mp4", "file_size_bytes": len(fake_content)},
        )
        upload_id = init_res.json()["id"]

        # Upload chunk
        await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=fake_content,
        )

        # Complete upload -> should be rejected by FFprobe validator with 422
        complete_res = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert complete_res.status_code == 422
        assert "validation" in complete_res.json()["detail"].lower()


# --- 3. Phase 2A.1 Reliability & Data Integrity Regression Tests ---

@pytest.mark.asyncio
async def test_chunk_stream_abort_truncation_recovery(tmp_path):
    """Test A: Verify staging file truncates on stream abort and allows clean full chunk retry."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Abort Recovery Workspace", "local_storage_path": str(tmp_path)},
        )
        assert ws_res.status_code == 201
        ws_id = ws_res.json()["id"]

        # 2. Generate sample video
        sample_path = tmp_path / "abort_sample.mp4"
        generate_sample_video(sample_path, duration=1)
        video_bytes = sample_path.read_bytes()
        total_size = len(video_bytes)
        mid = total_size // 2
        chunk0 = video_bytes[:mid]
        chunk1 = video_bytes[mid:]

        # 3. Initiate upload
        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "abort_sample.mp4", "file_size_bytes": total_size},
        )
        assert init_res.status_code == 201
        upload_id = init_res.json()["id"]

        # 4. Upload chunk 0 successfully
        c0_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=chunk0,
        )
        assert c0_res.status_code == 200

        # Check temporary staging file size on disk is exactly len(chunk0)
        temp_file = settings.UPLOADS_TEMP_DIR / upload_id / "abort_sample.mp4"
        assert temp_file.exists()
        assert temp_file.stat().st_size == len(chunk0)

        # 5. Simulate mid-stream network drop during chunk 1
        async def aborting_stream():
            yield chunk1[:1024]
            raise ConnectionResetError("Simulated client connection drop")

        with pytest.raises(Exception):
            await client.put(
                f"/api/v1/media/uploads/{upload_id}/chunk",
                params={"chunk_index": 1, "offset_bytes": len(chunk0)},
                content=aborting_stream(),
            )

        # CRITICAL VERIFICATION:
        # Staging file on disk MUST be truncated back to len(chunk0), NOT len(chunk0) + 1024!
        assert temp_file.exists()
        assert temp_file.stat().st_size == len(chunk0)

        # 6. Retry uploading chunk 1 with full payload and correct offset
        c1_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 1, "offset_bytes": len(chunk0)},
            content=chunk1,
        )
        assert c1_res.status_code == 200
        assert c1_res.json()["is_complete"] is True
        assert c1_res.json()["received_size_bytes"] == total_size
        assert temp_file.stat().st_size == total_size

        # 7. Complete upload and verify file integrity
        comp_res = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert comp_res.status_code == 200
        assert comp_res.json()["status"] == "completed"
        assert comp_res.json()["video"]["file_size_bytes"] == total_size


@pytest.mark.asyncio
async def test_complete_upload_db_commit_failure_recovery(tmp_path):
    """Test B: Verify promotion succeeds, DB failure rolls back, file is retained, and retry reconciles."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Commit Fail Workspace", "local_storage_path": str(tmp_path)},
        )
        assert ws_res.status_code == 201
        ws_id = ws_res.json()["id"]

        # 2. Generate sample video and upload completely
        sample_path = tmp_path / "commit_fail.mp4"
        generate_sample_video(sample_path, duration=1)
        video_bytes = sample_path.read_bytes()
        total_size = len(video_bytes)

        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "commit_fail.mp4", "file_size_bytes": total_size},
        )
        assert init_res.status_code == 201
        upload_id = init_res.json()["id"]

        c_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=video_bytes,
        )
        assert c_res.status_code == 200

        # 3. Simulate database commit failure on completion
        original_commit = AsyncSession.commit
        fail_once = True

        async def failing_commit(self, *args, **kwargs):
            nonlocal fail_once
            if fail_once:
                fail_once = False
                raise RuntimeError("Simulated DB commit error during finalization")
            return await original_commit(self, *args, **kwargs)

        with patch.object(AsyncSession, "commit", failing_commit):
            res1 = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
            assert res1.status_code == 500
            assert "Database commit failed" in res1.json()["detail"]

        # 4. CRITICAL VERIFICATION:
        # Promoted file MUST be retained at deterministic path on disk
        target_file = settings.MEDIA_ORIGINALS_DIR / ws_id / upload_id / "commit_fail.mp4"
        assert target_file.exists()
        assert target_file.stat().st_size == total_size

        # 5. Retry complete_upload without failure: must reconcile safely
        res2 = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "completed"
        assert data2["video"]["id"] == upload_id
        assert data2["video"]["file_size_bytes"] == total_size

        # Verify DB record exists and is ready
        get_res = await client.get(f"/api/v1/media/{upload_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == upload_id


@pytest.mark.asyncio
async def test_concurrent_complete_upload_idempotency(tmp_path):
    """Test C: Verify concurrent complete_upload calls return 200 OK and maintain DB idempotency."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Concurrent Complete Workspace", "local_storage_path": str(tmp_path)},
        )
        assert ws_res.status_code == 201
        ws_id = ws_res.json()["id"]

        # 2. Upload complete video
        sample_path = tmp_path / "concurrent_complete.mp4"
        generate_sample_video(sample_path, duration=1)
        video_bytes = sample_path.read_bytes()
        total_size = len(video_bytes)

        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "concurrent_complete.mp4", "file_size_bytes": total_size},
        )
        upload_id = init_res.json()["id"]

        await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=video_bytes,
        )

        # 3. Fire 3 concurrent complete requests
        results = await asyncio.gather(
            client.post(f"/api/v1/media/uploads/{upload_id}/complete"),
            client.post(f"/api/v1/media/uploads/{upload_id}/complete"),
            client.post(f"/api/v1/media/uploads/{upload_id}/complete"),
            return_exceptions=True,
        )

        # Verify every concurrent call returned HTTP 200 with the exact same media ID
        for res in results:
            assert not isinstance(res, Exception), f"Unexpected exception in concurrent call: {res}"
            assert res.status_code == 200
            assert res.json()["status"] == "completed"
            assert res.json()["video"]["id"] == upload_id

        # 4. Verify only one DB record exists
        list_res = await client.get("/api/v1/media", params={"workspace_id": ws_id})
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == upload_id

        # 5. Sequential retry after completion should also return 200 OK
        retry_res = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert retry_res.status_code == 200
        assert retry_res.json()["status"] == "completed"
        assert retry_res.json()["video"]["id"] == upload_id


@pytest.mark.asyncio
async def test_media_delete_active_job_conflict(tmp_path):
    """Test D: Verify active job deletion lock returns 409 Conflict and preserves file and record."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace & upload media
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Job Conflict Workspace", "local_storage_path": str(tmp_path)},
        )
        ws_id = ws_res.json()["id"]

        sample_path = tmp_path / "job_conflict.mp4"
        generate_sample_video(sample_path, duration=1)
        video_bytes = sample_path.read_bytes()
        total_size = len(video_bytes)

        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "job_conflict.mp4", "file_size_bytes": total_size},
        )
        upload_id = init_res.json()["id"]

        await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=video_bytes,
        )

        comp_res = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert comp_res.status_code == 200
        media_id = comp_res.json()["video"]["id"]
        rel_path = comp_res.json()["video"]["file_path"]
        abs_media_path = safe_resolve_path(rel_path)
        assert abs_media_path.exists()

        # Wait for auto-enqueued thumbnail job to reach terminal state
        for _ in range(60):
            meta = await client.get(f"/api/v1/media/{media_id}/thumbnail/metadata")
            if meta.status_code == 200 and meta.json().get("status") in ["completed", "failed"]:
                break
            await asyncio.sleep(0.05)

        # 2. Create an active processing job referencing this media_id
        from app.models.base import generate_uuid
        job_id = generate_uuid()
        async with async_session_factory() as session:
            job = ProcessingJob(
                id=job_id,
                entity_type="media",
                entity_id=media_id,
                job_type="transcode",
                status="running",
            )
            session.add(job)
            await session.commit()

        # 3. Attempt to delete media -> MUST fail with HTTP 409 Conflict
        del_conflict = await client.delete(f"/api/v1/media/{media_id}")
        assert del_conflict.status_code == 409
        assert "active processing job" in del_conflict.json()["detail"].lower()

        # Verify file is still intact on disk and record is still in database
        assert abs_media_path.exists()
        get_res = await client.get(f"/api/v1/media/{media_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == media_id

        # 4. Mark all active jobs for this media as completed in DB
        from sqlalchemy import update
        async with async_session_factory() as session:
            await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.entity_id == media_id)
                .values(status="completed")
            )
            await session.commit()

        # 5. Deletion must now succeed
        del_success = await client.delete(f"/api/v1/media/{media_id}")
        assert del_success.status_code == 200
        assert del_success.json()["status"] == "deleted"

        # Verify file is removed from disk and DB returns 404
        assert not abs_media_path.exists()
        get_after = await client.get(f"/api/v1/media/{media_id}")
        assert get_after.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_chunk_upload_integrity(tmp_path):
    """Test E: Verify chunk sequence/offset validation under out-of-order and concurrent attempts."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Chunk Integrity Workspace", "local_storage_path": str(tmp_path)},
        )
        ws_id = ws_res.json()["id"]

        # 2. Generate sample video and split into 4 chunks
        sample_path = tmp_path / "chunk_integrity.mp4"
        generate_sample_video(sample_path, duration=1)
        video_bytes = sample_path.read_bytes()
        total_size = len(video_bytes)

        chunk_size = total_size // 4
        c0 = video_bytes[0:chunk_size]
        c1 = video_bytes[chunk_size:2 * chunk_size]
        c2 = video_bytes[2 * chunk_size:3 * chunk_size]
        c3 = video_bytes[3 * chunk_size:]

        # 3. Initiate upload
        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "chunk_integrity.mp4", "file_size_bytes": total_size},
        )
        upload_id = init_res.json()["id"]

        # 4. Send chunk 0
        r0 = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=c0,
        )
        assert r0.status_code == 200

        # 5. Out-of-order chunk: try sending chunk 2 before chunk 1
        r_skip = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 2, "offset_bytes": len(c0)},
            content=c2,
        )
        assert r_skip.status_code == 400
        assert "Expected chunk index 1" in r_skip.json()["detail"]

        # 6. Wrong offset for chunk 1
        r_bad_offset = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 1, "offset_bytes": len(c0) + 999},
            content=c1,
        )
        assert r_bad_offset.status_code == 400
        assert "Chunk offset mismatch" in r_bad_offset.json()["detail"]

        # 7. Send chunk 1 correctly
        r1 = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 1, "offset_bytes": len(c0)},
            content=c1,
        )
        assert r1.status_code == 200

        # 8. Attempt concurrent submission of chunk 2 (valid) and chunk 3 (invalid out-of-order)
        res2, res3_bad = await asyncio.gather(
            client.put(
                f"/api/v1/media/uploads/{upload_id}/chunk",
                params={"chunk_index": 2, "offset_bytes": len(c0) + len(c1)},
                content=c2,
            ),
            client.put(
                f"/api/v1/media/uploads/{upload_id}/chunk",
                params={"chunk_index": 3, "offset_bytes": len(c0) + len(c1)},
                content=c3,
            ),
        )
        statuses = {res2.status_code, res3_bad.status_code}
        assert 200 in statuses
        assert 400 in statuses

        # 9. Send chunk 3 correctly
        r3 = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 3, "offset_bytes": len(c0) + len(c1) + len(c2)},
            content=c3,
        )
        assert r3.status_code == 200
        assert r3.json()["is_complete"] is True

        # 10. Complete and verify whole-file SHA-256
        comp_res = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert comp_res.status_code == 200
        expected_sha256 = hashlib.sha256(video_bytes).hexdigest()
        assert comp_res.json()["video"]["sha256"] == expected_sha256


# --- 4. Phase 2A.2 Targeted Reliability Hardening Regression Tests ---

@pytest.mark.asyncio
async def test_concurrent_identical_chunks_serialization(tmp_path):
    """Fix 1 (SEC-A4-01): Verify that simultaneous identical chunk requests are serialized and cannot corrupt disk or DB."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Concurrent Identical Workspace", "local_storage_path": str(tmp_path)},
        )
        ws_id = ws_res.json()["id"]

        # 2. Generate sample video
        sample_path = tmp_path / "concurrent_identical.mp4"
        generate_sample_video(sample_path, duration=1)
        video_bytes = sample_path.read_bytes()
        total_size = len(video_bytes)

        mid = total_size // 2
        chunk0 = video_bytes[:mid]
        chunk1 = video_bytes[mid:]

        # 3. Initiate upload session 1
        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "concurrent_identical.mp4", "file_size_bytes": total_size},
        )
        upload_id = init_res.json()["id"]

        # 4. Fire TWO simultaneous requests for chunk 0 with IDENTICAL parameters and payload
        res_a, res_b = await asyncio.gather(
            client.put(
                f"/api/v1/media/uploads/{upload_id}/chunk",
                params={"chunk_index": 0, "offset_bytes": 0},
                content=chunk0,
            ),
            client.put(
                f"/api/v1/media/uploads/{upload_id}/chunk",
                params={"chunk_index": 0, "offset_bytes": 0},
                content=chunk0,
            ),
        )

        # Both must return HTTP 200 (one processes chunk, second serialized and returns idempotent 200)
        assert res_a.status_code == 200
        assert res_b.status_code == 200

        data_a = res_a.json()
        data_b = res_b.json()
        assert data_a["received_size_bytes"] == len(chunk0)
        assert data_b["received_size_bytes"] == len(chunk0)

        # 5. Verify staging file on disk contains EXACTLY len(chunk0) bytes (NO interleaved duplicate writes!)
        staging_file = settings.UPLOADS_TEMP_DIR / upload_id / "concurrent_identical.mp4"
        assert staging_file.exists()
        assert staging_file.stat().st_size == len(chunk0)
        assert staging_file.read_bytes() == chunk0

        # 6. Verify database session state
        async with async_session_factory() as db_session:
            from app.models.upload import UploadSession
            sess = await db_session.get(UploadSession, upload_id)
            assert sess.received_size_bytes == len(chunk0)
            assert sess.last_chunk_index == 0
            assert sess.chunk_count == 1

        # 7. Test independent concurrency across two separate upload sessions:
        init_res_2 = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "separate_session.mp4", "file_size_bytes": total_size},
        )
        upload_id_2 = init_res_2.json()["id"]

        # Concurrently upload chunk 1 for session 1 and chunk 0 for session 2
        r_sess1, r_sess2 = await asyncio.gather(
            client.put(
                f"/api/v1/media/uploads/{upload_id}/chunk",
                params={"chunk_index": 1, "offset_bytes": len(chunk0)},
                content=chunk1,
            ),
            client.put(
                f"/api/v1/media/uploads/{upload_id_2}/chunk",
                params={"chunk_index": 0, "offset_bytes": 0},
                content=chunk0,
            ),
        )
        assert r_sess1.status_code == 200
        assert r_sess2.status_code == 200
        assert r_sess1.json()["is_complete"] is True
        assert r_sess2.json()["received_size_bytes"] == len(chunk0)


@pytest.mark.asyncio
async def test_chunk_rollback_truncation_failure_marks_session_failed(tmp_path):
    """Fix 2 (SEC-A3-01): Verify that if rollback truncation fails, it is logged and the session is permanently marked failed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace & initiate upload
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "Truncate Fail Workspace", "local_storage_path": str(tmp_path)},
        )
        ws_id = ws_res.json()["id"]

        sample_path = tmp_path / "trunc_fail.mp4"
        generate_sample_video(sample_path, duration=1)
        video_bytes = sample_path.read_bytes()
        total_size = len(video_bytes)

        mid = total_size // 2
        chunk0 = video_bytes[:mid]
        chunk1 = video_bytes[mid:]

        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "trunc_fail.mp4", "file_size_bytes": total_size},
        )
        upload_id = init_res.json()["id"]

        # Send chunk 0 successfully
        c0_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=chunk0,
        )
        assert c0_res.status_code == 200

        # 2. Simulate streaming abort where truncate() ALSO fails
        import builtins
        real_open = builtins.open

        class TruncateFailingWrapper:
            def __init__(self, raw):
                self._raw = raw
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return self._raw.__exit__(*args)
            def seek(self, *a, **k):
                return self._raw.seek(*a, **k)
            def write(self, *a, **k):
                return self._raw.write(*a, **k)
            def flush(self):
                return self._raw.flush()
            def truncate(self, *a, **k):
                raise OSError("Simulated hardware I/O error on truncate")

        def custom_open(file, mode="r", *args, **kwargs):
            f = real_open(file, mode, *args, **kwargs)
            if "trunc_fail.mp4" in str(file) and "r+b" in mode:
                return TruncateFailingWrapper(f)
            return f

        async def aborting_stream():
            yield chunk1[:500]
            raise ConnectionResetError("Client connection dropped mid-stream")

        # 3. Stream fails and truncate fails: original ConnectionResetError must be preserved
        with patch("builtins.open", custom_open):
            with pytest.raises(Exception) as exc_info:
                await client.put(
                    f"/api/v1/media/uploads/{upload_id}/chunk",
                    params={"chunk_index": 1, "offset_bytes": len(chunk0)},
                    content=aborting_stream(),
                )
            assert "Client connection dropped mid-stream" in str(exc_info.value) or isinstance(exc_info.value, ConnectionResetError)

        # 4. In database: UploadSession MUST be marked 'failed' permanently
        async with async_session_factory() as db_session:
            from app.models.upload import UploadSession
            sess = await db_session.get(UploadSession, upload_id)
            assert sess.status == "failed"

        # 5. Subsequent chunk request on this damaged session MUST be rejected
        retry_res = await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 1, "offset_bytes": len(chunk0)},
            content=chunk1,
        )
        assert retry_res.status_code == 400
        assert "not active" in retry_res.json()["detail"].lower()
        assert "failed" in retry_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promoted_file_recovery_sha256_integrity_verification(tmp_path):
    """Fix 3 (SEC-A2-01): Verify that promoted-file recovery validates against recorded session SHA-256 and rejects corrupt/mismatched content."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create workspace
        ws_res = await client.post(
            "/api/v1/workspaces",
            json={"name": "SHA Integrity Workspace", "local_storage_path": str(tmp_path)},
        )
        ws_id = ws_res.json()["id"]

        # 2. Generate valid sample video A
        sample_a_path = tmp_path / "valid_a.mp4"
        generate_sample_video(sample_a_path, duration=1)
        video_a_bytes = sample_a_path.read_bytes()
        total_size = len(video_a_bytes)
        expected_sha = hashlib.sha256(video_a_bytes).hexdigest()

        # Generate a distinct sample video B with different bytes of identical byte size
        sample_b_path = tmp_path / "valid_b.mp4"
        generate_sample_video(sample_b_path, duration=1)
        video_b_bytes = sample_b_path.read_bytes()
        # Ensure identical size but different payload
        video_b_tampered = video_b_bytes[:total_size - 16] + b"TAMPERED_CONTENT"
        if len(video_b_tampered) < total_size:
            video_b_tampered += b"X" * (total_size - len(video_b_tampered))
        elif len(video_b_tampered) > total_size:
            video_b_tampered = video_b_tampered[:total_size]
        assert len(video_b_tampered) == total_size
        tampered_sha = hashlib.sha256(video_b_tampered).hexdigest()
        assert tampered_sha != expected_sha

        # 3. Initiate upload and stream chunk for video A
        init_res = await client.post(
            "/api/v1/media/uploads/initiate",
            json={"workspace_id": ws_id, "filename": "valid_a.mp4", "file_size_bytes": total_size},
        )
        upload_id = init_res.json()["id"]

        await client.put(
            f"/api/v1/media/uploads/{upload_id}/chunk",
            params={"chunk_index": 0, "offset_bytes": 0},
            content=video_a_bytes,
        )

        # 4. Record expected_sha in the UploadSession (simulating prior recorded hash)
        async with async_session_factory() as db_session:
            from app.models.upload import UploadSession
            sess = await db_session.get(UploadSession, upload_id)
            sess.sha256 = expected_sha
            await db_session.commit()

        # 5. Place tampered file (matching size, mismatched SHA-256) at deterministic promoted path
        target_dir = settings.MEDIA_ORIGINALS_DIR / ws_id / upload_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "valid_a.mp4"
        target_file.write_bytes(video_b_tampered)

        # 6. Call complete_upload -> MUST detect integrity mismatch and return HTTP 409 Conflict
        comp_mismatch = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert comp_mismatch.status_code == 409
        assert "integrity mismatch" in comp_mismatch.json()["detail"].lower()

        # Verify session SHA-256 in DB was NOT overwritten with tampered hash
        async with async_session_factory() as db_session:
            from app.models.upload import UploadSession
            sess = await db_session.get(UploadSession, upload_id)
            assert sess.sha256 == expected_sha
            assert sess.sha256 != tampered_sha

        # Verify NO ImportedVideo was created
        async with async_session_factory() as db_session:
            video_rec = await db_session.get(ImportedVideo, upload_id)
            assert video_rec is None

        # 7. Restore the authentic video content matching expected_sha
        target_file.write_bytes(video_a_bytes)

        # 8. Retry complete_upload -> MUST now succeed with HTTP 200 OK
        comp_success = await client.post(f"/api/v1/media/uploads/{upload_id}/complete")
        assert comp_success.status_code == 200
        assert comp_success.json()["status"] == "completed"
        assert comp_success.json()["video"]["sha256"] == expected_sha
        assert comp_success.json()["video"]["id"] == upload_id
