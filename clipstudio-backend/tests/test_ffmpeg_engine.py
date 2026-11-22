import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from app.api.websockets.connection import ws_manager
from app.config import settings
from app.database import async_session_factory
from app.main import app
from app.models.job import ProcessingJob
from app.services.ffmpeg import (
    FFmpegExecutableException,
    FFmpegExecutionException,
    FFmpegExecutionResult,
    FFmpegProgress,
    FFmpegProgressParser,
    FFmpegRunner,
    FFmpegRuntimeInfo,
    FFmpegTimeoutException,
    detect_ffmpeg_runtime,
    parse_encoders,
    parse_ffmpeg_version,
    parse_hwaccels,
    parse_speed_multiplier,
    parse_time_to_seconds,
    resolve_ffmpeg_executable,
    resolve_ffprobe_executable,
)
from app.services.job_queue import job_queue


# ==============================================================================
# 1. Detection and Runtime Inspection Tests
# ==============================================================================


def test_resolve_ffmpeg_executable():
    """Verifies that the host FFmpeg executable is successfully resolved."""
    exe_path = resolve_ffmpeg_executable()
    assert exe_path is not None
    assert Path(exe_path).exists()
    assert "ffmpeg" in Path(exe_path).name.lower()


def test_resolve_ffprobe_executable():
    """Verifies that the host FFprobe executable is successfully resolved."""
    exe_path = resolve_ffprobe_executable()
    assert exe_path is not None
    assert Path(exe_path).exists()
    assert "ffprobe" in Path(exe_path).name.lower()


def test_resolve_ffmpeg_config_override(tmp_path, monkeypatch):
    """Verifies that settings.FFMPEG_PATH takes priority if configured and valid."""
    fake_ffmpeg = tmp_path / "custom_ffmpeg.exe"
    fake_ffmpeg.write_text("fake binary")

    monkeypatch.setattr(settings, "FFMPEG_PATH", str(fake_ffmpeg))
    resolved = resolve_ffmpeg_executable()
    assert resolved == str(fake_ffmpeg)


def test_resolve_ffmpeg_missing_raises_exception(monkeypatch):
    """Verifies that FFmpegExecutableException is raised when binary cannot be found."""
    monkeypatch.setattr(settings, "FFMPEG_PATH", None)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("app.services.ffmpeg.runtime._get_candidate_binary_paths", lambda name: [])

    with pytest.raises(FFmpegExecutableException) as exc_info:
        resolve_ffmpeg_executable()
    assert "FFmpeg executable could not be resolved" in str(exc_info.value.message)


def test_parse_ffmpeg_version_strings():
    """Verifies version and build parsing against multiple real-world formats."""
    # Format 1: Gyan full build
    gyan_sample = (
        "ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026\n"
        "built with gcc 16.2.0 (Rev3, Built by MSYS2 project)\n"
    )
    v1, b1 = parse_ffmpeg_version(gyan_sample)
    assert v1 == "9.0.2-full_build-www.gyan.dev"
    assert "gcc 16.2.0" in b1

    # Format 2: Official release build
    ubuntu_sample = (
        "ffmpeg version 6.1.1-1ubuntu1 Copyright (c) 2000-2023 the FFmpeg developers\n"
        "built with gcc 13.2.0 (Ubuntu 13.2.0-4ubuntu3)\n"
    )
    v2, b2 = parse_ffmpeg_version(ubuntu_sample)
    assert v2 == "6.1.1-1ubuntu1"
    assert "gcc 13.2.0" in b2

    # Format 3: Git hash build
    git_sample = "ffmpeg version n6.1.1-2-g4f05b14c33 Copyright (c) 2000-2024\n"
    v3, b3 = parse_ffmpeg_version(git_sample)
    assert v3 == "n6.1.1-2-g4f05b14c33"
    assert b3 is None

    # Empty
    v4, b4 = parse_ffmpeg_version("")
    assert v4 is None
    assert b4 is None


def test_parse_hwaccels():
    """Verifies extraction of hardware acceleration methods."""
    sample = (
        "ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026\n"
        "Hardware acceleration methods:\n"
        "cuda\n"
        "vaapi\n"
        "dxva2\n"
        "qsv\n"
        "d3d11va\n"
        "opencl\n"
        "vulkan\n"
    )
    hw = parse_hwaccels(sample)
    assert hw == ["cuda", "vaapi", "dxva2", "qsv", "d3d11va", "opencl", "vulkan"]


def test_parse_encoders():
    """Verifies parsing of video/audio encoders from ffmpeg -encoders table."""
    sample = (
        "Encoders:\n"
        " V..... = Video\n"
        " A..... = Audio\n"
        " ------\n"
        " V..... libx264              libx264 H.264 / AVC\n"
        " V..... libx265              libx265 H.265 / HEVC\n"
        " V..... h264_qsv             H.264 / AVC (Intel Quick Sync Video)\n"
        " A..... aac                  AAC (Advanced Audio Coding)\n"
    )
    encoders = parse_encoders(sample)
    assert "libx264" in encoders
    assert "libx265" in encoders
    assert "h264_qsv" in encoders
    assert "aac" in encoders


@pytest.mark.asyncio
async def test_detect_ffmpeg_runtime_live():
    """Verifies real system runtime detection returns populated FFmpegRuntimeInfo."""
    info = await detect_ffmpeg_runtime(force_refresh=True)
    assert info.available is True
    assert info.ffmpeg_path is not None
    assert info.version is not None
    assert isinstance(info.hwaccels, list)
    assert isinstance(info.encoders, list)
    assert info.error is None


# ==============================================================================
# 2. Progress Parsing Tests
# ==============================================================================


def test_parse_time_to_seconds():
    """Verifies conversion of HH:MM:SS.fraction to floating-point seconds."""
    assert parse_time_to_seconds("00:00:01.000000") == 1.0
    assert parse_time_to_seconds("00:01:30.500000") == 90.5
    assert parse_time_to_seconds("01:00:00.000000") == 3600.0
    assert parse_time_to_seconds("00:00:00.000000") == 0.0
    assert parse_time_to_seconds("N/A") == 0.0
    assert parse_time_to_seconds("") == 0.0


def test_parse_speed_multiplier():
    """Verifies parsing of FFmpeg speed multiplier strings."""
    assert parse_speed_multiplier(" 136x") == 136.0
    assert parse_speed_multiplier("1.50x") == 1.5
    assert parse_speed_multiplier("0.85x") == 0.85
    assert parse_speed_multiplier("N/A") is None
    assert parse_speed_multiplier("") is None


def test_progress_parser_single_block():
    """Verifies parsing a single machine-readable progress block."""
    parser = FFmpegProgressParser(total_duration_seconds=10.0)
    data = (
        "frame=150\n"
        "fps=30.00\n"
        "stream_0_0_q=-0.0\n"
        "bitrate=1200.5kbits/s\n"
        "total_size=1048576\n"
        "out_time_us=5000000\n"
        "out_time_ms=5000000\n"
        "out_time=00:00:05.000000\n"
        "dup_frames=0\n"
        "drop_frames=0\n"
        "speed= 2.0x\n"
        "progress=continue\n"
    )
    items = parser.feed(data)
    assert len(items) == 1
    prog = items[0]
    assert prog.frame == 150
    assert prog.fps == 30.0
    assert prog.bitrate == "1200.5kbits/s"
    assert prog.total_size == 1048576
    assert prog.out_time_seconds == 5.0
    assert prog.out_time_str == "00:00:05.000000"
    assert prog.speed == 2.0
    assert prog.progress_status == "continue"
    assert prog.percent == 50.0  # 5.0 / 10.0 * 100
    assert prog.is_finished is False


def test_progress_parser_chunked_streaming():
    """Verifies stream parser handles fragmented and split chunks correctly."""
    parser = FFmpegProgressParser(total_duration_seconds=5.0)
    full_text = (
        "frame=60\n"
        "fps=30.00\n"
        "bitrate=800kbits/s\n"
        "total_size=512000\n"
        "out_time_us=2000000\n"
        "out_time=00:00:02.000000\n"
        "speed=1.0x\n"
        "progress=continue\n"
        "frame=150\n"
        "fps=30.00\n"
        "bitrate=850kbits/s\n"
        "total_size=1200000\n"
        "out_time_us=5000000\n"
        "out_time=00:00:05.000000\n"
        "speed=1.2x\n"
        "progress=end\n"
    )

    # Split into arbitrary 7-byte chunks to test buffer boundary handling
    all_items = []
    chunk_size = 7
    for i in range(0, len(full_text), chunk_size):
        chunk = full_text[i:i + chunk_size]
        items = parser.feed(chunk)
        all_items.extend(items)

    assert len(all_items) == 2
    assert all_items[0].frame == 60
    assert all_items[0].percent == 40.0
    assert all_items[0].progress_status == "continue"

    assert all_items[1].frame == 150
    assert all_items[1].percent == 100.0
    assert all_items[1].progress_status == "end"
    assert all_items[1].is_finished is True


def test_progress_parser_missing_fields_and_no_duration():
    """Verifies parser does not fabricate percentage if duration is unknown."""
    parser = FFmpegProgressParser(total_duration_seconds=None)
    data = (
        "frame=30\n"
        "bitrate=N/A\n"
        "total_size=N/A\n"
        "out_time=N/A\n"
        "speed=N/A\n"
        "progress=continue\n"
    )
    items = parser.feed(data)
    assert len(items) == 1
    prog = items[0]
    assert prog.frame == 30
    assert prog.bitrate == "N/A"
    assert prog.percent is None  # Strict adherence: no fabricated percentage
    assert prog.speed is None


# ==============================================================================
# 3. Subprocess Runner Execution Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_runner_real_synthetic_execution():
    """Verifies FFmpegRunner executes real FFmpeg synthetic generation command."""
    runner = FFmpegRunner()
    captured_progress = []

    def on_prog(p: FFmpegProgress):
        captured_progress.append(p)

    cmd = [
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=30",
        "-f", "null",
        "-",
    ]

    result = await runner.run(
        args=cmd,
        total_duration_seconds=1.0,
        progress_callback=on_prog,
    )

    assert result.success is True
    assert result.returncode == 0
    assert result.duration_seconds > 0.0
    assert result.pid is not None
    assert result.error_message is None
    assert len(captured_progress) >= 1
    assert captured_progress[-1].is_finished is True
    assert captured_progress[-1].percent == 100.0


@pytest.mark.asyncio
async def test_runner_bounded_stderr_tail():
    """Verifies stderr capture is strictly bounded to max_stderr_bytes."""
    max_bytes = 256
    runner = FFmpegRunner(max_stderr_bytes=max_bytes)

    # Use a command that writes banner + progress info
    cmd = [
        "-f", "lavfi",
        "-i", "testsrc=duration=0.5:size=160x120:rate=25",
        "-f", "null",
        "-",
    ]
    result = await runner.run(args=cmd, timeout_seconds=10.0)
    assert result.success is True
    # The recorded stderr must not exceed max_bytes
    assert len(result.stderr.encode("utf-8")) <= max_bytes + 64


@pytest.mark.asyncio
async def test_runner_invalid_arguments_failure():
    """Verifies non-zero exit code captures stderr and flags failure."""
    runner = FFmpegRunner()
    cmd = ["-invalid_nonexistent_flag_clipstudio"]

    result = await runner.run(args=cmd)
    assert result.success is False
    assert result.returncode != 0
    assert result.error_message is not None
    assert "failed with code" in result.error_message


@pytest.mark.asyncio
async def test_runner_timeout_termination():
    """Verifies timeout triggers process tree termination and raises FFmpegTimeoutException."""
    runner = FFmpegRunner()
    # Use -re to enforce real-time rate so process takes actual seconds and triggers timeout
    cmd = [
        "-re",
        "-f", "lavfi",
        "-i", "testsrc=duration=5:size=320x240:rate=30",
        "-f", "null",
        "-",
    ]

    with pytest.raises(FFmpegTimeoutException) as exc_info:
        await runner.run(args=cmd, timeout_seconds=0.3)
    assert "timed out after 0.3 seconds" in str(exc_info.value.message)
    assert runner.active_pid is None


@pytest.mark.asyncio
async def test_runner_task_cancellation():
    """Verifies task cancellation terminates the subprocess cleanly."""
    runner = FFmpegRunner()
    cmd = [
        "-re",
        "-f", "lavfi",
        "-i", "testsrc=duration=5:size=320x240:rate=30",
        "-f", "null",
        "-",
    ]

    task = asyncio.create_task(runner.run(args=cmd, timeout_seconds=30.0))
    await asyncio.sleep(0.3)
    pid = runner.active_pid
    assert pid is not None

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Process should be terminated
    assert runner.active_pid is None


# ==============================================================================
# 4. Job Queue Integration Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_job_queue_ffmpeg_lifecycle():
    """Verifies full FFmpeg job dispatch, progress streaming, and completion in JobQueueService."""
    await job_queue.cancel_all_active_jobs()
    await asyncio.sleep(0.05)

    cmd = [
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=30",
        "-f", "null",
        "-",
    ]

    job = await job_queue.create_job(
        job_type="ffmpeg_job",
        entity_type="test_video",
        entity_id="test_vid_001",
        payload={
            "args": cmd,
            "total_duration_seconds": 1.0,
            "description": "Synthetic transcoding verification",
        },
    )
    job_id = job.id

    # Wait for completion (poll database)
    for _ in range(60):
        await asyncio.sleep(0.1)
        async with async_session_factory() as session:
            refreshed = await session.get(ProcessingJob, job_id)
            if refreshed and refreshed.status in ["completed", "failed", "cancelled"]:
                break

    async with async_session_factory() as session:
        final_job = await session.get(ProcessingJob, job_id)
        assert final_job is not None
        assert final_job.status == "completed"
        assert final_job.progress_percent == 100.0
        assert final_job.completed_at is not None
        assert "Completed" in final_job.current_step


@pytest.mark.asyncio
async def test_job_queue_ffmpeg_cancellation():
    """Verifies job_queue.cancel_job aborts an active FFmpeg job and sets status to cancelled."""
    await job_queue.cancel_all_active_jobs()
    await asyncio.sleep(0.05)

    cmd = [
        "-re",
        "-f", "lavfi",
        "-i", "testsrc=duration=5:size=320x240:rate=30",
        "-f", "null",
        "-",
    ]

    job = await job_queue.create_job(
        job_type="ffmpeg_job",
        entity_type="test_video",
        entity_id="test_vid_cancel",
        payload={
            "args": cmd,
            "total_duration_seconds": 5.0,
            "description": "Long test job for cancellation",
        },
    )
    job_id = job.id

    # Allow it to start
    await asyncio.sleep(0.3)
    cancelled = await job_queue.cancel_job(job_id)
    assert cancelled is True

    # Wait for cancellation status to persist
    for _ in range(60):
        await asyncio.sleep(0.1)
        async with async_session_factory() as session:
            refreshed = await session.get(ProcessingJob, job_id)
            if refreshed and refreshed.status == "cancelled":
                break

    async with async_session_factory() as session:
        final_job = await session.get(ProcessingJob, job_id)
        assert final_job is not None
        assert final_job.status == "cancelled"


# ==============================================================================
# 5. API Health & Capability Endpoint Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_health_endpoint_includes_ffmpeg():
    """Verifies GET /api/v1/health exposes FFmpeg capabilities in its payload."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "ffmpeg" in data
        assert data["ffmpeg"]["available"] is True
        assert data["ffmpeg"]["version"] is not None
        assert "hwaccels" in data["ffmpeg"]


@pytest.mark.asyncio
async def test_health_ffmpeg_dedicated_endpoint():
    """Verifies GET /api/v1/health/ffmpeg returns full runtime capability dictionary."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/health/ffmpeg?refresh=true")
        assert res.status_code == 200
        data = res.json()
        assert data["available"] is True
        assert data["version"] is not None
        assert isinstance(data["hwaccels"], list)
        assert isinstance(data["encoders"], list)


# ==============================================================================
# 6. Terminal Job State Protection Tests (CS-AUDIT-2B1-001)
# ==============================================================================


@pytest.mark.asyncio
async def test_terminal_state_protection_completed_job():
    """Verifies a stale running progress callback cannot change a completed job back to running."""
    await job_queue.cancel_all_active_jobs()
    async with async_session_factory() as session:
        job = ProcessingJob(
            job_type="ffmpeg_job",
            entity_type="test_video",
            status="completed",
            progress_percent=100.0,
            current_step="Completed",
            result_data='{"returncode": 0, "duration_seconds": 12.5}',
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    # Attempt to inject a late running progress callback
    await job_queue._update_job_progress(
        job_id=job_id,
        status="running",
        progress_percent=55.0,
        current_step="Stale late FFmpeg progress frame 500",
        message="Stale frame update",
    )

    # Verify database state was untouched
    async with async_session_factory() as session:
        refreshed = await session.get(ProcessingJob, job_id)
        assert refreshed is not None
        assert refreshed.status == "completed"
        assert refreshed.progress_percent == 100.0
        assert refreshed.current_step == "Completed"
        assert refreshed.result_data == '{"returncode": 0, "duration_seconds": 12.5}'


@pytest.mark.asyncio
async def test_terminal_state_protection_cancelled_job():
    """Verifies a stale running progress callback cannot change a cancelled job back to running."""
    await job_queue.cancel_all_active_jobs()
    async with async_session_factory() as session:
        job = ProcessingJob(
            job_type="ffmpeg_job",
            entity_type="test_video",
            status="cancelled",
            progress_percent=33.0,
            current_step="Cancelled by user request",
            error_message="User requested cancellation.",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    # Attempt to inject a late running progress callback
    await job_queue._update_job_progress(
        job_id=job_id,
        status="running",
        progress_percent=75.0,
        current_step="Stale late transcode step",
        message="Stale progress update",
    )

    # Verify database state was untouched
    async with async_session_factory() as session:
        refreshed = await session.get(ProcessingJob, job_id)
        assert refreshed is not None
        assert refreshed.status == "cancelled"
        assert refreshed.progress_percent == 33.0
        assert refreshed.current_step == "Cancelled by user request"
        assert refreshed.error_message == "User requested cancellation."


@pytest.mark.asyncio
async def test_terminal_state_protection_failed_job():
    """Verifies a stale running progress callback cannot change a failed job back to running."""
    await job_queue.cancel_all_active_jobs()
    async with async_session_factory() as session:
        job = ProcessingJob(
            job_type="ffmpeg_job",
            entity_type="test_video",
            status="failed",
            progress_percent=12.0,
            current_step="Failed with exit code 1",
            error_message="Fatal FFmpeg transcode error: corrupted stream.",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    # Attempt to inject a late running progress callback
    await job_queue._update_job_progress(
        job_id=job_id,
        status="running",
        progress_percent=85.0,
        current_step="Stale step after failure",
        message="Stale message",
    )

    # Verify database state was untouched
    async with async_session_factory() as session:
        refreshed = await session.get(ProcessingJob, job_id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.progress_percent == 12.0
        assert refreshed.current_step == "Failed with exit code 1"
        assert refreshed.error_message == "Fatal FFmpeg transcode error: corrupted stream."


@pytest.mark.asyncio
async def test_active_running_job_progress_updates_succeed():
    """Verifies legitimate progress updates for an active running job succeed normally."""
    await job_queue.cancel_all_active_jobs()
    async with async_session_factory() as session:
        job = ProcessingJob(
            job_type="ffmpeg_job",
            entity_type="test_video",
            status="running",
            progress_percent=10.0,
            current_step="Initial processing",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    # Normal progress update
    await job_queue._update_job_progress(
        job_id=job_id,
        status="running",
        progress_percent=45.5,
        current_step="Processing frame 455",
        message="Processed frame 455 (45.5%)",
    )

    # Verify database state updated
    async with async_session_factory() as session:
        refreshed = await session.get(ProcessingJob, job_id)
        assert refreshed is not None
        assert refreshed.status == "running"
        assert refreshed.progress_percent == 45.5
        assert refreshed.current_step == "Processing frame 455"


@pytest.mark.asyncio
async def test_terminal_state_preserves_completion_timestamps_and_result_data():
    """Verifies terminal metadata (completed_at, result_data) is never wiped by rejected updates."""
    from datetime import datetime, timezone
    completed_time = datetime.now(timezone.utc)

    await job_queue.cancel_all_active_jobs()
    async with async_session_factory() as session:
        job = ProcessingJob(
            job_type="ffmpeg_job",
            entity_type="test_video",
            status="completed",
            progress_percent=100.0,
            current_step="Completed",
            completed_at=completed_time,
            result_data='{"verified": true}',
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    # Attempt to inject running progress and conflicting queued state
    await job_queue._update_job_progress(
        job_id=job_id,
        status="running",
        progress_percent=0.0,
        current_step="Reset to running",
        message="Stale reset",
    )
    await job_queue._update_job_progress(
        job_id=job_id,
        status="queued",
        progress_percent=0.0,
        current_step="Reset to queued",
        message="Stale queued",
    )

    async with async_session_factory() as session:
        refreshed = await session.get(ProcessingJob, job_id)
        assert refreshed is not None
        assert refreshed.status == "completed"
        assert refreshed.progress_percent == 100.0
        assert refreshed.current_step == "Completed"
        assert refreshed.result_data == '{"verified": true}'
        assert refreshed.completed_at is not None
