import os
import struct
from pathlib import Path
from app.config import settings
from app.core.exceptions import ClipStudioException
from app.core.logging import logger
from app.services.ffmpeg import FFmpegRunner, resolve_ffmpeg_executable
from app.services.storage import atomic_promote_file, safe_resolve_path


class ThumbnailException(ClipStudioException):
    """Thumbnail generation or validation exception."""
    pass


def get_jpeg_dimensions(file_path: Path | str) -> tuple[int | None, int | None]:
    """Safely extract actual (width, height) dimensions from a JPEG image header without external dependencies.

    Parses SOF markers (SOF0-SOF3, SOF5-SOF7, SOF9-SOF11) in pure Python.
    Returns (None, None) if file is missing, corrupt, truncated, or not a JPEG.
    """
    p = Path(file_path)
    if not p.exists() or not p.is_file() or p.stat().st_size < 4:
        return (None, None)

    try:
        with open(p, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return (None, None)

            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return (None, None)

                # Skip any fill bytes
                while marker[1] == 0xFF:
                    next_byte = f.read(1)
                    if not next_byte:
                        return (None, None)
                    marker = b"\xff" + next_byte

                m = marker[1]
                # EOI (End of Image) or SOS (Start of Scan) - stop before entropy data
                if m in (0xD9, 0xDA):
                    return (None, None)

                # SOF markers containing width & height
                # 0xC0=SOF0 (baseline), 0xC1=SOF1 (extended), 0xC2=SOF2 (progressive),
                # 0xC3=SOF3, 0xC5=SOF5, 0xC6=SOF6, 0xC7=SOF7, 0xC9=SOF9, 0xCA=SOF10, 0xCB=SOF11
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                    length_bytes = f.read(2)
                    if len(length_bytes) < 2:
                        return (None, None)
                    _precision = f.read(1)
                    height_bytes = f.read(2)
                    width_bytes = f.read(2)
                    if len(height_bytes) < 2 or len(width_bytes) < 2:
                        return (None, None)
                    height = struct.unpack(">H", height_bytes)[0]
                    width = struct.unpack(">H", width_bytes)[0]
                    return (width, height)
                else:
                    # Skip variable-length segment
                    length_bytes = f.read(2)
                    if len(length_bytes) < 2:
                        return (None, None)
                    seg_len = struct.unpack(">H", length_bytes)[0]
                    if seg_len < 2:
                        return (None, None)
                    f.seek(seg_len - 2, os.SEEK_CUR)
    except Exception as exc:
        logger.debug(f"Failed to read JPEG dimensions from {p}: {exc}")
        return (None, None)


def calculate_thumbnail_timestamp(duration_seconds: float) -> float:
    """Calculate an optimal, representative seek timestamp for frame extraction.

    - For zero or negative duration: fallback to 0.0s.
    - For short videos (<= 1.0s): sample at mid-point (duration / 2.0).
    - For regular videos: sample at 10% of duration (or configurable percent),
      with a minimum offset (0.5s) to bypass common black opening fade-ins,
      capped at 15.0s to avoid deep seeks on multi-hour media.
    """
    if duration_seconds <= 0.0:
        return 0.0

    if duration_seconds <= 1.0:
        return round(duration_seconds / 2.0, 3)

    target_ts = duration_seconds * settings.THUMBNAIL_DEFAULT_TIMESTAMP_PERCENT
    # Ensure seek is at least THUMBNAIL_MIN_TIMESTAMP_SECONDS, but strictly less than total duration
    ts = max(settings.THUMBNAIL_MIN_TIMESTAMP_SECONDS, target_ts)
    if ts >= duration_seconds:
        ts = duration_seconds * 0.5

    # Cap seek at 15.0s to ensure fast keyframe seek even on very long media
    return round(min(ts, 15.0), 3)


def get_thumbnail_storage_paths(workspace_id: str, media_id: str) -> tuple[Path, str]:
    """Derive the absolute destination path and relative database path for a media thumbnail.

    Layout: data/media/thumbnails/{workspace_id}/{media_id}/thumbnail.jpg
    Relative DB path: media/thumbnails/{workspace_id}/{media_id}/thumbnail.jpg
    """
    rel_path = f"media/thumbnails/{workspace_id}/{media_id}/thumbnail.jpg"
    abs_path = settings.MEDIA_THUMBNAILS_DIR / workspace_id / media_id / "thumbnail.jpg"
    return abs_path, rel_path


async def generate_thumbnail(
    input_video_path: Path | str,
    workspace_id: str,
    media_id: str,
    duration_seconds: float = 0.0,
    width: int | None = None,
    quality: int | None = None,
    timeout_seconds: float | None = None,
) -> tuple[Path, str]:
    """Extract a representative thumbnail frame from a video using FFmpeg and promote atomically.

    Returns:
        tuple[Path, str]: (absolute_thumbnail_path, relative_database_path)
    """
    # 1. Resolve and validate input file path
    if isinstance(input_video_path, Path):
        abs_input = input_video_path.resolve()
    else:
        p = Path(input_video_path)
        if p.is_absolute():
            abs_input = p.resolve()
        else:
            abs_input = safe_resolve_path(input_video_path)

    if not abs_input.exists():
        raise ThumbnailException(f"Source video file not found: {abs_input}")

    if not abs_input.is_file():
        raise ThumbnailException(f"Source video path is not a file: {abs_input}")

    # 2. Determine target paths & temp staging path
    abs_target, rel_target = get_thumbnail_storage_paths(workspace_id, media_id)
    thumb_width = width or settings.THUMBNAIL_WIDTH
    thumb_quality = quality or settings.THUMBNAIL_QUALITY
    timeout = timeout_seconds or settings.THUMBNAIL_SUBPROCESS_TIMEOUT_SECONDS

    seek_time = calculate_thumbnail_timestamp(duration_seconds)

    # Isolated temp staging directory
    temp_dir = settings.THUMBNAILS_TEMP_DIR / workspace_id / media_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_output = temp_dir / f"temp_{media_id}_{os.getpid()}_{seek_time}.jpg"

    # 3. Assemble FFmpeg argument array
    # Fast input seek (-ss before -i) avoids decoding preceding frames
    # scale={width}:-2 preserves aspect ratio and ensures even vertical dimension
    ffmpeg_exe = resolve_ffmpeg_executable()
    cmd_args = [
        "-ss", f"{seek_time:.3f}",
        "-i", str(abs_input),
        "-vf", f"scale={thumb_width}:-2",
        "-vframes", "1",
        "-q:v", str(thumb_quality),
        "-f", "image2",
        "-y",
        str(temp_output),
    ]

    logger.info(
        f"Extracting thumbnail for media {media_id} (seek: {seek_time:.3f}s, width: {thumb_width}): "
        f"{ffmpeg_exe} {' '.join(cmd_args)}"
    )

    runner = FFmpegRunner(ffmpeg_path=ffmpeg_exe)
    try:
        result = await runner.run(
            args=cmd_args,
            timeout_seconds=timeout,
        )

        if not result.success:
            raise ThumbnailException(
                f"FFmpeg thumbnail extraction failed (exit {result.returncode}): {result.stderr or result.error_message}"
            )

        if not temp_output.exists() or temp_output.stat().st_size == 0:
            raise ThumbnailException("FFmpeg completed but failed to produce a valid thumbnail image.")

        # 4. Atomically promote staged temporary thumbnail to permanent storage
        abs_target.parent.mkdir(parents=True, exist_ok=True)
        promoted = atomic_promote_file(temp_output, abs_target)
        logger.info(f"Thumbnail successfully promoted to {promoted} ({promoted.stat().st_size} bytes)")
        return promoted, rel_target

    except Exception as exc:
        # Clean up temporary output on failure
        if temp_output.exists():
            try:
                temp_output.unlink(missing_ok=True)
            except Exception:
                pass
        if isinstance(exc, ThumbnailException):
            raise
        raise ThumbnailException(f"Failed to generate thumbnail: {exc}") from exc
    finally:
        # Clean up temp directory if empty
        if temp_dir.exists() and not any(temp_dir.iterdir()):
            try:
                temp_dir.rmdir()
            except Exception:
                pass
