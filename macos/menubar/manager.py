"""Background process helpers for the Humanizer menu-bar app."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("humanizer.menubar")

DEFAULT_PORT = 8000
HEALTH_URL = f"http://127.0.0.1:{DEFAULT_PORT}/health"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
_DEPS_PROBE = "import fastapi, uvicorn, language_tool_python; import AppKit"


@dataclass
class HealthSnapshot:
    server_ok: bool
    ollama_ok: bool
    detail: str


def support_dir() -> Path:
    path = Path.home() / "Library" / "Application Support" / "Humanizer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = Path.home() / "Library" / "Logs" / "Humanizer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_file() -> Path:
    return support_dir() / "server.pid"


def resolve_project_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    env = os.environ.get("HUMANIZER_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    here = Path(__file__).resolve()
    # macos/menubar/manager.py -> repo root
    repo_candidate = here.parents[2]
    if (repo_candidate / "server.py").is_file():
        return repo_candidate

    bundled = Path(os.environ.get("HUMANIZER_BUNDLE_RESOURCES", "")) / "HumanizerHome"
    if (bundled / "server.py").is_file():
        return bundled.resolve()

    app_support = support_dir() / "Home"
    if (app_support / "server.py").is_file():
        return app_support.resolve()

    return repo_candidate


def hardware_is_apple_silicon() -> bool:
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "hw.optional.arm64"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out == "1"
    except (OSError, subprocess.CalledProcessError):
        return platform.machine() == "arm64"


def _native_argv(argv: list[str]) -> list[str]:
    """Wrap a command so it cannot accidentally run under Rosetta on Apple Silicon."""
    if hardware_is_apple_silicon():
        return ["/usr/bin/arch", "-arm64", *argv]
    return argv


def preferred_host_python() -> Path:
    """Pick a native host Python for creating the Application Support venv."""
    candidates: list[Path] = []
    if hardware_is_apple_silicon():
        # Prefer stable brew Pythons, then Apple CLT, then whatever `python3` is.
        candidates.extend(
            [
                Path("/opt/homebrew/bin/python3.12"),
                Path("/opt/homebrew/bin/python3.11"),
                Path("/opt/homebrew/bin/python3.10"),
                Path("/usr/bin/python3"),
                Path("/opt/homebrew/bin/python3"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/local/bin/python3.12"),
                Path("/usr/local/bin/python3.11"),
                Path("/usr/local/bin/python3"),
                Path("/usr/bin/python3"),
            ]
        )

    which = shutil.which("python3")
    if which:
        candidates.append(Path(which))
    candidates.append(Path("/usr/bin/python3"))

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        if os.access(path, os.X_OK):
            return path
    return Path("/usr/bin/python3")


def python_bin(root: Path) -> Path:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return venv_python
    return preferred_host_python()


def _probe_imports(python: Path) -> bool:
    result = subprocess.run(
        _native_argv([str(python), "-c", _DEPS_PROBE]),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _http_json(url: str, timeout: float = 1.5) -> dict | None:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None


def check_health() -> HealthSnapshot:
    ollama = _http_json(OLLAMA_TAGS_URL) is not None
    payload = _http_json(HEALTH_URL)
    if payload and payload.get("ok"):
        return HealthSnapshot(True, ollama, "Server online")
    if ollama:
        return HealthSnapshot(False, True, "Server offline")
    return HealthSnapshot(False, False, "Server offline")


def ensure_ollama_running() -> bool:
    if _http_json(OLLAMA_TAGS_URL) is not None:
        return True

    app = Path("/Applications/Ollama.app")
    if app.is_dir():
        subprocess.Popen(
            ["open", "-a", "Ollama"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        binary = shutil.which("ollama")
        if not binary:
            logger.warning("Ollama not installed")
            return False
        subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    deadline = time.time() + 25
    while time.time() < deadline:
        if _http_json(OLLAMA_TAGS_URL) is not None:
            return True
        time.sleep(0.5)
    return False


def _read_pid() -> int | None:
    path = pid_file()
    if not path.is_file():
        return None
    try:
        return int(path.read_text().strip())
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_server() -> None:
    pid = _read_pid()
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + 5
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.2)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    # Also clear anything still bound to the port.
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{DEFAULT_PORT}"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                os.kill(int(line), signal.SIGTERM)
            except (OSError, ValueError):
                pass
    except FileNotFoundError:
        pass

    if pid_file().is_file():
        pid_file().unlink(missing_ok=True)


def ensure_venv(root: Path) -> Path:
    venv = root / ".venv"
    python = venv / "bin" / "python"
    marker = venv / ".humanizer_deps_ready"
    host = preferred_host_python()

    # Recreate when missing, or when prior installs left broken/arch-mismatched wheels.
    needs_create = not python.is_file()
    if python.is_file() and marker.is_file() and _probe_imports(python):
        return python
    if python.is_file() and not _probe_imports(python):
        logger.warning("Rebuilding broken virtual environment at %s", venv)
        shutil.rmtree(venv, ignore_errors=True)
        needs_create = True
        marker.unlink(missing_ok=True)

    if needs_create or not python.is_file():
        logger.info("Creating virtual environment at %s with %s", venv, host)
        subprocess.run(
            _native_argv([str(host), "-m", "venv", str(venv)]),
            check=True,
            cwd=str(root),
        )
        python = venv / "bin" / "python"

    if marker.is_file() and _probe_imports(python):
        return python

    logger.info("Installing Python packages into %s", venv)
    subprocess.run(
        _native_argv([str(python), "-m", "pip", "install", "--upgrade", "pip"]),
        check=False,
        cwd=str(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    req = root / "requirements.txt"
    if req.is_file():
        subprocess.run(
            _native_argv([str(python), "-m", "pip", "install", "-r", str(req)]),
            check=False,
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    subprocess.run(
        _native_argv([str(python), "-m", "pip", "install", "rumps", "pyobjc-framework-Cocoa"]),
        check=False,
        cwd=str(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if _probe_imports(python):
        marker.write_text("ok\n", encoding="utf-8")
    else:
        logger.error("Dependency install incomplete; server may fail to start")
    return python


def start_server(root: Path) -> bool:
    if check_health().server_ok:
        return True

    # Another copy of the menu-bar app may already be starting the server.
    pid = _read_pid()
    if pid and _pid_alive(pid):
        deadline = time.time() + 45
        while time.time() < deadline:
            if check_health().server_ok:
                return True
            time.sleep(0.5)
        if check_health().server_ok:
            return True

    stop_server()
    ensure_ollama_running()
    python = ensure_venv(root)
    log_path = logs_dir() / "server.log"
    log_file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115

    env = os.environ.copy()
    env.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
    if "OLLAMA_LLM_LIBRARY" not in env:
        env["OLLAMA_LLM_LIBRARY"] = "metal"
    try:
        from macos.menubar.settings import apply_to_env

        env = apply_to_env(env)
        logger.info(
            "Starting server with grammar=%s writing=%s",
            env.get("OLLAMA_GRAMMAR_MODEL"),
            env.get("OLLAMA_WRITING_MODEL"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not apply model settings: %s", exc)

    process = subprocess.Popen(
        _native_argv([str(python), "server.py"]),
        cwd=str(root),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    pid_file().write_text(str(process.pid), encoding="utf-8")

    deadline = time.time() + 60
    while time.time() < deadline:
        if check_health().server_ok:
            return True
        if process.poll() is not None:
            logger.error("Server exited early; see %s", log_path)
            return False
        time.sleep(0.4)
    return check_health().server_ok


def restart_server(root: Path) -> bool:
    stop_server()
    time.sleep(0.5)
    return start_server(root)


def ensure_home_payload(resources: Path) -> Path:
    """Copy bundled server home into Application Support on first run."""
    dest = support_dir() / "Home"
    marker = dest / ".humanizer_home_ready"
    src = resources / "HumanizerHome"
    if not src.is_dir():
        return resolve_project_root()

    if not marker.is_file() or not (dest / "server.py").is_file():
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(
                ".venv",
                "__pycache__",
                "*.pyc",
                "llama.cpp",
                "models",
                "dist",
                ".git",
                "nltk_data",
                "benchmark_results*.json",
            ),
        )
        marker.write_text("ok\n", encoding="utf-8")
    else:
        # Refresh menu-bar code and key server modules on launch without wiping .venv
        for rel in (
            "server.py",
            "writing_agent.py",
            "security.py",
            "cloud_ai.py",
            "rag.py",
            "requirements.txt",
            "macos",
        ):
            s = src / rel
            d = dest / rel
            if not s.exists():
                continue
            if s.is_dir():
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(
                    s,
                    d,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)

    return dest
