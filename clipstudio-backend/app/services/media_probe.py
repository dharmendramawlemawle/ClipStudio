import asyncio
import json
import shutil
from pathlib import Path
from typing import Any
from app.core.exceptions import ClipStudioException
from app.core.logging import logger


class MediaValidationException(ClipStudioException):
    """Media validation or FFprobe inspection exception."""
    pass


def resolve_ffprobe_executable() -> str:
    """Dynamically resolve ffprobe executable path on Windows."""
    ffprobe_cmd = shutil.which("ffprobe")
    if ffprobe_cmd:
        return ffprobe_cmd

    # Known candidate paths on Windows (Winget / Gyan install locations)
    candidates = [
        Path(r"C:\Users\dharm\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffprobe.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
        Path(r"C:\ffmpeg\bin\ffprobe.exe"),
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand)

    raise MediaValidationException(
        "FFprobe executable could not be resolved. Ensure FFprobe is installed and available in PATH."
    )


def parse_fractional_fps(fps_str: str) -> float:
    """Safely parse FFprobe fractional frame rate like '30/1' or '60000/1001'."""
    if not fps_str or fps_str == "0/0":
        return 0.0
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/", 1)
            den_val = float(den)
            return round(float(num) / den_val, 3) if den_val != 0 else 0.0
        return round(float(fps_str), 3)
    except Exception:
        return 0.0


async def probe_media_file(
    file_path: Path,
    timeout_seconds: float = 30.0,
    max_output_bytes: int = 1048576,  # 1 MB bounded buffer
) -> dict[str, Any]:
    """Execute FFprobe safely on a media file and return JSON stream metadata."""
    if not file_path.exists():
        raise MediaValidationException(f"Media file not found for probing: {file_path}")

    ffprobe_exe = resolve_ffprobe_executable()
    args = [
        ffprobe_exe,
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-print_format", "json",
        str(file_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise MediaValidationException(f"FFprobe inspection timed out after {timeout_seconds}s.")

        if proc.returncode != 0:
            err_msg = stderr_data.decode("utf-8", errors="replace").strip()
            raise MediaValidationException(f"FFprobe validation failed (code {proc.returncode}): {err_msg}")

        # Bounded read
        if len(stdout_data) > max_output_bytes:
            stdout_data = stdout_data[:max_output_bytes]

        parsed = json.loads(stdout_data.decode("utf-8", errors="replace"))
        return parsed

    except json.JSONDecodeError as exc:
        raise MediaValidationException(f"Failed to parse FFprobe JSON output: {exc}")
    except Exception as exc:
        if isinstance(exc, MediaValidationException):
            raise
        logger.error(f"Unexpected error probing media {file_path}: {exc}")
        raise MediaValidationException(f"Media validation error: {str(exc)}")


def extract_media_specs(probe_data: dict[str, Any]) -> dict[str, Any]:
    """Extract and validate normalized video and audio specifications from FFprobe output."""
    streams = probe_data.get("streams", [])
    format_info = probe_data.get("format", {})

    # 1. Identify primary video stream
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise MediaValidationException(
            "Validation rejected: File contains no supported video stream."
        )

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise MediaValidationException(
            f"Validation rejected: Invalid video dimensions ({width}x{height})."
        )

    # Calculate FPS
    fps = parse_fractional_fps(video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate", ""))

    # 2. Extract Duration
    duration_sec = 0.0
    if "duration" in format_info:
        try:
            duration_sec = float(format_info["duration"])
        except ValueError:
            duration_sec = 0.0
    if duration_sec <= 0.0 and "duration" in video_stream:
        try:
            duration_sec = float(video_stream["duration"])
        except ValueError:
            duration_sec = 0.0

    # 3. Identify audio stream (optional)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    audio_codec = audio_stream.get("codec_name", "") if audio_stream else ""

    container_format = format_info.get("format_name", "")

    # Clean subset of metadata for database storage
    minimal_metadata = {
        "format": {
            "format_name": container_format,
            "duration": duration_sec,
            "size": format_info.get("size"),
            "bit_rate": format_info.get("bit_rate"),
        },
        "video": {
            "codec": video_stream.get("codec_name", ""),
            "profile": video_stream.get("profile", ""),
            "width": width,
            "height": height,
            "fps": fps,
            "pix_fmt": video_stream.get("pix_fmt", ""),
        },
        "audio": {
            "codec": audio_codec,
            "sample_rate": audio_stream.get("sample_rate") if audio_stream else None,
            "channels": audio_stream.get("channels") if audio_stream else None,
        } if audio_stream else None,
    }

    return {
        "width": width,
        "height": height,
        "duration_seconds": round(duration_sec, 2),
        "fps": fps,
        "video_codec": video_stream.get("codec_name", ""),
        "audio_codec": audio_codec,
        "container_format": container_format,
        "metadata_json": json.dumps(minimal_metadata),
    }
