import os
import subprocess
import sys
import pytest

STOP_PS1 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "stop.ps1"))


def run_stop_script(data_dir: str, backend_port: int = 18000, frontend_port: int = 15173, root: str = None):
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        STOP_PS1,
        "-DataDir",
        data_dir,
        "-BackendPort",
        str(backend_port),
        "-FrontendPort",
        str(frontend_port),
    ]
    if root:
        cmd.extend(["-Root", root])

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL
    )
    return res


def test_stop_script_already_stopped(tmp_path):
    """Scenario 2: Already stopped -> exit code 0."""
    res = run_stop_script(str(tmp_path))
    assert res.returncode == 0, f"Expected 0, got {res.returncode}. Output: {res.stdout}\n{res.stderr}"
    assert "[SUCCESS] All ClipStudio services have been stopped safely." in res.stdout


def test_stop_script_both_services_running(tmp_path):
    """Scenario 1: Both services running, stopped successfully -> exit code 0."""
    # Spawn 2 isolated dummy processes
    proc1 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    proc2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])

    backend_pid_file = tmp_path / "backend.pid"
    frontend_pid_file = tmp_path / "frontend.pid"

    backend_pid_file.write_text(str(proc1.pid), encoding="utf-8")
    frontend_pid_file.write_text(str(proc2.pid), encoding="utf-8")

    try:
        res = run_stop_script(str(tmp_path))
        assert res.returncode == 0, f"Expected 0, got {res.returncode}. Output: {res.stdout}\n{res.stderr}"
        assert "[SUCCESS] All ClipStudio services have been stopped safely." in res.stdout

        # Verify processes were terminated
        proc1.poll()
        proc2.poll()
        assert proc1.returncode is not None, "Backend process was not terminated"
        assert proc2.returncode is not None, "Frontend process was not terminated"

        # Verify PID files removed
        assert not backend_pid_file.exists()
        assert not frontend_pid_file.exists()
    finally:
        if proc1.poll() is None:
            proc1.kill()
        if proc2.poll() is None:
            proc2.kill()


def test_stop_script_stale_pid_files(tmp_path):
    """Scenario 3: Stale PID files pointing to dead or invalid PIDs -> cleaned up, exit code 0."""
    backend_pid_file = tmp_path / "backend.pid"
    frontend_pid_file = tmp_path / "frontend.pid"

    # 999999 is typically non-existent on Windows
    backend_pid_file.write_text("999999", encoding="utf-8")
    frontend_pid_file.write_text("not_a_number", encoding="utf-8")

    res = run_stop_script(str(tmp_path))
    assert res.returncode == 0, f"Expected 0, got {res.returncode}. Output: {res.stdout}\n{res.stderr}"
    assert "[SUCCESS] All ClipStudio services have been stopped safely." in res.stdout
    assert not backend_pid_file.exists()
    assert not frontend_pid_file.exists()


def test_stop_script_backend_cannot_be_terminated(tmp_path):
    """Scenario 4: Backend process cannot be terminated (PID 4 System) -> non-zero exit code."""
    backend_pid_file = tmp_path / "backend.pid"
    backend_pid_file.write_text("4", encoding="utf-8")  # System PID cannot be killed

    res = run_stop_script(str(tmp_path))
    assert res.returncode != 0, f"Expected non-zero, got {res.returncode}. Output: {res.stdout}"
    assert "[!] ERROR: Failed to cleanly stop all services" in res.stdout


def test_stop_script_frontend_cannot_be_terminated(tmp_path):
    """Scenario 5: Frontend process cannot be terminated -> non-zero exit code."""
    frontend_pid_file = tmp_path / "frontend.pid"
    frontend_pid_file.write_text("4", encoding="utf-8")  # System PID cannot be killed

    res = run_stop_script(str(tmp_path))
    assert res.returncode != 0, f"Expected non-zero, got {res.returncode}. Output: {res.stdout}"
    assert "[!] ERROR: Failed to cleanly stop all services" in res.stdout


def test_stop_script_required_cleanup_fails(tmp_path):
    """Scenario 6: Required cleanup fails (locked PID file) -> non-zero exit code."""
    backend_pid_file = tmp_path / "backend.pid"
    backend_pid_file.write_text("999999", encoding="utf-8")

    # Exclusively lock the PID file using Windows file locking
    f = open(backend_pid_file, "r+")
    try:
        res = run_stop_script(str(tmp_path))
        assert res.returncode != 0, f"Expected non-zero on file lock, got {res.returncode}. Output: {res.stdout}"
        assert "[!] ERROR: Failed to cleanly stop all services" in res.stdout
    finally:
        f.close()


def test_stop_script_port_still_held(tmp_path):
    """Scenario 7: Port still held by process that refuses to release -> non-zero exit code."""
    # Target port 445 (SMB / System PID 4) which is actively listening and cannot be terminated
    res = run_stop_script(str(tmp_path), backend_port=445)
    assert res.returncode != 0, f"Expected non-zero when port cannot be freed, got {res.returncode}. Output: {res.stdout}"
    assert "remains occupied" in res.stdout or "Failed to terminate listener" in res.stdout
    assert "[!] ERROR: Failed to cleanly stop all services" in res.stdout
