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
STATE_FILE = "server.json"
LAUNCHER_PID_FILE = "launcher.pid"
LAUNCHER_LOG_FILE = "launcher.log"
PG_STATE_FILE = "postgres.json"
MINIO_STATE_FILE = "minio.json"

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

_LOG_HANDLE: object | None = None
_JOB_HANDLE: int | None = None
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


def _create_kill_on_close_job() -> int | None:
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return job


def _assign_process_to_job(job: int | None, proc: subprocess.Popen) -> None:
    if not job or sys.platform != "win32":
        return
    handle = proc._handle  # noqa: SLF001
    if handle:
        ctypes.windll.kernel32.AssignProcessToJobObject(job, handle)


def _kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
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


def _postgres_bin(install_dir: Path, name: str) -> Path:
    return install_dir / "tools" / "postgres" / "bin" / name


def _ensure_postgres(data_dir: Path, install_dir: Path) -> None:
    global _PG_PROC
    if _port_open("127.0.0.1", PG_PORT):
        _log(f"postgres already listening on {PG_PORT}")
        return

    pgdata = data_dir / "pgdata"
    pgdata.mkdir(parents=True, exist_ok=True)
    initdb = _postgres_bin(install_dir, "initdb.exe")
    pg_ctl = _postgres_bin(install_dir, "pg_ctl.exe")
    psql = _postgres_bin(install_dir, "psql.exe")
    if not initdb.is_file() or not pg_ctl.is_file():
        raise FileNotFoundError(f"未找到 PostgreSQL 工具：{install_dir / 'tools' / 'postgres' / 'bin'}")

    if not (pgdata / "PG_VERSION").is_file():
        _log("initializing postgres data directory")
        subprocess.run(
            [str(initdb), "-D", str(pgdata), "-U", "tender", "-E", "UTF8", "--locale=C"],
            check=True,
            creationflags=CREATE_NO_WINDOW,
        )
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
    proc = subprocess.Popen(
        [str(pg_ctl), "-D", str(pgdata), "-l", str(log_path), "-w", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    proc.wait(timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"postgres start failed (code {proc.returncode})")

    deadline = time.time() + 30
    while time.time() < deadline:
        if _port_open("127.0.0.1", PG_PORT):
            break
        time.sleep(0.5)
    else:
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
                "-tc",
                "SELECT 1 FROM pg_database WHERE datname='tender_agent'",
            ],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
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
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    _write_json(data_dir, PG_STATE_FILE, {"port": PG_PORT, "data_dir": str(pgdata)})
    _log("postgres ready")


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
        creationflags=CREATE_NO_WINDOW,
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
    for rel in ("Scripts/python.exe", "bin/python.exe"):
        candidate = runtime / rel.replace("/", os.sep)
        if candidate.is_file():
            return candidate
    return runtime / "Scripts" / "python.exe"


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
    env.setdefault("PYTHONUTF8", "1")

    log_path = _backend_log_path(data_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(
        f"\n--- TenderAgent backend start {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} ---\n"
    )
    log_file.flush()

    return subprocess.Popen(
        cmd,
        cwd=str(install_dir),
        env=env,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
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
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )


def _shutdown(install_dir: Path | None, data_dir: Path | None) -> None:
    global _SHUTTING_DOWN, _JOB_HANDLE
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

    if _JOB_HANDLE and sys.platform == "win32":
        ctypes.windll.kernel32.CloseHandle(_JOB_HANDLE)
        _JOB_HANDLE = None


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

    global _JOB_HANDLE, _BACKEND_PROC
    _JOB_HANDLE = _create_kill_on_close_job()

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
        _ensure_postgres(data_dir, install_dir)
        _ensure_minio(data_dir, install_dir)
        proc = _start_server(install_dir, data_dir, port)
    except (FileNotFoundError, RuntimeError) as exc:
        _log(f"start failed: {exc}")
        print(str(exc), file=sys.stderr)
        _shutdown(install_dir, data_dir)
        return 1

    _assign_process_to_job(_JOB_HANDLE, proc)
    _BACKEND_PROC = proc
    _log(f"backend started pid={proc.pid} port={port}")

    if not _wait_for_health(port, proc):
        exit_code = proc.poll()
        _log(f"health check failed exit_code={exit_code}")
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
