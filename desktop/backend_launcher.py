"""标书智能体桌面端 sidecar — 启动 PostgreSQL、MinIO 与 uvicorn。"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 18766
PG_PORT = 55432
MINIO_PORT = 59000
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
STATE_FILE = "server.json"
LAUNCHER_PID_FILE = "launcher.pid"
LAUNCHER_LOG_FILE = "launcher.log"
PG_STATE_FILE = "postgres.json"
MINIO_STATE_FILE = "minio.json"


def _bootstrap_touch() -> None:
    """Write a log line as early as possible to diagnose pre-main failures."""
    try:
        data = os.environ.get("TENDER_DATA_DIR")
        if not data:
            local = os.environ.get("LOCALAPPDATA")
            data = str(Path(local) / "TenderAgent" / "data") if local else str(
                Path.home() / "AppData" / "Local" / "TenderAgent" / "data"
            )
        path = Path(data)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / LAUNCHER_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(
                f"\n--- bootstrap import pid={os.getpid()} exe={sys.executable} ---\n"
            )
    except Exception as exc:
        try:
            fallback = Path(os.environ.get("TEMP", ".")) / "TenderAgent-bootstrap.log"
            fallback.write_text(f"bootstrap failed: {exc}\n", encoding="utf-8")
        except OSError:
            pass


_bootstrap_touch()

_LOG_HANDLE: object | None = None
_BACKEND_PROC: subprocess.Popen | None = None
_PG_PROC: subprocess.Popen | None = None
_MINIO_PROC: subprocess.Popen | None = None
_SHUTTING_DOWN = False


def _install_dir() -> Path:
    if os.environ.get("TENDER_INSTALL_DIR"):
        return Path(os.environ["TENDER_INSTALL_DIR"]).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if os.environ.get("TENDER_DATA_DIR"):
        return Path(os.environ["TENDER_DATA_DIR"]).resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "TenderAgent" / "data").resolve()


def _init_log(data_dir: Path) -> None:
    global _LOG_HANDLE
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LAUNCHER_LOG_FILE
    try:
        _LOG_HANDLE = open(path, "a", encoding="utf-8")
        _LOG_HANDLE.write(
            f"\n--- TenderAgent backend {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} ---\n"
        )
        _LOG_HANDLE.flush()
    except OSError:
        _LOG_HANDLE = None


def _log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] [launcher] {message}"
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write(line + "\n")
            _LOG_HANDLE.flush()
        except OSError:
            pass


def _state_path(data_dir: Path, name: str) -> Path:
    return data_dir / name


def _read_json(data_dir: Path, name: str) -> dict | None:
    path = _state_path(data_dir, name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(data_dir: Path, name: str, payload: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _state_path(data_dir, name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _remove_runtime_files(data_dir: Path) -> None:
    for name in (STATE_FILE, LAUNCHER_PID_FILE, PG_STATE_FILE, MINIO_STATE_FILE):
        path = data_dir / name
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


def _health_ok(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _port_open(host: str, port: int) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and exit_code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_subprocess_flags(),
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _subprocess_flags() -> int:
    if sys.platform != "win32":
        return 0
    return CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB


def _postgres_root(install_dir: Path) -> Path:
    return install_dir / "tools" / "postgres"


def _postgres_bin(install_dir: Path, name: str) -> Path:
    return _postgres_root(install_dir) / "bin" / name


def _postgres_env(install_dir: Path, pgdata: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    pg_bin = str(_postgres_root(install_dir) / "bin")
    env["PATH"] = pg_bin + os.pathsep + env.get("PATH", "")
    env["PGPORT"] = str(PG_PORT)
    if pgdata is not None:
        env["PGDATA"] = str(pgdata)
    return env


def _append_log_tail(data_dir: Path, name: str, lines: int = 12) -> None:
    path = data_dir / name
    if not path.is_file():
        return
    try:
        tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        if tail:
            _log(f"{name} tail:")
            for line in tail:
                _log(f"  {line}")
    except OSError:
        pass


def _ensure_postgres(data_dir: Path, install_dir: Path) -> None:
    global _PG_PROC
    if _port_open("127.0.0.1", PG_PORT):
        _log(f"postgres already listening on {PG_PORT}")
        return

    pgdata = data_dir / "pgdata"
    initdb = _postgres_bin(install_dir, "initdb.exe")
    pg_ctl = _postgres_bin(install_dir, "pg_ctl.exe")
    psql = _postgres_bin(install_dir, "psql.exe")
    if not initdb.is_file() or not pg_ctl.is_file():
        raise FileNotFoundError(f"未找到 PostgreSQL 工具：{_postgres_root(install_dir) / 'bin'}")

    if not (pgdata / "PG_VERSION").is_file():
        if pgdata.exists() and any(pgdata.iterdir()):
            _log("resetting incomplete postgres data directory")
            import shutil

            shutil.rmtree(pgdata, ignore_errors=True)
        pgdata.mkdir(parents=True, exist_ok=True)
        _log("initializing postgres data directory")
        initdb_cmd = [
            str(initdb),
            "-D",
            str(pgdata),
            "-U",
            "tender",
            "-E",
            "UTF8",
            "--auth-local=trust",
            "--auth-host=trust",
        ]
        if sys.platform != "win32":
            initdb_cmd.append("--locale=C")
        result = subprocess.run(
            initdb_cmd,
            capture_output=True,
            text=True,
            env=_postgres_env(install_dir, pgdata),
            creationflags=_subprocess_flags(),
        )
        if result.returncode != 0:
            _log(f"initdb failed code={result.returncode}")
            if result.stdout.strip():
                _log(f"initdb stdout: {result.stdout.strip()}")
            if result.stderr.strip():
                _log(f"initdb stderr: {result.stderr.strip()}")
            raise RuntimeError(f"postgres initdb failed (code {result.returncode})")

        conf = pgdata / "postgresql.conf"
        hba = pgdata / "pg_hba.conf"
        if conf.is_file():
            conf.write_text(
                conf.read_text(encoding="utf-8")
                + f"\nport = {PG_PORT}\nlisten_addresses = '127.0.0.1'\n",
                encoding="utf-8",
            )
        if hba.is_file():
            hba.write_text(
                hba.read_text(encoding="utf-8")
                + "\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\n",
                encoding="utf-8",
            )

    log_path = data_dir / "postgres.log"
    _log("starting postgres")
    result = subprocess.run(
        [
            str(pg_ctl),
            "-D",
            str(pgdata),
            "-l",
            str(log_path),
            "-o",
            f"-p {PG_PORT}",
            "-w",
            "start",
        ],
        capture_output=True,
        text=True,
        env=_postgres_env(install_dir, pgdata),
        creationflags=_subprocess_flags(),
        timeout=60,
    )
    if result.returncode != 0:
        _log(f"pg_ctl start failed code={result.returncode}")
        if result.stdout.strip():
            _log(f"pg_ctl stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            _log(f"pg_ctl stderr: {result.stderr.strip()}")
        _append_log_tail(data_dir, "postgres.log")
        raise RuntimeError(f"postgres start failed (code {result.returncode})")

    deadline = time.time() + 30
    while time.time() < deadline:
        if _port_open("127.0.0.1", PG_PORT):
            break
        time.sleep(0.5)
    else:
        _append_log_tail(data_dir, "postgres.log")
        raise RuntimeError("postgres did not become ready")

    if psql.is_file():
        subprocess.run(
            [
                str(psql),
                "-h",
                "127.0.0.1",
                "-p",
                str(PG_PORT),
                "-U",
                "tender",
                "-d",
                "postgres",
                "-c",
                "CREATE DATABASE tender_agent;",
            ],
            capture_output=True,
            text=True,
            env=_postgres_env(install_dir, pgdata),
            creationflags=_subprocess_flags(),
            check=False,
        )
    _write_json(data_dir, PG_STATE_FILE, {"port": PG_PORT, "data_dir": str(pgdata)})
    _log("postgres ready")


def _ensure_postgres_with_retry(data_dir: Path, install_dir: Path) -> None:
    try:
        _ensure_postgres(data_dir, install_dir)
    except RuntimeError as exc:
        pgdata = data_dir / "pgdata"
        if not pgdata.exists():
            raise
        _log(f"postgres setup failed ({exc}); resetting data directory and retrying once")
        import shutil

        shutil.rmtree(pgdata, ignore_errors=True)
        _ensure_postgres(data_dir, install_dir)


def _ensure_minio(data_dir: Path, install_dir: Path) -> None:
    global _MINIO_PROC
    if _port_open("127.0.0.1", MINIO_PORT):
        _log(f"minio already listening on {MINIO_PORT}")
        return

    minio_exe = install_dir / "tools" / "minio.exe"
    if not minio_exe.is_file():
        raise FileNotFoundError(f"未找到 MinIO：{minio_exe}")

    storage_dir = data_dir / "minio"
    storage_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "minio.log"
    env = os.environ.copy()
    env["MINIO_ROOT_USER"] = "minioadmin"
    env["MINIO_ROOT_PASSWORD"] = "minioadmin"

    _log("starting minio")
    log_file = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            str(minio_exe),
            "server",
            str(storage_dir),
            "--address",
            f"127.0.0.1:{MINIO_PORT}",
            "--console-address",
            f"127.0.0.1:{MINIO_PORT + 1}",
        ],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=_subprocess_flags(),
    )
    _MINIO_PROC = proc
    _write_json(data_dir, MINIO_STATE_FILE, {"port": MINIO_PORT, "pid": proc.pid})

    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("minio exited early")
        if _port_open("127.0.0.1", MINIO_PORT):
            _log("minio ready")
            return
        time.sleep(0.5)
    raise RuntimeError("minio did not become ready")


def _runtime_python(install_dir: Path) -> Path:
    runtime = install_dir / "runtime"
    for rel in ("python.exe", "Scripts/python.exe", "bin/python.exe"):
        candidate = runtime / rel.replace("/", os.sep)
        if candidate.is_file():
            return candidate
    return runtime / "python.exe"


def _backend_log_path(data_dir: Path) -> Path:
    return data_dir / "backend.log"


def _start_server(install_dir: Path, data_dir: Path, port: int) -> subprocess.Popen:
    python = _runtime_python(install_dir)
    backend_dir = install_dir / "backend"
    if not backend_dir.is_dir():
        raise FileNotFoundError(f"未找到 backend 目录：{backend_dir}")
    assets_dir = install_dir / "frontend" / "dist" / "assets"
    if not assets_dir.is_dir():
        raise FileNotFoundError(f"未找到前端资源：{assets_dir}")

    if not python.is_file():
        raise FileNotFoundError(f"未找到运行时 Python：{python}")

    cmd = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        str(backend_dir),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    env = os.environ.copy()
    env["TENDER_DESKTOP"] = "1"
    env["TENDER_INSTALL_DIR"] = str(install_dir)
    env["TENDER_DATA_DIR"] = str(data_dir)
    env["ASPOSE_LICENSE_PATH"] = str(install_dir / "aspose" / "Aspose.License.txt")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(data_dir / "pycache")

    log_path = _backend_log_path(data_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(
        f"\n--- TenderAgent backend start {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} ---\n"
    )
    log_file.flush()

    return subprocess.Popen(
        cmd,
        cwd=str(data_dir),
        env=env,
        creationflags=_subprocess_flags(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def _wait_for_health(port: int, proc: subprocess.Popen, timeout: float = 120.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        if _health_ok(port):
            return True
        time.sleep(0.5)
    return False


def _stop_postgres(data_dir: Path, install_dir: Path) -> None:
    pg_ctl = _postgres_bin(install_dir, "pg_ctl.exe")
    pgdata = data_dir / "pgdata"
    if pg_ctl.is_file() and pgdata.is_dir():
        subprocess.run(
            [str(pg_ctl), "-D", str(pgdata), "-w", "stop", "fast"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_postgres_env(install_dir, pgdata),
            creationflags=_subprocess_flags(),
            check=False,
        )


def _shutdown(install_dir: Path | None, data_dir: Path | None) -> None:
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    _log("shutdown")

    if _BACKEND_PROC is not None and _BACKEND_PROC.poll() is None:
        _kill_process_tree(_BACKEND_PROC.pid)
        try:
            _BACKEND_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    elif data_dir is not None:
        state = _read_json(data_dir, STATE_FILE)
        if state:
            backend_pid = int(state.get("pid") or 0) or None
            if backend_pid and _pid_alive(backend_pid):
                _kill_process_tree(backend_pid)

    if _MINIO_PROC is not None and _MINIO_PROC.poll() is None:
        _kill_process_tree(_MINIO_PROC.pid)
    elif data_dir is not None:
        state = _read_json(data_dir, MINIO_STATE_FILE)
        if state:
            pid = int(state.get("pid") or 0)
            if pid and _pid_alive(pid):
                _kill_process_tree(pid)

    if install_dir is not None and data_dir is not None:
        _stop_postgres(data_dir, install_dir)

    if data_dir is not None:
        _remove_runtime_files(data_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="TenderAgent backend sidecar")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    install_dir = _install_dir()
    data_dir = _data_dir()
    port = args.port
    data_dir.mkdir(parents=True, exist_ok=True)
    _init_log(data_dir)
    _log(f"install_dir={install_dir} port={port}")

    if _health_ok(port):
        state = _read_json(data_dir, STATE_FILE)
        pid = int(state.get("pid") or 0) if state else 0
        if pid and _pid_alive(pid):
            _log(f"reusing healthy backend pid={pid} port={port}")
            _write_json(data_dir, LAUNCHER_PID_FILE, {"pid": os.getpid()})
            try:
                while _health_ok(port) and _pid_alive(pid):
                    time.sleep(1.0)
            except KeyboardInterrupt:
                pass
            return 0

    global _BACKEND_PROC
    _BACKEND_PROC = None

    def _on_exit() -> None:
        _shutdown(install_dir, data_dir)

    atexit.register(_on_exit)

    def _signal_handler(signum: int, _frame: object) -> None:
        _shutdown(install_dir, data_dir)
        raise SystemExit(128 + signum)

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is not None:
            try:
                signal.signal(sig, _signal_handler)
            except (OSError, ValueError):
                pass
    if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)
        except (OSError, ValueError):
            pass

    _remove_runtime_files(data_dir)

    try:
        _ensure_postgres_with_retry(data_dir, install_dir)
        _ensure_minio(data_dir, install_dir)
        proc = _start_server(install_dir, data_dir, port)
    except Exception as exc:
        _log(f"start failed: {exc}")
        print(str(exc), file=sys.stderr)
        _append_log_tail(data_dir, "postgres.log")
        _append_log_tail(data_dir, "minio.log")
        _append_log_tail(data_dir, "backend.log")
        _shutdown(install_dir, data_dir)
        return 1

    _BACKEND_PROC = proc
    _log(f"backend started pid={proc.pid} port={port}")

    if not _wait_for_health(port, proc):
        exit_code = proc.poll()
        _log(f"health check failed exit_code={exit_code}")
        _append_log_tail(data_dir, "backend.log")
        _append_log_tail(data_dir, "postgres.log")
        _append_log_tail(data_dir, "minio.log")
        _shutdown(install_dir, data_dir)
        return 1

    _write_json(
        data_dir,
        STATE_FILE,
        {
            "port": port,
            "pid": proc.pid,
            "url": f"http://127.0.0.1:{port}",
            "started_at": int(time.time()),
        },
    )
    _write_json(data_dir, LAUNCHER_PID_FILE, {"pid": os.getpid()})
    _log("backend healthy")

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    _shutdown(install_dir, data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
