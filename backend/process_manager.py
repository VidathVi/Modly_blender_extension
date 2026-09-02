"""
Backend process manager — launches, health-checks, and tears down
the Modly FastAPI backend as a subprocess from within Blender.

The backend runs in its own Python venv (separate from Blender's Python)
to avoid version/ABI mismatches and GPU context conflicts.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------

_process: Optional[subprocess.Popen] = None
_process_lock = threading.Lock()
_status: str = "stopped"  # stopped | starting | running | failed | installing
_status_message: str = ""
_log_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_status() -> str:
    """Return current backend status: stopped | starting | running | failed."""
    return _status


def get_status_message() -> str:
    """Return a human-readable status/error message."""
    return _status_message


def get_log_path() -> Optional[Path]:
    """Return path to the backend log file, or None."""
    return _log_path


def is_running() -> bool:
    """Check if the backend subprocess is alive."""
    with _process_lock:
        return _process is not None and _process.poll() is None


def start() -> bool:
    """
    Launch the Modly backend subprocess.

    Returns True if the process was started (does NOT wait for health).
    The caller should poll ``health_check()`` or use the status panel.
    """
    global _process, _status, _status_message, _log_path

    # Avoid circular import at module level
    from ..preferences import get_api_path, get_preferences, get_data_dir

    with _process_lock:
        if _process is not None and _process.poll() is None:
            if _status == "installing":
                _status_message = "Installation in progress..."
                return True
            _status = "running"
            _status_message = "Backend already running"
            return True

        prefs = get_preferences()
        api_path = get_api_path()
        data_dir = get_data_dir()

        # Validate
        main_py = api_path / "main.py"
        if not main_py.is_file():
            _status = "failed"
            _status_message = f"main.py not found at {api_path}"
            log.error(_status_message)
            return False

        # Find the backend venv Python
        python_exe = _find_venv_python(api_path)
        if python_exe is None:
            # We need to create the venv
            setup_script = Path(__file__).parent / "setup_venv.py"
            addon_data = Path(os.path.expanduser("~")) / ".modly" / "blender_extension"
            addon_data.mkdir(parents=True, exist_ok=True)
            _log_path = addon_data / "backend.log"
            log_file = open(_log_path, "w", encoding="utf-8")

            cmd = [sys.executable, str(setup_script), str(api_path)]
            log.info(f"Starting venv setup: {' '.join(cmd)}")
            
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW
            
            try:
                _process = subprocess.Popen(
                    cmd,
                    cwd=str(api_path),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=creation_flags,
                )
                _status = "installing"
                _status_message = "Creating Python virtual environment and installing dependencies... This may take a minute."
                return True
            except Exception as exc:
                _status = "failed"
                _status_message = f"Failed to start venv setup: {exc}"
                log.error(_status_message, exc_info=True)
                return False

        # Prepare log file
        addon_data = Path(os.path.expanduser("~")) / ".modly" / "blender_extension"
        addon_data.mkdir(parents=True, exist_ok=True)
        _log_path = addon_data / "backend.log"
        log_file = open(_log_path, "w", encoding="utf-8")

        # Environment for the subprocess
        env = os.environ.copy()
        env["MODELS_DIR"] = str(data_dir / "models")
        env["WORKSPACE_DIR"] = str(data_dir / "workspace")
        # Extensions dir — the Modly app stores installed extensions here
        extensions_dir = data_dir / "extensions"
        if extensions_dir.is_dir():
            env["EXTENSIONS_DIR"] = str(extensions_dir)

        # Build the command
        port = prefs.backend_port
        cmd = [
            str(python_exe),
            "-m", "uvicorn",
            "main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
        ]

        log.info(f"Starting backend: {' '.join(cmd)}")
        log.info(f"CWD: {api_path}")
        log.info(f"Log: {_log_path}")

        try:
            # CREATE_NO_WINDOW prevents a console window on Windows
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            _process = subprocess.Popen(
                cmd,
                cwd=str(api_path),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
            _status = "starting"
            _status_message = f"Backend starting on port {port}..."
            log.info(f"Backend PID: {_process.pid}")
            return True

        except Exception as exc:
            _status = "failed"
            _status_message = f"Failed to start backend: {exc}"
            log.error(_status_message, exc_info=True)
            return False


def stop() -> None:
    """Terminate the backend subprocess cleanly."""
    global _process, _status, _status_message

    with _process_lock:
        if _process is None:
            _status = "stopped"
            _status_message = ""
            return

        if _process.poll() is None:
            log.info(f"Terminating backend PID {_process.pid}")
            try:
                _process.terminate()
                # Give it a few seconds to shut down gracefully
                try:
                    _process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log.warning("Backend did not terminate in 5s, killing")
                    _process.kill()
                    _process.wait(timeout=3)
            except Exception as exc:
                log.error(f"Error stopping backend: {exc}", exc_info=True)

        _process = None
        _status = "stopped"
        _status_message = "Backend stopped"
        log.info("Backend stopped")


def restart() -> bool:
    """Stop and re-start the backend."""
    stop()
    time.sleep(0.5)
    return start()


def health_check() -> bool:
    """
    Poll the backend's health endpoint.

    Returns True if the backend responds, False otherwise.
    Also updates the global status.
    """
    global _status, _status_message

    from ..preferences import get_backend_url
    import urllib.request
    import urllib.error

    url = f"{get_backend_url()}/docs"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                _status = "running"
                _status_message = "Backend healthy"
                return True
    except urllib.error.URLError:
        pass
    except Exception:
        pass

    start_backend_now = False

    # If the process died, mark as failed
    with _process_lock:
        if _process is not None and _process.poll() is not None:
            exit_code = _process.returncode
            if _status == "installing":
                if exit_code == 0:
                    _status = "stopped"
                    _status_message = "Installation successful. Starting backend..."
                    _process = None
                    start_backend_now = True
                else:
                    _status = "failed"
                    _status_message = f"Installation failed with code {exit_code} — see log"
                    _process = None
                    return False
            else:
                _status = "failed"
                _status_message = f"Backend exited with code {exit_code} — see log"
                _process = None
                return False

    if start_backend_now:
        return start()

    # Process still running but not responding yet
    if _status == "starting":
        _status_message = "Backend starting, waiting for health response..."
    elif _status == "installing":
        _status_message = "Creating Python virtual environment and installing dependencies... This may take a minute."
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_venv_python(api_path: Path) -> Optional[Path]:
    """
    Locate the Python executable in the backend's venv.

    Checks multiple common locations relative to the Modly installation.
    """
    candidates = []

    # venv inside api/
    candidates.append(api_path / ".venv" / "Scripts" / "python.exe")
    candidates.append(api_path / ".venv" / "bin" / "python")
    candidates.append(api_path / "venv" / "Scripts" / "python.exe")
    candidates.append(api_path / "venv" / "bin" / "python")

    # venv one level up from api/ (e.g., C:\Modly\.venv)
    parent = api_path.parent
    candidates.append(parent / ".venv" / "Scripts" / "python.exe")
    candidates.append(parent / ".venv" / "bin" / "python")
    candidates.append(parent / "venv" / "Scripts" / "python.exe")
    candidates.append(parent / "venv" / "bin" / "python")

    # Resources dir (packaged Modly app)
    candidates.append(parent / "resources" / ".venv" / "Scripts" / "python.exe")
    candidates.append(parent / "resources" / ".venv" / "bin" / "python")

    for p in candidates:
        if p.is_file():
            return p

    return None
