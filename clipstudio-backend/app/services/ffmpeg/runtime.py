import asyncio
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from app.config import settings
from app.core.exceptions import ClipStudioException
from app.core.logging import logger


class FFmpegExecutableException(ClipStudioException):
    """Raised when FFmpeg or FFprobe binaries are missing or inaccessible."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=500)


@dataclass
class FFmpegRuntimeInfo:
    """Structured information about detected FFmpeg runtime environment."""

    available: bool = False
    ffmpeg_path: Optional[str] = None
    ffprobe_path: Optional[str] = None
    version: Optional[str] = None
    build_info: Optional[str] = None
    hwaccels: list[str] = field(default_factory=list)
    encoders: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "ffmpeg_path": self.ffmpeg_path,
            "ffprobe_path": self.ffprobe_path,
            "version": self.version,
            "build_info": self.build_info,
            "hwaccels": self.hwaccels,
            "encoders": self.encoders,
            "error": self.error,
        }


def _get_candidate_binary_paths(binary_name: str) -> list[Path]:
    """Generates prioritized list of Windows binary candidate paths."""
    exe_name = f"{binary_name}.exe" if not binary_name.endswith(".exe") else binary_name
    candidates: list[Path] = []

    # 1. Winget packages under %LOCALAPPDATA%
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            for gyan_dir in winget_pkgs.glob("Gyan.FFmpeg*"):
                for bin_dir in gyan_dir.glob("**/bin"):
                    candidates.append(bin_dir / exe_name)

    # 2. Standard Program Files and root locations
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates.extend([
        Path(program_files) / "ffmpeg" / "bin" / exe_name,
        Path(r"C:\ffmpeg\bin") / exe_name,
        Path(r"C:\ProgramData\chocolatey\bin") / exe_name,
    ])

    return candidates


def resolve_ffmpeg_executable() -> str:
    """Dynamically resolve ffmpeg executable path on the host system."""
    # 1. Config override
    if settings.FFMPEG_PATH:
        configured = Path(settings.FFMPEG_PATH)
        if configured.exists() and configured.is_file():
            return str(configured)
        logger.warning(f"Configured FFMPEG_PATH does not exist: {settings.FFMPEG_PATH}")

    # 2. System PATH
    in_path = shutil.which("ffmpeg")
    if in_path:
        return in_path

    # 3. Known Windows candidate paths
    for cand in _get_candidate_binary_paths("ffmpeg"):
        if cand.exists() and cand.is_file():
            return str(cand)

    raise FFmpegExecutableException(
        "FFmpeg executable could not be resolved. Ensure FFmpeg is installed and available in PATH, "
        "or specify FFMPEG_PATH in configuration."
    )


def resolve_ffprobe_executable() -> str:
    """Dynamically resolve ffprobe executable path on the host system."""
    # 1. Config override
    if settings.FFPROBE_PATH:
        configured = Path(settings.FFPROBE_PATH)
        if configured.exists() and configured.is_file():
            return str(configured)
        logger.warning(f"Configured FFPROBE_PATH does not exist: {settings.FFPROBE_PATH}")

    # 2. System PATH
    in_path = shutil.which("ffprobe")
    if in_path:
        return in_path

    # 3. Known Windows candidate paths
    for cand in _get_candidate_binary_paths("ffprobe"):
        if cand.exists() and cand.is_file():
            return str(cand)

    raise FFmpegExecutableException(
        "FFprobe executable could not be resolved. Ensure FFprobe is installed and available in PATH, "
        "or specify FFPROBE_PATH in configuration."
    )


def parse_ffmpeg_version(output_str: str) -> tuple[Optional[str], Optional[str]]:
    """Extracts version identifier and build details from `ffmpeg -version` output."""
    if not output_str:
        return None, None

    version: Optional[str] = None
    build_info: Optional[str] = None

    # First line usually: "ffmpeg version <version_id> Copyright..."
    ver_match = re.search(r"ffmpeg version\s+([^\s]+)", output_str, re.IGNORECASE)
    if ver_match:
        version = ver_match.group(1).strip()

    # Second line often: "built with <compiler info>"
    built_match = re.search(r"built with\s+(.+)", output_str, re.IGNORECASE)
    if built_match:
        build_info = built_match.group(1).split("\n")[0].strip()

    return version, build_info


def parse_hwaccels(output_str: str) -> list[str]:
    """Parses hardware acceleration methods from `ffmpeg -hwaccels` output."""
    if not output_str:
        return []

    hwaccels: list[str] = []
    lines = output_str.strip().splitlines()
    collecting = False

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        if "Hardware acceleration methods:" in line:
            collecting = True
            continue
        if collecting:
            # Skip banner lines if any
            if not line_clean.startswith("ffmpeg version") and not line_clean.startswith("built with"):
                hwaccels.append(line_clean)

    return hwaccels


def parse_encoders(output_str: str) -> list[str]:
    """Parses supported video/audio encoder names from `ffmpeg -encoders` output."""
    if not output_str:
        return []

    encoders: list[str] = []
    lines = output_str.strip().splitlines()
    in_encoders_section = False

    # Format in FFmpeg:
    #  V..... = Video, A..... = Audio
    #  ------
    #  V..... libx264              libx264 H.264 / AVC...
    encoder_line_pattern = re.compile(r"^\s*([VAS][FSXBD.]{5})\s+([a-zA-Z0-9_\-]+)")

    for line in lines:
        if line.strip().startswith("------"):
            in_encoders_section = True
            continue
        if not in_encoders_section:
            continue

        match = encoder_line_pattern.match(line)
        if match:
            encoder_name = match.group(2)
            encoders.append(encoder_name)

    return encoders


# Singleton runtime cache
_cached_runtime_info: Optional[FFmpegRuntimeInfo] = None
_detection_lock = asyncio.Lock()


async def detect_ffmpeg_runtime(force_refresh: bool = False) -> FFmpegRuntimeInfo:
    """Performs non-blocking inspection of host FFmpeg capabilities."""
    global _cached_runtime_info

    if _cached_runtime_info is not None and not force_refresh:
        return _cached_runtime_info

    async with _detection_lock:
        if _cached_runtime_info is not None and not force_refresh:
            return _cached_runtime_info

        try:
            ffmpeg_path = resolve_ffmpeg_executable()
        except FFmpegExecutableException as exc:
            _cached_runtime_info = FFmpegRuntimeInfo(
                available=False,
                error=str(exc.message),
            )
            return _cached_runtime_info

        ffprobe_path: Optional[str] = None
        try:
            ffprobe_path = resolve_ffprobe_executable()
        except Exception:
            logger.warning("FFprobe binary could not be resolved during runtime detection.")

        info = FFmpegRuntimeInfo(
            available=True,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )

        # 1. Query version
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_path,
                "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            ver_text = stdout.decode("utf-8", errors="replace")
            info.version, info.build_info = parse_ffmpeg_version(ver_text)
        except Exception as exc:
            logger.warning(f"Could not parse FFmpeg version: {exc}")

        # 2. Query hardware acceleration
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_path,
                "-hwaccels",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            hw_text = stdout.decode("utf-8", errors="replace")
            info.hwaccels = parse_hwaccels(hw_text)
        except Exception as exc:
            logger.warning(f"Could not parse FFmpeg hwaccels: {exc}")

        # 3. Query encoders
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_path,
                "-encoders",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            enc_text = stdout.decode("utf-8", errors="replace")
            info.encoders = parse_encoders(enc_text)
        except Exception as exc:
            logger.warning(f"Could not parse FFmpeg encoders: {exc}")

        _cached_runtime_info = info
        return info
