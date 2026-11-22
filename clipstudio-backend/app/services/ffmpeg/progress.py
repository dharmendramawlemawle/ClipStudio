import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FFmpegProgress:
    """Structured progress metrics emitted by FFmpeg."""

    frame: int = 0
    fps: float = 0.0
    bitrate: str = "N/A"
    total_size: int = 0
    out_time_seconds: float = 0.0
    out_time_str: str = "00:00:00.000000"
    speed: Optional[float] = None
    speed_str: str = "N/A"
    progress_status: str = "continue"  # "continue" | "end"
    percent: Optional[float] = None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_finished(self) -> bool:
        return self.progress_status == "end"


def parse_time_to_seconds(time_str: str) -> float:
    """Parses FFmpeg time format (HH:MM:SS.fraction) into total seconds."""
    if not time_str or time_str.strip() == "N/A":
        return 0.0
    try:
        parts = time_str.strip().split(":")
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return max(0.0, h * 3600.0 + m * 60.0 + s)
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return max(0.0, m * 60.0 + s)
        return max(0.0, float(time_str))
    except Exception:
        return 0.0


def parse_speed_multiplier(speed_str: str) -> Optional[float]:
    """Parses FFmpeg speed string (e.g. ' 1.35x' or '136x') into float."""
    if not speed_str or speed_str.strip() == "N/A":
        return None
    cleaned = speed_str.strip().rstrip("xX").strip()
    try:
        val = float(cleaned)
        return val if val >= 0 else None
    except Exception:
        return None


class FFmpegProgressParser:
    """Stateful stream parser for FFmpeg machine-readable '-progress pipe:1' output."""

    def __init__(self, total_duration_seconds: Optional[float] = None):
        self.total_duration_seconds = (
            total_duration_seconds if total_duration_seconds and total_duration_seconds > 0 else None
        )
        self._buffer: str = ""
        self._current_block: dict[str, str] = {}

    def feed(self, chunk: bytes | str) -> list[FFmpegProgress]:
        """Feeds a stream chunk into the parser and returns any complete progress objects."""
        if isinstance(chunk, bytes):
            text = chunk.decode("utf-8", errors="replace")
        else:
            text = chunk

        self._buffer += text
        results: list[FFmpegProgress] = []

        # Process lines
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue

            if "=" in line:
                key, val = line.split("=", 1)
                k = key.strip()
                v = val.strip()
                self._current_block[k] = v

                if k == "progress":
                    # End of a progress block
                    progress_item = self._build_progress(self._current_block)
                    results.append(progress_item)
                    self._current_block = {}

        return results

    def flush(self) -> list[FFmpegProgress]:
        """Flushes any remaining buffered lines when stream ends."""
        results: list[FFmpegProgress] = []
        if self._buffer.strip():
            remaining_lines = self._buffer.strip().splitlines()
            self._buffer = ""
            for line in remaining_lines:
                line = line.strip()
                if "=" in line:
                    key, val = line.split("=", 1)
                    k = key.strip()
                    v = val.strip()
                    self._current_block[k] = v
                    if k == "progress":
                        results.append(self._build_progress(self._current_block))
                        self._current_block = {}

        if self._current_block:
            # Emit last block even if missing final progress= line
            results.append(self._build_progress(self._current_block))
            self._current_block = {}

        return results

    def _build_progress(self, raw: dict[str, str]) -> FFmpegProgress:
        """Converts raw key-value mapping to an FFmpegProgress dataclass."""
        # 1. Frame
        frame = 0
        try:
            frame = int(raw.get("frame", "0"))
        except (ValueError, TypeError):
            frame = 0

        # 2. FPS
        fps = 0.0
        try:
            fps = float(raw.get("fps", "0.0"))
        except (ValueError, TypeError):
            fps = 0.0

        # 3. Bitrate
        bitrate = raw.get("bitrate", "N/A")

        # 4. Total Size
        total_size = 0
        try:
            total_size = int(raw.get("total_size", "0"))
        except (ValueError, TypeError):
            total_size = 0

        # 5. Out Time
        out_time_str = raw.get("out_time", "00:00:00.000000")
        out_time_seconds = 0.0

        if "out_time_us" in raw and raw["out_time_us"] != "N/A":
            try:
                out_time_seconds = max(0.0, float(raw["out_time_us"]) / 1_000_000.0)
            except (ValueError, TypeError):
                out_time_seconds = parse_time_to_seconds(out_time_str)
        elif "out_time_ms" in raw and raw["out_time_ms"] != "N/A":
            try:
                # In ffmpeg, out_time_ms is microsecond scale
                out_time_seconds = max(0.0, float(raw["out_time_ms"]) / 1_000_000.0)
            except (ValueError, TypeError):
                out_time_seconds = parse_time_to_seconds(out_time_str)
        else:
            out_time_seconds = parse_time_to_seconds(out_time_str)

        # 6. Speed
        speed_raw = raw.get("speed", "N/A")
        speed_multiplier = parse_speed_multiplier(speed_raw)

        # 7. Progress status
        progress_status = raw.get("progress", "continue").strip().lower()
        if progress_status not in ["continue", "end"]:
            progress_status = "continue"

        # 8. Percentage calculation
        percent: Optional[float] = None
        if self.total_duration_seconds and self.total_duration_seconds > 0:
            if progress_status == "end":
                percent = 100.0
            else:
                pct = (out_time_seconds / self.total_duration_seconds) * 100.0
                percent = round(min(100.0, max(0.0, pct)), 2)

        return FFmpegProgress(
            frame=frame,
            fps=fps,
            bitrate=bitrate,
            total_size=total_size,
            out_time_seconds=round(out_time_seconds, 3),
            out_time_str=out_time_str,
            speed=speed_multiplier,
            speed_str=speed_raw,
            progress_status=progress_status,
            percent=percent,
            raw=dict(raw),
        )
