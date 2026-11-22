import asyncio
import collections
import inspect
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from app.config import settings
from app.core.exceptions import ClipStudioException
from app.core.logging import logger
from app.services.ffmpeg.progress import FFmpegProgress, FFmpegProgressParser
from app.services.ffmpeg.runtime import resolve_ffmpeg_executable


class FFmpegException(ClipStudioException):
    """Base exception for FFmpeg processing errors."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message=message, status_code=status_code)


class FFmpegTimeoutException(FFmpegException):
    """Raised when an FFmpeg process exceeds its allowed execution timeout."""
    pass


class FFmpegExecutionException(FFmpegException):
    """Raised when an FFmpeg process exits with a non-zero exit code."""

    def __init__(self, message: str, returncode: int, stderr_tail: str):
        super().__init__(message=message, status_code=500)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


@dataclass
class FFmpegExecutionResult:
    """Detailed result of an FFmpeg execution run."""

    returncode: int
    success: bool
    command: list[str]
    duration_seconds: float
    stderr: str
    pid: Optional[int] = None
    last_progress: Optional[FFmpegProgress] = None
    error_message: Optional[str] = None


async def terminate_process_tree(proc: asyncio.subprocess.Process, timeout: float = 3.0) -> None:
    """Safely terminates a process and any child processes it spawned."""
    if proc.returncode is not None:
        return

    pid = proc.pid
    logger.warning(f"Terminating FFmpeg process PID={pid}...")

    # 1. Attempt standard terminate/kill
    try:
        proc.kill()
    except ProcessLookupError:
        return
    except Exception as exc:
        logger.debug(f"proc.kill() error for PID={pid}: {exc}")

    # 2. On Windows, execute taskkill /F /T /PID to tear down entire child process tree
    if sys.platform == "win32" and pid:
        try:
            tk = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(tk.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                tk.kill()
        except Exception as exc:
            logger.debug(f"taskkill execution failed for PID={pid}: {exc}")

    # 3. Final wait to ensure zombie cleanup
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        logger.warning(f"Timed out waiting for process PID={pid} to exit.")


class FFmpegRunner:
    """Subprocess runner for FFmpeg with bounded stderr, progress streaming, and lifecycle management."""

    def __init__(
        self,
        ffmpeg_path: Optional[str] = None,
        max_stderr_bytes: Optional[int] = None,
    ):
        self._custom_ffmpeg_path = ffmpeg_path
        self._max_stderr_bytes = (
            max_stderr_bytes if max_stderr_bytes is not None else settings.FFMPEG_STDERR_MAX_BYTES
        )
        self._active_proc: Optional[asyncio.subprocess.Process] = None

    @property
    def active_pid(self) -> Optional[int]:
        return self._active_proc.pid if self._active_proc else None

    async def run(
        self,
        args: list[str],
        total_duration_seconds: Optional[float] = None,
        progress_callback: Optional[Callable[[FFmpegProgress], Any]] = None,
        timeout_seconds: Optional[float] = None,
        cwd: Optional[Path | str] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> FFmpegExecutionResult:
        """Executes an FFmpeg command with progress streaming and bounded stderr capture."""
        start_time = time.monotonic()
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.FFMPEG_SUBPROCESS_TIMEOUT_SECONDS
        )

        # 1. Resolve executable and normalize command
        ffmpeg_bin = self._custom_ffmpeg_path or resolve_ffmpeg_executable()
        cmd_args: list[str] = []

        if not args:
            raise FFmpegException("No arguments supplied to FFmpegRunner.")

        # Ensure binary is at index 0
        first_arg = args[0]
        if (
            first_arg == ffmpeg_bin
            or first_arg == "ffmpeg"
            or first_arg.endswith("ffmpeg.exe")
        ):
            cmd_args = [ffmpeg_bin] + list(args[1:])
        else:
            cmd_args = [ffmpeg_bin] + list(args)

        # Inject machine-readable progress flags if not explicitly present
        if "-progress" not in cmd_args:
            cmd_args = [cmd_args[0], "-progress", "pipe:1", "-nostats"] + cmd_args[1:]

        # Prepare environment
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)

        parser = FFmpegProgressParser(total_duration_seconds=total_duration_seconds)
        last_progress: Optional[FFmpegProgress] = None

        # Circular bounded buffer for stderr chunks
        stderr_chunks: collections.deque[bytes] = collections.deque()
        stderr_total_bytes: int = 0

        async def _read_stdout(stdout_stream: asyncio.StreamReader):
            nonlocal last_progress
            while True:
                chunk = await stdout_stream.read(16384)
                if not chunk:
                    break
                progress_list = parser.feed(chunk)
                for prog in progress_list:
                    last_progress = prog
                    if progress_callback:
                        try:
                            if inspect.iscoroutinefunction(progress_callback):
                                await progress_callback(prog)
                            else:
                                res = progress_callback(prog)
                                if inspect.isawaitable(res):
                                    await res
                        except Exception as cb_exc:
                            logger.warning(f"Error in FFmpeg progress callback: {cb_exc}")

            # Flush any remaining buffer
            final_progress_list = parser.flush()
            for prog in final_progress_list:
                last_progress = prog
                if progress_callback:
                    try:
                        if inspect.iscoroutinefunction(progress_callback):
                            await progress_callback(prog)
                        else:
                            res = progress_callback(prog)
                            if inspect.isawaitable(res):
                                await res
                    except Exception as cb_exc:
                        logger.warning(f"Error in final FFmpeg progress callback: {cb_exc}")

        async def _read_stderr(stderr_stream: asyncio.StreamReader):
            nonlocal stderr_total_bytes
            while True:
                chunk = await stderr_stream.read(16384)
                if not chunk:
                    break
                stderr_chunks.append(chunk)
                stderr_total_bytes += len(chunk)

                # Maintain bounded size by trimming oldest chunks
                while stderr_total_bytes > self._max_stderr_bytes and len(stderr_chunks) > 1:
                    removed = stderr_chunks.popleft()
                    stderr_total_bytes -= len(removed)

        # 2. Spawn subprocess
        logger.info(f"Launching FFmpeg: {' '.join(cmd_args[:8])}... (timeout={timeout}s)")
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
        self._active_proc = proc
        pid = proc.pid
        logger.info(f"FFmpeg spawned with PID={pid}")

        try:
            # 3. Read stdout and stderr concurrently with timeout
            stream_reader_coro = asyncio.gather(
                _read_stdout(proc.stdout),
                _read_stderr(proc.stderr),
            )

            try:
                if timeout > 0:
                    await asyncio.wait_for(stream_reader_coro, timeout=timeout)
                else:
                    await stream_reader_coro
            except asyncio.TimeoutError:
                logger.error(f"FFmpeg process PID={pid} exceeded timeout of {timeout}s.")
                await terminate_process_tree(proc)
                raise FFmpegTimeoutException(
                    f"FFmpeg process (PID {pid}) timed out after {timeout} seconds."
                )

            # Wait for exit status
            returncode = await proc.wait()

        except asyncio.CancelledError:
            logger.warning(f"FFmpeg execution cancelled for PID={pid}.")
            await terminate_process_tree(proc)
            raise

        except Exception:
            if proc.returncode is None:
                await terminate_process_tree(proc)
            raise

        finally:
            self._active_proc = None

        elapsed = time.monotonic() - start_time

        # Compile captured stderr tail
        raw_stderr = b"".join(stderr_chunks)
        if len(raw_stderr) > self._max_stderr_bytes:
            raw_stderr = raw_stderr[-self._max_stderr_bytes:]
        stderr_str = raw_stderr.decode("utf-8", errors="replace").strip()

        success = (returncode == 0)
        error_msg: Optional[str] = None

        if not success:
            err_lines = [l.strip() for l in stderr_str.splitlines() if l.strip()]
            error_summary = " ".join(err_lines[-3:]) if err_lines else f"Exit code {returncode}"
            error_msg = f"FFmpeg execution failed with code {returncode}: {error_summary}"
            logger.error(f"FFmpeg PID={pid} failed (exit {returncode}): {error_summary}")
        else:
            logger.info(f"FFmpeg PID={pid} completed successfully in {elapsed:.2f}s")

        return FFmpegExecutionResult(
            returncode=returncode,
            success=success,
            command=cmd_args,
            duration_seconds=round(elapsed, 3),
            stderr=stderr_str,
            pid=pid,
            last_progress=last_progress,
            error_message=error_msg,
        )
