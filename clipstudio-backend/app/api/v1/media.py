import asyncio
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.core.logging import logger
from app.database import get_db
from app.models.job import ProcessingJob
from app.models.upload import UploadSession
from app.models.video import ImportedVideo
from app.models.workspace import Workspace
from app.schemas.upload import (
    UploadChunkResponse,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadInitiateRequest,
    UploadSessionRead,
)
from app.schemas.video import ImportedVideoRead, MediaListResponse, ThumbnailMetadataResponse
from app.services.media_probe import MediaValidationException, extract_media_specs, probe_media_file
from app.services.storage import (
    StorageException,
    atomic_promote_file,
    check_disk_space,
    cleanup_directory,
    compute_sha256_stream,
    safe_resolve_path,
    sanitize_filename,
)
from app.api.websockets.connection import ws_manager

router = APIRouter(prefix="/media", tags=["Media"])


@router.post("/uploads/initiate", response_model=UploadSessionRead, status_code=status.HTTP_201_CREATED)
async def initiate_upload(
    payload: UploadInitiateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Initiate a persistent upload session with storage and disk capacity validation."""
    # 1. Validate target workspace exists
    ws_result = await db.execute(select(Workspace).where(Workspace.id == payload.workspace_id))
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target workspace {payload.workspace_id} not found.",
        )

    # 2. Enforce configured max upload size limit
    if payload.file_size_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
        max_gb = settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed upload size of {max_gb:.1f} GB.",
        )

    if payload.file_size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size must be greater than zero bytes.",
        )

    # 3. Check disk space safety margin (file size + 1 GB reserve)
    is_ok, free_bytes, message = check_disk_space(payload.file_size_bytes)
    if not is_ok:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=message,
        )

    # 4. Generate isolated temporary staging path
    from app.models.base import generate_uuid
    upload_id = generate_uuid()
    sanitized_name = sanitize_filename(payload.filename)

    staging_dir = settings.UPLOADS_TEMP_DIR / upload_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = staging_dir / sanitized_name

    # Initialize empty file
    with open(temp_file_path, "wb"):
        pass

    # Store relative path in database
    relative_temp_path = f"temp/uploads/{upload_id}/{sanitized_name}"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS)

    # 5. Create persistent UploadSession
    session = UploadSession(
        id=upload_id,
        workspace_id=payload.workspace_id,
        original_filename=payload.filename,
        expected_size_bytes=payload.file_size_bytes,
        received_size_bytes=0,
        status="active",
        temporary_path=relative_temp_path,
        chunk_count=0,
        last_chunk_index=-1,
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return session


_upload_locks: dict[str, asyncio.Lock] = {}
_locks_mutex = asyncio.Lock()


async def get_upload_lock(upload_id: str) -> asyncio.Lock:
    """Acquire a per-upload-session asyncio Lock to serialize concurrent chunk and finalize calls."""
    async with _locks_mutex:
        if upload_id not in _upload_locks:
            _upload_locks[upload_id] = asyncio.Lock()
        return _upload_locks[upload_id]


@router.put("/uploads/{upload_id}/chunk", response_model=UploadChunkResponse)
async def upload_chunk(
    upload_id: str,
    request: Request,
    chunk_index: int = Query(..., ge=0, description="Sequential chunk index starting at 0"),
    offset_bytes: int = Query(..., ge=0, description="Byte offset in file"),
    db: AsyncSession = Depends(get_db),
):
    """Stream a binary chunk directly to disk with sequence and offset validation.

    Note on Concurrency & Retry Protocol (SEC-A4-01, MF-02):
    All chunk and completion operations for a session are serialized by an in-process asyncio Lock.
    If a chunk upload fails or is aborted mid-stream (e.g. network disconnect),
    the server truncates the staging file back to the known valid offset (session.received_size_bytes).
    The client must retry the chunk by re-sending the FULL chunk payload starting from
    the chunk's original starting offset (offset_bytes == session.received_size_bytes).
    If truncation fails, the session is permanently marked 'failed' to prevent silent corruption (SEC-A3-01).
    """
    lock = await get_upload_lock(upload_id)
    async with lock:
        # 1. Fetch active session
        sess_result = await db.execute(select(UploadSession).where(UploadSession.id == upload_id))
        session = sess_result.scalar_one_or_none()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Upload session {upload_id} not found.",
            )

        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Upload session is not active (current status: {session.status}).",
            )

        # Check expiration
        now = datetime.now(timezone.utc)
        if session.expires_at.tzinfo is None:
            session_expires = session.expires_at.replace(tzinfo=timezone.utc)
        else:
            session_expires = session.expires_at

        if now > session_expires:
            session.status = "expired"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Upload session has expired.",
            )

        # 2. Chunk sequence & offset validation
        if chunk_index == session.last_chunk_index:
            # Idempotent re-submission of current chunk
            return UploadChunkResponse(
                upload_id=session.id,
                received_size_bytes=session.received_size_bytes,
                expected_size_bytes=session.expected_size_bytes,
                chunk_index=chunk_index,
                is_complete=(session.received_size_bytes == session.expected_size_bytes),
            )

        if chunk_index != session.last_chunk_index + 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Chunk sequence error. Expected chunk index {session.last_chunk_index + 1}, "
                    f"received {chunk_index}."
                ),
            )

        if offset_bytes != session.received_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Chunk offset mismatch. Expected offset {session.received_size_bytes}, "
                    f"received {offset_bytes}."
                ),
            )

        # 3. Stream chunk directly to disk with mid-stream abort recovery (HF-01, SEC-A3-01)
        abs_temp_path = safe_resolve_path(session.temporary_path)
        if not abs_temp_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Temporary staging file disappeared from storage.",
            )

        initial_offset = session.received_size_bytes
        bytes_written = 0

        try:
            with open(abs_temp_path, "r+b") as f:
                f.seek(initial_offset)
                async for chunk_slice in request.stream():
                    if chunk_slice:
                        f.write(chunk_slice)
                        bytes_written += len(chunk_slice)
                f.flush()
        except BaseException as stream_err:
            # Truncate staging file back to initial_offset to strip any partial writes
            try:
                with open(abs_temp_path, "r+b") as f:
                    f.seek(initial_offset)
                    f.truncate()
                    f.flush()
            except Exception as trunc_err:
                logger.error(
                    f"Upload session {upload_id}: Failed to truncate staging file after stream abort. "
                    f"Initial offset: {initial_offset}, Truncate error: {trunc_err}"
                )
                try:
                    session.status = "failed"
                    await db.commit()
                except Exception as db_err:
                    logger.error(
                        f"Upload session {upload_id}: Failed to persist 'failed' status to DB: {db_err}"
                    )
                    try:
                        await db.rollback()
                    except Exception:
                        pass
            raise

        # Enforce expected size
        new_received_total = initial_offset + bytes_written
        if new_received_total > session.expected_size_bytes:
            try:
                with open(abs_temp_path, "r+b") as f:
                    f.seek(initial_offset)
                    f.truncate()
                    f.flush()
            except Exception as trunc_err:
                logger.error(
                    f"Upload session {upload_id}: Failed to truncate staging file after size exceeded. "
                    f"Initial offset: {initial_offset}, Truncate error: {trunc_err}"
                )
                try:
                    session.status = "failed"
                    await db.commit()
                except Exception as db_err:
                    logger.error(
                        f"Upload session {upload_id}: Failed to persist 'failed' status to DB: {db_err}"
                    )
                    try:
                        await db.rollback()
                    except Exception:
                        pass
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Received bytes ({new_received_total}) exceed declared file size "
                    f"({session.expected_size_bytes})."
                ),
            )

        # 4. Update session
        session.received_size_bytes = new_received_total
        session.chunk_count += 1
        session.last_chunk_index = chunk_index
        await db.commit()

        return UploadChunkResponse(
            upload_id=session.id,
            received_size_bytes=session.received_size_bytes,
            expected_size_bytes=session.expected_size_bytes,
            chunk_index=chunk_index,
            is_complete=(session.received_size_bytes == session.expected_size_bytes),
        )


@router.post("/uploads/{upload_id}/complete", response_model=UploadCompleteResponse)
async def complete_upload(
    upload_id: str,
    payload: UploadCompleteRequest = UploadCompleteRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Finalize upload, compute SHA-256 over entire assembled file, validate with FFprobe, and promote.

    Includes idempotent handling for concurrent/repeated calls (MF-01) and safe reconciliation
    if database commit fails after file promotion (HF-02).
    """
    lock = await get_upload_lock(upload_id)
    async with lock:
        # 1. Fetch session
        sess_result = await db.execute(select(UploadSession).where(UploadSession.id == upload_id))
        session = sess_result.scalar_one_or_none()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Upload session {upload_id} not found.",
            )

        session_id = str(upload_id)

        # Helper to ensure thumbnail recovery during idempotent retries (Finding CS-REV-2B2-001)
        async def _ensure_thumbnail_job_for_existing(existing_v: ImportedVideo):
            needs_recovery = False
            if existing_v.thumbnail_status in ("pending", "failed", "missing") or not existing_v.thumbnail_path:
                needs_recovery = True
            else:
                try:
                    p = Path(existing_v.thumbnail_path)
                    abs_thumb = p.resolve() if p.is_absolute() else safe_resolve_path(existing_v.thumbnail_path)
                    if not abs_thumb.exists() or abs_thumb.stat().st_size == 0:
                        needs_recovery = True
                except Exception:
                    needs_recovery = True

            if needs_recovery:
                try:
                    active_job_res = await db.execute(
                        select(ProcessingJob).where(
                            ProcessingJob.entity_type == "media",
                            ProcessingJob.entity_id == existing_v.id,
                            ProcessingJob.job_type == "thumbnail_generation",
                            ProcessingJob.status.in_(["queued", "running"]),
                        )
                    )
                    if not active_job_res.scalars().first():
                        m_id = str(existing_v.id)
                        w_id = str(existing_v.workspace_id)
                        f_path = str(existing_v.file_path)
                        dur = float(existing_v.duration_seconds or 0.0)

                        sp = Path(f_path)
                        abs_source = sp.resolve() if sp.is_absolute() else safe_resolve_path(f_path)
                        if abs_source.exists() and abs_source.is_file():
                            from app.services.job_queue import job_queue
                            # Release the read transaction on db to release SQLite lock before enqueuing
                            await db.rollback()
                            await job_queue.enqueue_thumbnail_job(
                                media_id=m_id,
                                workspace_id=w_id,
                                file_path=f_path,
                                duration_seconds=dur,
                            )
                            logger.info(f"Idempotent upload recovery: enqueued thumbnail job for media {m_id}")
                        else:
                            existing_v.thumbnail_status = "failed"
                            await db.commit()
                except Exception as rec_err:
                    logger.warning(f"Failed to recover thumbnail during upload complete retry: {rec_err}")

        # Idempotent return if already completed (MF-01)
        if session.status == "completed":
            vid_result = await db.execute(select(ImportedVideo).where(ImportedVideo.id == session_id))
            existing_video = vid_result.scalar_one_or_none()
            if existing_video:
                await _ensure_thumbnail_job_for_existing(existing_video)
                # Re-query fresh video model so response reflects latest status
                fresh_res = await db.execute(select(ImportedVideo).where(ImportedVideo.id == session_id))
                return_video = fresh_res.scalar_one_or_none() or existing_video
                return UploadCompleteResponse(
                    status="completed",
                    video=ImportedVideoRead.model_validate(return_video),
                    message="Upload already completed successfully.",
                )
            if session.sha256:
                vid_result = await db.execute(
                    select(ImportedVideo).where(
                        ImportedVideo.workspace_id == session.workspace_id,
                        ImportedVideo.sha256 == session.sha256,
                    )
                )
                existing_video = vid_result.scalar_one_or_none()
                if existing_video:
                    await _ensure_thumbnail_job_for_existing(existing_video)
                    fresh_res = await db.execute(select(ImportedVideo).where(ImportedVideo.id == existing_video.id))
                    return_video = fresh_res.scalar_one_or_none() or existing_video
                    return UploadCompleteResponse(
                        status="completed",
                        video=ImportedVideoRead.model_validate(return_video),
                        message="Upload already completed successfully.",
                    )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session is already marked completed, but associated media record was not found.",
            )

        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session is already {session.status}.",
            )

        if session.received_size_bytes != session.expected_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Incomplete upload: received {session.received_size_bytes} of "
                    f"{session.expected_size_bytes} bytes."
                ),
            )

        workspace_id = str(session.workspace_id)
        original_filename = str(session.original_filename)
        expected_size_bytes = int(session.expected_size_bytes)
        received_size_bytes = int(session.received_size_bytes)

        # Deterministic storage paths: media_id is bound 1-to-1 to session_id (HF-02)
        sanitized_name = sanitize_filename(original_filename)
        target_dir = settings.MEDIA_ORIGINALS_DIR / workspace_id / session_id
        target_path = target_dir / sanitized_name

        # Check if file was already promoted during a previous interrupted attempt
        if target_path.exists() and target_path.stat().st_size == expected_size_bytes:
            media_file_to_probe = target_path
            already_promoted = True
        else:
            abs_temp_path = safe_resolve_path(session.temporary_path)
            if not abs_temp_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Staged temporary file is missing.",
                )
            media_file_to_probe = abs_temp_path
            already_promoted = False

        # 2. Compute SHA-256 incrementally across the entire assembled file (SEC-A2-01)
        computed_sha256 = compute_sha256_stream(media_file_to_probe)

        # Integrity verification: If session already has a recorded SHA-256 (e.g. from prior attempt
        # or recovered file), verify that the promoted/assembled file's hash strictly matches.
        if session.sha256 and computed_sha256 != session.sha256:
            logger.error(
                f"Upload session {session_id}: File integrity mismatch during recovery. "
                f"Expected recorded SHA-256 '{session.sha256}', but file on disk computed '{computed_sha256}'."
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"File integrity mismatch during recovery: promoted file content does not match "
                    f"the recorded session SHA-256 checksum."
                ),
            )

        session.sha256 = computed_sha256

        # 3. Duplicate detection within workspace (excluding self if reconciling)
        dup_query = select(ImportedVideo).where(
            ImportedVideo.workspace_id == workspace_id,
            ImportedVideo.sha256 == computed_sha256,
            ImportedVideo.id != session_id,
        )
        dup_result = await db.execute(dup_query)
        existing_dup = dup_result.scalars().first()

        if existing_dup and not payload.confirm_duplicate:
            return UploadCompleteResponse(
                status="duplicate_detected",
                duplicate_video_id=existing_dup.id,
                message=(
                    f"A video with identical content already exists in this workspace ('{existing_dup.file_name}'). "
                    f"Confirm duplicate import to retain a separate reference."
                ),
            )

        # 4. Media validation via FFprobe subprocess
        try:
            probe_data = await probe_media_file(media_file_to_probe)
            specs = extract_media_specs(probe_data)
        except MediaValidationException as val_err:
            session.status = "failed"
            await db.commit()
            if not already_promoted:
                cleanup_directory(abs_temp_path.parent)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(val_err),
            )

        # 5. Atomic promotion to permanent storage (if not already promoted)
        if not already_promoted:
            try:
                atomic_promote_file(abs_temp_path, target_path)
            except StorageException as st_err:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Storage promotion failed: {st_err}",
                )
            finally:
                cleanup_directory(abs_temp_path.parent)

        # 6. Database persistence with atomic rollback & concurrent retry handling
        rel_storage_path = f"media/originals/{workspace_id}/{session_id}/{sanitized_name}"

        existing_video_res = await db.execute(select(ImportedVideo).where(ImportedVideo.id == session_id))
        video = existing_video_res.scalar_one_or_none()
        if not video:
            video = ImportedVideo(
                id=session_id,
                workspace_id=workspace_id,
                file_name=original_filename,
                file_path=rel_storage_path,
                file_size_bytes=received_size_bytes,
                duration_seconds=specs["duration_seconds"],
                width=specs["width"],
                height=specs["height"],
                fps=specs["fps"],
                video_codec=specs["video_codec"],
                audio_codec=specs["audio_codec"],
                status="ready",
                sha256=computed_sha256,
                container_format=specs["container_format"],
                metadata_json=specs["metadata_json"],
            )
            db.add(video)

        session.status = "completed"

        try:
            await db.commit()
            await db.refresh(video)
        except Exception as commit_err:
            await db.rollback()
            # Check if video was committed concurrently by a race request (MF-01)
            # Query by plain string session_id to avoid touching expired ORM instance attributes
            concurrent_check = await db.execute(select(ImportedVideo).where(ImportedVideo.id == session_id))
            concurrent_video = concurrent_check.scalar_one_or_none()
            if concurrent_video:
                return UploadCompleteResponse(
                    status="completed",
                    video=ImportedVideoRead.model_validate(concurrent_video),
                    message="Media imported successfully.",
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database commit failed during upload finalization: {commit_err}",
            )

        # 7. Broadcast WebSocket event
        try:
            await ws_manager.broadcast({
                "event_type": "media_imported",
                "media_id": video.id,
                "workspace_id": video.workspace_id,
                "file_name": video.file_name,
                "duration": video.duration_seconds,
                "resolution": f"{video.width}x{video.height}",
                "status": video.status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

        # 8. Auto-trigger thumbnail generation job (Phase 2B.2 & 2B.3)
        try:
            from app.services.job_queue import job_queue
            await job_queue.enqueue_thumbnail_job(
                media_id=video.id,
                workspace_id=video.workspace_id,
                file_path=video.file_path,
                duration_seconds=video.duration_seconds,
            )
        except Exception as thumb_err:
            logger.error(
                f"Failed to auto-enqueue thumbnail job for media {video.id} in workspace {video.workspace_id}: {thumb_err}",
                exc_info=True,
            )
            # Ensure thumbnail_status is recorded as failed in the DB to avoid indefinite invalid pending state (Issue A)
            try:
                video.thumbnail_status = "failed"
                await db.commit()
                await db.refresh(video)
            except Exception as update_err:
                logger.error(f"Failed to record thumbnail failure status for media {video.id}: {update_err}")

            try:
                await ws_manager.broadcast({
                    "event_type": "thumbnail_updated",
                    "media_id": video.id,
                    "workspace_id": video.workspace_id,
                    "status": "failed",
                    "error": str(thumb_err),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass

        return UploadCompleteResponse(
            status="completed",
            video=ImportedVideoRead.model_validate(video),
            message="Media imported successfully.",
        )


@router.get("", response_model=MediaListResponse)
async def list_media(
    workspace_id: str | None = Query(None, description="Filter media by workspace UUID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List imported media with pagination and optional workspace filtering."""
    query = select(ImportedVideo)
    count_query = select(func.count(ImportedVideo.id))

    if workspace_id:
        query = query.where(ImportedVideo.workspace_id == workspace_id)
        count_query = count_query.where(ImportedVideo.workspace_id == workspace_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(ImportedVideo.created_at.desc()).offset(skip).limit(limit)
    res = await db.execute(query)
    videos = res.scalars().all()

    # Query active thumbnail jobs to report accurate live status (CS-REV-2B2-001)
    media_ids = [v.id for v in videos]
    active_jobs: dict[str, str] = {}
    if media_ids:
        job_stmt = select(ProcessingJob.entity_id, ProcessingJob.status).where(
            ProcessingJob.entity_type == "media",
            ProcessingJob.entity_id.in_(media_ids),
            ProcessingJob.job_type == "thumbnail_generation",
            ProcessingJob.status.in_(["queued", "running"]),
        )
        job_res = await db.execute(job_stmt)
        active_jobs = {row[0]: row[1] for row in job_res.all()}

    items: list[ImportedVideoRead] = []
    for v in videos:
        item = ImportedVideoRead.model_validate(v)
        # Accurate status: Never report queued or processing unless an actual active job exists
        if v.thumbnail_status in ("pending", "processing"):
            if v.id in active_jobs:
                item.thumbnail_status = "processing" if active_jobs[v.id] == "running" else "queued"
            else:
                item.thumbnail_status = "pending"
        items.append(item)

    return MediaListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{media_id}", response_model=ImportedVideoRead)
async def get_media(
    media_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve detailed metadata for an imported media asset."""
    result = await db.execute(select(ImportedVideo).where(ImportedVideo.id == media_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media {media_id} not found.",
        )

    item = ImportedVideoRead.model_validate(video)
    if video.thumbnail_status in ("pending", "processing"):
        active_job_res = await db.execute(
            select(ProcessingJob.status).where(
                ProcessingJob.entity_type == "media",
                ProcessingJob.entity_id == media_id,
                ProcessingJob.job_type == "thumbnail_generation",
                ProcessingJob.status.in_(["queued", "running"]),
            )
        )
        active_status = active_job_res.scalars().first()
        if active_status:
            item.thumbnail_status = "processing" if active_status == "running" else "queued"
        else:
            item.thumbnail_status = "pending"
    return item


@router.delete("/{media_id}", status_code=status.HTTP_200_OK)
async def delete_media(
    media_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Safely delete an imported media asset and its source file if not in active use."""
    result = await db.execute(select(ImportedVideo).where(ImportedVideo.id == media_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media {media_id} not found.",
        )

    # 1. Enforce active job safety check
    active_jobs = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.entity_id == media_id,
            ProcessingJob.status.in_(["queued", "running"]),
        )
    )
    if active_jobs.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete media while an active processing job is using it.",
        )

    # 2. Check if other ImportedVideo rows point to this exact file_path (reference reuse)
    other_refs = await db.execute(
        select(ImportedVideo).where(
            ImportedVideo.file_path == video.file_path,
            ImportedVideo.id != media_id,
        )
    )
    is_shared = other_refs.scalar_one_or_none() is not None

    # 3. Safely delete physical file if not shared
    if not is_shared:
        try:
            p = Path(video.file_path)
            if p.is_absolute():
                abs_path = p.resolve()
            else:
                abs_path = safe_resolve_path(video.file_path)

            if abs_path.exists() and abs_path.is_file():
                abs_path.unlink(missing_ok=True)
                # Remove media_id directory if empty
                if abs_path.parent.exists() and not any(abs_path.parent.iterdir()):
                    abs_path.parent.rmdir()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete media file from storage: {exc}",
            )

    # 4. Safely delete thumbnail file/dir if present
    if video.thumbnail_path:
        try:
            thumb_abs = safe_resolve_path(video.thumbnail_path)
            if thumb_abs.exists() and thumb_abs.is_file():
                thumb_abs.unlink(missing_ok=True)
                if thumb_abs.parent.exists() and not any(thumb_abs.parent.iterdir()):
                    thumb_abs.parent.rmdir()
        except Exception:
            pass

    # 5. Remove database record
    await db.delete(video)
    await db.commit()

    return {"status": "deleted", "media_id": media_id}


@router.get("/{media_id}/thumbnail", response_class=FileResponse)
async def get_media_thumbnail(
    media_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve the generated JPEG thumbnail for an imported video asset."""
    result = await db.execute(select(ImportedVideo).where(ImportedVideo.id == media_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media asset '{media_id}' not found.",
        )

    if not video.thumbnail_path or video.thumbnail_status != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thumbnail not available for media '{media_id}' (status: {video.thumbnail_status}).",
        )

    abs_thumb_path = safe_resolve_path(video.thumbnail_path)
    if not abs_thumb_path.exists() or not abs_thumb_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thumbnail file is missing from storage for media '{media_id}'.",
        )

    return FileResponse(
        path=abs_thumb_path,
        media_type="image/jpeg",
        filename=f"{media_id}_thumbnail.jpg",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Thumbnail-Status": video.thumbnail_status,
        },
    )


@router.get("/{media_id}/thumbnail/metadata", response_model=ThumbnailMetadataResponse)
async def get_media_thumbnail_metadata(
    media_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve detailed metadata and status for a media thumbnail.

    Returns actual image dimensions (width, height) extracted from the generated JPEG header.
    """
    result = await db.execute(select(ImportedVideo).where(ImportedVideo.id == media_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media asset '{media_id}' not found.",
        )

    from app.services.thumbnail import get_jpeg_dimensions

    file_size = None
    actual_width = None
    actual_height = None

    if video.thumbnail_path:
        try:
            p = Path(video.thumbnail_path)
            abs_p = p.resolve() if p.is_absolute() else safe_resolve_path(video.thumbnail_path)
            if abs_p.exists() and abs_p.is_file():
                file_size = abs_p.stat().st_size
                actual_width, actual_height = get_jpeg_dimensions(abs_p)
        except Exception:
            pass

    # Accurate status checking (CS-REV-2B2-001)
    active_job_res = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.entity_type == "media",
            ProcessingJob.entity_id == media_id,
            ProcessingJob.job_type == "thumbnail_generation",
            ProcessingJob.status.in_(["queued", "running"]),
        )
    )
    active_job = active_job_res.scalars().first()

    effective_status = video.thumbnail_status
    if video.thumbnail_status in ("pending", "processing"):
        if active_job:
            effective_status = "processing" if active_job.status == "running" else "queued"
        else:
            effective_status = "pending"

    thumb_url = f"/api/v1/media/{media_id}/thumbnail" if video.thumbnail_status == "completed" and video.thumbnail_path else None

    return ThumbnailMetadataResponse(
        media_id=video.id,
        status=effective_status,
        thumbnail_path=video.thumbnail_path,
        thumbnail_url=thumb_url,
        width=actual_width,
        height=actual_height,
        file_size_bytes=file_size,
        generated_at=video.thumbnail_generated_at,
    )


@router.post("/thumbnails/reconcile", status_code=status.HTTP_200_OK)
async def reconcile_thumbnails(
    workspace_id: str | None = Query(None, description="Optional workspace UUID to restrict reconciliation"),
    db: AsyncSession = Depends(get_db),
):
    """Trigger workspace-wide or global reconciliation of missing, pending, or interrupted thumbnails."""
    from app.services.job_queue import job_queue
    recovered_ids = await job_queue.reconcile_pending_thumbnails(workspace_id=workspace_id)
    return {
        "status": "completed",
        "recovered_count": len(recovered_ids),
        "recovered_media_ids": recovered_ids,
        "message": f"Successfully scheduled thumbnail generation for {len(recovered_ids)} media asset(s).",
    }


@router.post("/{media_id}/thumbnail/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_media_thumbnail(
    media_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Trigger or retry thumbnail generation for an imported video asset."""
    result = await db.execute(select(ImportedVideo).where(ImportedVideo.id == media_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media asset '{media_id}' not found.",
        )

    # Verify source file exists
    p = Path(video.file_path)
    if p.is_absolute():
        source_file = p.resolve()
    else:
        source_file = safe_resolve_path(video.file_path)

    if not source_file.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Source video file does not exist on disk: {video.file_path}",
        )

    # Check for active thumbnail job
    active_job_res = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.entity_type == "media",
            ProcessingJob.entity_id == media_id,
            ProcessingJob.job_type == "thumbnail_generation",
            ProcessingJob.status.in_(["queued", "running"]),
        )
    )
    existing_job = active_job_res.scalar_one_or_none()
    if existing_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Thumbnail generation is already in progress for media '{media_id}' (job {existing_job.id}).",
        )

    v_id = str(video.id)
    v_ws = str(video.workspace_id)
    v_path = str(video.file_path)
    v_dur = float(video.duration_seconds or 0.0)

    # Release read transaction before enqueuing to prevent lock contention
    await db.rollback()

    # Enqueue job
    from app.services.job_queue import job_queue
    job = await job_queue.enqueue_thumbnail_job(
        media_id=v_id,
        workspace_id=v_ws,
        file_path=v_path,
        duration_seconds=v_dur,
    )

    return {
        "status": "queued",
        "job_id": job.id,
        "media_id": v_id,
        "message": f"Thumbnail generation job queued for media '{media_id}'.",
    }

