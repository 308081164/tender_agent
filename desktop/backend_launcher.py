"""标书智能体桌面端 sidecar — 启动 PostgreSQL、MinIO 与 uvicorn。"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 18766
PG_PORT_DEFAULT = 25432
PG_PORT_LEGACY = 55432
PG_TCP_HOST = "127.0.0.1"
PG_PIPE_HOST = "."
# Small curated list — avoid scanning 100+ ports (each probe can block ~1.5s on Windows).
PG_TCP_PORT_CANDIDATES = (
    PG_PORT_DEFAULT,
    25433,
    25434,
    25435,
    25436,
    PG_PORT_LEGACY,
    5433,
    15432,
)
PORT_PROBE_TIMEOUT = 0.25
PG_ISREADY_PROBE_TIMEOUT = 2.0
MINIO_PORT = 59000
CREATE_NO_WINDOW = 0x08000000
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
_ACTIVE_PG_PORT: int | None = None
_ACTIVE_PG_HOST: str = PG_TCP_HOST


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


def _port_open(host: str, port: int, timeout: float = PORT_PROBE_TIMEOUT) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
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
    # CREATE_BREAKAWAY_FROM_JOB fails with ERROR_ACCESS_DENIED when TenderAgent
    # itself is already inside a non-breakaway Windows Job Object (for example
    # CI runners and some enterprise launchers). Children remain manageable as
    # part of the launcher process tree without that flag.
    return CREATE_NO_WINDOW


def _subprocess_capture_kwargs() -> dict[str, object]:
    """Capture subprocess text safely on localized Windows consoles (GBK output)."""
    return {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


def _is_windows_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _postgres_admin_error_message() -> str:
    return (
        "PostgreSQL 无法在 Windows 管理员账户下直接启动。"
        "请关闭「以管理员身份运行」，使用普通用户启动标书智能体。"
    )


def _postgres_bind_error_message(port: int) -> str:
    return (
        f"PostgreSQL 无法绑定本地端口 {port}（Permission denied）。"
        "这通常由 Windows/Hyper-V 保留端口范围导致。"
        "安装包会自动尝试其他端口或命名管道；若仍失败，请删除数据目录后重试。"
    )


def _postgres_start_failed_message() -> str:
    return (
        "PostgreSQL 无法启动（TCP 端口与命名管道均失败）。"
        "请删除 %LOCALAPPDATA%\\TenderAgent\\data 后重试，"
        "并确保未勾选快捷方式的「以管理员身份运行」。"
    )


def _postgres_root(install_dir: Path) -> Path:
    return install_dir / "tools" / "postgres"


def _postgres_bin(install_dir: Path, name: str) -> Path:
    return _postgres_root(install_dir) / "bin" / name


def _postgres_env(
    install_dir: Path, pgdata: Path | None = None, port: int | None = None
) -> dict[str, str]:
    env = os.environ.copy()
    pg_bin = str(_postgres_root(install_dir) / "bin")
    env["PATH"] = pg_bin + os.pathsep + env.get("PATH", "")
    env["PGPORT"] = str(port if port is not None else (_ACTIVE_PG_PORT or PG_PORT_DEFAULT))
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    if pgdata is not None:
        env["PGDATA"] = str(pgdata)
    return env


def _can_bind_port(port: int) -> bool:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _read_pg_port_from_conf(pgdata: Path) -> int | None:
    conf = pgdata / "postgresql.conf"
    if not conf.is_file():
        return None
    try:
        match = re.search(r"^port\s*=\s*(\d+)", conf.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return int(match.group(1))
    except (OSError, ValueError):
        pass
    return None


def _read_pg_port_from_state(data_dir: Path) -> int | None:
    saved = _read_pg_state(data_dir)
    return saved[1] if saved else None


def _read_pg_host_from_state(data_dir: Path) -> str | None:
    saved = _read_pg_state(data_dir)
    return saved[0] if saved else None


def _read_pg_state(data_dir: Path) -> tuple[str, int] | None:
    state = _read_json(data_dir, PG_STATE_FILE)
    if not state:
        return None
    try:
        port = int(state.get("port") or 0)
    except (TypeError, ValueError):
        return None
    if port <= 0:
        return None
    host = str(state.get("host") or PG_TCP_HOST).strip() or PG_TCP_HOST
    return host, port


def _save_pg_state(data_dir: Path, pgdata: Path, host: str, port: int, pid: int | None = None) -> None:
    payload: dict[str, object] = {"host": host, "port": port, "data_dir": str(pgdata)}
    if pid is not None:
        payload["pid"] = pid
    _write_json(data_dir, PG_STATE_FILE, payload)


def _postgres_port_candidates(data_dir: Path, pgdata: Path) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []

    def add(port: int | None) -> None:
        if port and 1024 <= port <= 65535 and port not in seen:
            seen.add(port)
            ordered.append(port)

    add(_read_pg_port_from_state(data_dir))
    add(_read_pg_port_from_conf(pgdata))
    for port in PG_TCP_PORT_CANDIDATES:
        add(port)
    return ordered


def _update_postgresql_conf_listen(pgdata: Path, *, tcp: bool) -> None:
    conf = pgdata / "postgresql.conf"
    if not conf.is_file():
        return
    listen = "listen_addresses = '127.0.0.1'" if tcp else "listen_addresses = ''"
    text = conf.read_text(encoding="utf-8")
    if re.search(r"^listen_addresses\s*=", text, flags=re.MULTILINE):
        text = re.sub(
            r"^listen_addresses\s*=.*$", listen, text, count=1, flags=re.MULTILINE
        )
    else:
        text += f"\n{listen}\n"
    conf.write_text(text, encoding="utf-8")


def _log_windows_port_diagnostics() -> None:
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_subprocess_flags(),
            timeout=10,
        )
        if result.stdout.strip():
            _log("windows excluded TCP port ranges:")
            for line in result.stdout.strip().splitlines()[:12]:
                _log(f"  {line.strip()}")
    except OSError as exc:
        _log(f"could not read excluded port ranges: {exc}")


def _kill_stale_postgres_for_pgdata(data_dir: Path) -> None:
    pgdata = data_dir / "pgdata"
    if not pgdata.is_dir():
        return
    pid = _read_postmaster_pid(pgdata)
    if pid and _pid_alive(pid):
        _log(f"killing stale postgres pid={pid} from postmaster.pid")
        _kill_process_tree(pid)
        pid_file = pgdata / "postmaster.pid"
        if pid_file.is_file():
            try:
                pid_file.unlink()
            except OSError:
                pass
        return
    if sys.platform != "win32":
        return
    escaped = str(pgdata).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='postgres.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{escaped}*' }} | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_subprocess_flags(),
            timeout=8,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            stale_pid = int(line)
            if _pid_alive(stale_pid):
                _log(f"killing stale postgres.exe pid={stale_pid} for pgdata")
                _kill_process_tree(stale_pid)
    except OSError as exc:
        _log(f"could not scan stale postgres processes: {exc}")


def _pg_isready_once(
    install_dir: Path,
    pgdata: Path,
    port: int,
    host: str,
    timeout: float = PG_ISREADY_PROBE_TIMEOUT,
) -> bool:
    pg_isready = _postgres_bin(install_dir, "pg_isready.exe")
    if not pg_isready.is_file():
        return False
    try:
        result = subprocess.run(
            [str(pg_isready), "-h", host, "-p", str(port), "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_postgres_env(install_dir, pgdata, port),
            creationflags=_subprocess_flags(),
            timeout=timeout,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _postgres_accepts_connections(
    install_dir: Path,
    pgdata: Path,
    port: int,
    host: str,
    timeout: float = 30.0,
) -> bool:
    if _pg_isready_once(install_dir, pgdata, port, host):
        return True
    if host == PG_PIPE_HOST:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _pg_isready_once(install_dir, pgdata, port, host):
            return True
        if _port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def _update_postgresql_conf_port(pgdata: Path, port: int) -> None:
    conf = pgdata / "postgresql.conf"
    if not conf.is_file():
        return
    text = conf.read_text(encoding="utf-8")
    if re.search(r"^port\s*=", text, flags=re.MULTILINE):
        text = re.sub(r"^port\s*=.*$", f"port = {port}", text, count=1, flags=re.MULTILINE)
    else:
        text += f"\nport = {port}\n"
    if "listen_addresses" not in text:
        text += "listen_addresses = '127.0.0.1'\n"
    conf.write_text(text, encoding="utf-8")


def _append_hba_rules(pgdata: Path) -> None:
    hba = pgdata / "pg_hba.conf"
    if not hba.is_file():
        return
    text = hba.read_text(encoding="utf-8")
    extra = "\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\n"
    if "127.0.0.1/32" not in text:
        hba.write_text(text + extra, encoding="utf-8")


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


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def _wait_for_port_close(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def _read_postmaster_pid(pgdata: Path) -> int | None:
    pid_file = pgdata / "postmaster.pid"
    if not pid_file.is_file():
        return None
    try:
        first_line = pid_file.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        return int(first_line.strip())
    except (OSError, ValueError, IndexError):
        return None


def _cleanup_stale_postmaster_pid(pgdata: Path) -> bool:
    """Return True when an existing postgres instance appears to be running."""
    pid_file = pgdata / "postmaster.pid"
    if not pid_file.is_file():
        return False
    pid = _read_postmaster_pid(pgdata)
    if pid is None:
        _log("removing invalid postmaster.pid")
        try:
            pid_file.unlink()
        except OSError:
            pass
        return False
    if _pid_alive(pid):
        _log(f"postgres already running pid={pid}")
        return True
    _log(f"removing stale postmaster.pid for dead pid={pid}")
    try:
        pid_file.unlink()
    except OSError:
        pass
    return False


def _ensure_postgres_database(
    install_dir: Path,
    pgdata: Path,
    pg_port: int,
    pg_host: str,
    psql: Path | None = None,
) -> None:
    if psql is None:
        psql = _postgres_bin(install_dir, "psql.exe")
    if not psql.is_file():
        return
    subprocess.run(
        [
            str(psql),
            "-h",
            pg_host,
            "-p",
            str(pg_port),
            "-U",
            "tender",
            "-d",
            "postgres",
            "-c",
            "CREATE DATABASE tender_agent;",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_postgres_env(install_dir, pgdata, pg_port),
        creationflags=_subprocess_flags(),
        timeout=15,
        check=False,
    )


def _postgres_log_has_admin_error(data_dir: Path) -> bool:
    path = data_dir / "postgres.log"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return "administrative permissions is not permitted" in text


def _postgres_log_shows_ready(data_dir: Path) -> bool:
    path = data_dir / "postgres.log"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    markers = (
        "database system is ready",
        "ready to accept connections",
        "准备接受连接",
        "accepting connections",
    )
    return any(marker in text for marker in markers)


def _postgres_log_has_no_socket_error(data_dir: Path) -> bool:
    path = data_dir / "postgres.log"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    markers = (
        "could not create any sockets",
        "没有为监听创建套接字",
        "no sockets could be created",
    )
    return any(marker in text for marker in markers)


def _postgres_log_has_bind_error(data_dir: Path) -> bool:
    path = data_dir / "postgres.log"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    markers = (
        "permission denied",
        "could not bind",
        "could not create listen socket",
        "无法绑定",
        "无法创建tcp/ip套接字",
        "无法创建监听套接字",
    )
    return any(marker in text for marker in markers)


def _postgres_is_ready(
    install_dir: Path,
    pgdata: Path,
    port: int,
    host: str,
    data_dir: Path,
) -> bool:
    if _pg_isready_once(install_dir, pgdata, port, host):
        return True
    if host == PG_TCP_HOST and _port_open(host, port):
        pid = _read_postmaster_pid(pgdata)
        if pid and _pid_alive(pid):
            return True
        if _postgres_log_shows_ready(data_dir):
            return True
    return False


def _start_postgres_via_pg_ctl(
    data_dir: Path,
    install_dir: Path,
    pgdata: Path,
    pg_port: int,
    pg_host: str,
    pg_ctl: Path,
    *,
    tcp: bool,
) -> None:
    log_path = data_dir / "postgres.log"
    mode = "tcp" if tcp else "pipe"
    if _is_windows_admin():
        _log("running as Windows administrator; starting postgres via pg_ctl to drop privileges")
    _log(f"starting postgres via pg_ctl ({mode}) host={pg_host} port={pg_port}")
    _update_postgresql_conf_listen(pgdata, tcp=tcp)
    _update_postgresql_conf_port(pgdata, pg_port)
    try:
        result = subprocess.run(
            [
                str(pg_ctl),
                "-D",
                str(pgdata),
                "-l",
                str(log_path),
                "-o",
                f"-p {pg_port}",
                "-w",
                "start",
            ],
            env=_postgres_env(install_dir, pgdata, pg_port),
            creationflags=_subprocess_flags(),
            timeout=45,
            # postgres.exe can inherit pg_ctl's captured pipe handles on Windows.
            # Avoid waiting forever for pipe EOF; server output is already in -l.
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        _log(f"pg_ctl start timed out after 45s on port {pg_port}")
        if _postgres_is_ready(install_dir, pgdata, pg_port, pg_host, data_dir):
            _log(f"postgres is ready on port {pg_port} despite pg_ctl timeout")
            return
        _append_log_tail(data_dir, "postgres.log")
        raise RuntimeError(f"postgres start timed out on port {pg_port}")

    if result.returncode == 0:
        _log(f"pg_ctl start succeeded ({mode}) port={pg_port}")
        return

    _log(f"pg_ctl start failed code={result.returncode} mode={mode} port={pg_port}")
    _append_log_tail(data_dir, "postgres.log")

    if _postgres_is_ready(install_dir, pgdata, pg_port, pg_host, data_dir):
        _log(f"postgres is ready on port {pg_port} despite pg_ctl exit {result.returncode}")
        return

    if _postgres_log_has_admin_error(data_dir):
        raise RuntimeError(_postgres_admin_error_message())
    if tcp and _postgres_log_has_bind_error(data_dir):
        raise RuntimeError(_postgres_bind_error_message(pg_port))
    raise RuntimeError(f"postgres start failed ({mode}) on port {pg_port} (code {result.returncode})")


def _postgres_running(
    install_dir: Path, pgdata: Path, host: str, port: int, data_dir: Path
) -> bool:
    return _postgres_is_ready(install_dir, pgdata, port, host, data_dir)


def _reuse_running_postgres(
    data_dir: Path,
    install_dir: Path,
    pgdata: Path,
    host: str,
    port: int,
    psql: Path | None = None,
    pid: int | None = None,
) -> bool:
    if not _postgres_running(install_dir, pgdata, host, port, data_dir):
        return False
    global _ACTIVE_PG_PORT, _ACTIVE_PG_HOST
    _ACTIVE_PG_PORT = port
    _ACTIVE_PG_HOST = host
    _ensure_postgres_database(install_dir, pgdata, port, host, psql)
    _save_pg_state(data_dir, pgdata, host, port, pid)
    _log(f"postgres ready on {host}:{port}")
    return True


def _init_postgres_data_dir(
    data_dir: Path, install_dir: Path, pgdata: Path, initdb: Path
) -> None:
    if (pgdata / "PG_VERSION").is_file():
        return
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
        env=_postgres_env(install_dir, pgdata, PG_PORT_DEFAULT),
        creationflags=_subprocess_flags(),
        **_subprocess_capture_kwargs(),
    )
    if result.returncode != 0:
        _log(f"initdb failed code={result.returncode}")
        if result.stdout.strip():
            _log(f"initdb stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            _log(f"initdb stderr: {result.stderr.strip()}")
        raise RuntimeError(f"postgres initdb failed (code {result.returncode})")

    _update_postgresql_conf_port(pgdata, PG_PORT_DEFAULT)
    _update_postgresql_conf_listen(pgdata, tcp=True)
    _append_hba_rules(pgdata)


def _try_start_postgres_tcp(
    data_dir: Path,
    install_dir: Path,
    pgdata: Path,
    pg_port: int,
    pg_ctl: Path,
    psql: Path | None,
) -> bool:
    if _reuse_running_postgres(
        data_dir, install_dir, pgdata, PG_TCP_HOST, pg_port, psql
    ):
        return True
    if not _can_bind_port(pg_port):
        _log(f"port {pg_port} is not bindable locally, trying next")
        return False
    try:
        _start_postgres_via_pg_ctl(
            data_dir,
            install_dir,
            pgdata,
            pg_port,
            PG_TCP_HOST,
            pg_ctl,
            tcp=True,
        )
        global _ACTIVE_PG_PORT, _ACTIVE_PG_HOST
        _ACTIVE_PG_PORT = pg_port
        _ACTIVE_PG_HOST = PG_TCP_HOST
        _ensure_postgres_database(install_dir, pgdata, pg_port, PG_TCP_HOST, psql)
        _save_pg_state(data_dir, pgdata, PG_TCP_HOST, pg_port)
        _log(f"postgres ready on tcp 127.0.0.1:{pg_port}")
        return True
    except RuntimeError as exc:
        _log(f"postgres tcp start failed on port {pg_port}: {exc}")
        if _reuse_running_postgres(
            data_dir, install_dir, pgdata, PG_TCP_HOST, pg_port, psql
        ):
            return True
        _stop_postgres(data_dir, install_dir, pg_port)
        return False


def _ensure_postgres(data_dir: Path, install_dir: Path) -> None:
    pgdata = data_dir / "pgdata"
    _log("postgres setup begin")
    _kill_stale_postgres_for_pgdata(data_dir)

    initdb = _postgres_bin(install_dir, "initdb.exe")
    pg_ctl = _postgres_bin(install_dir, "pg_ctl.exe")
    psql = _postgres_bin(install_dir, "psql.exe")
    if not initdb.is_file() or not pg_ctl.is_file():
        raise FileNotFoundError(f"未找到 PostgreSQL 工具：{_postgres_root(install_dir) / 'bin'}")

    candidates = _postgres_port_candidates(data_dir, pgdata)
    _log(f"postgres port candidates: {candidates}")

    saved = _read_pg_state(data_dir)
    if saved and _reuse_running_postgres(
        data_dir, install_dir, pgdata, saved[0], saved[1], psql
    ):
        return

    for port in candidates:
        if _reuse_running_postgres(
            data_dir, install_dir, pgdata, PG_TCP_HOST, port, psql
        ):
            return

    existing_pid = _read_postmaster_pid(pgdata)
    if existing_pid is not None and _pid_alive(existing_pid):
        for port in candidates:
            _log(f"existing postgres pid={existing_pid}; probing port {port}")
            if _reuse_running_postgres(
                data_dir,
                install_dir,
                pgdata,
                PG_TCP_HOST,
                port,
                psql,
                pid=existing_pid,
            ):
                return
        _log(f"postgres pid={existing_pid} alive but not accepting connections; stopping")
        _kill_process_tree(existing_pid)

    if _cleanup_stale_postmaster_pid(pgdata):
        for port in candidates:
            if _reuse_running_postgres(
                data_dir, install_dir, pgdata, PG_TCP_HOST, port, psql
            ):
                return

    _init_postgres_data_dir(data_dir, install_dir, pgdata, initdb)

    for pg_port in candidates:
        if _try_start_postgres_tcp(
            data_dir, install_dir, pgdata, pg_port, pg_ctl, psql
        ):
            return

    _log_windows_port_diagnostics()
    raise RuntimeError(_postgres_start_failed_message())


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


def _runtime_root(install_dir: Path) -> Path:
    return install_dir / "runtime"


def _runtime_python(install_dir: Path) -> Path:
    # Always use embed python.exe; Scripts/python.exe may be a pip stub pointing at CI paths.
    return _runtime_root(install_dir) / "python.exe"


def _runtime_env(install_dir: Path, data_dir: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    runtime = _runtime_root(install_dir)
    env["PYTHONHOME"] = str(runtime)
    runtime_bin = str(runtime)
    scripts = runtime / "Scripts"
    if scripts.is_dir():
        runtime_bin = str(scripts) + os.pathsep + runtime_bin
    env["PATH"] = runtime_bin + os.pathsep + env.get("PATH", "")
    env["TENDER_INSTALL_DIR"] = str(install_dir)
    if data_dir is not None:
        env["TENDER_DATA_DIR"] = str(data_dir)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if data_dir is not None:
        env["PYTHONPYCACHEPREFIX"] = str(data_dir / "pycache")
    return env


def _backend_log_path(data_dir: Path) -> Path:
    return data_dir / "backend.log"


def _verify_install_layout(install_dir: Path) -> None:
    checks: list[tuple[str, Path, bool]] = [
        ("runtime python", _runtime_python(install_dir), True),
        ("backend dir", install_dir / "backend", False),
        ("frontend index", install_dir / "frontend" / "dist" / "index.html", True),
        ("frontend assets", install_dir / "frontend" / "dist" / "assets", False),
        ("postgres initdb", _postgres_bin(install_dir, "initdb.exe"), True),
        ("postgres server", _postgres_bin(install_dir, "postgres.exe"), True),
        ("postgres pg_ctl", _postgres_bin(install_dir, "pg_ctl.exe"), True),
        ("minio", install_dir / "tools" / "minio.exe", True),
        ("aspose license", install_dir / "aspose" / "Aspose.License.txt", True),
    ]
    missing: list[str] = []
    for label, path, is_file in checks:
        ok = path.is_file() if is_file else path.is_dir()
        if not ok:
            missing.append(f"{label}: {path}")
    if missing:
        raise FileNotFoundError("安装目录不完整：\n" + "\n".join(missing))


def _verify_runtime_imports(install_dir: Path, data_dir: Path) -> None:
    python = _runtime_python(install_dir)
    env = _runtime_env(install_dir, data_dir)
    result = subprocess.run(
        [
            str(python),
            "-c",
            "import uvicorn, fastapi, sqlalchemy, psycopg2, minio, aspose.words; print('imports ok')",
        ],
        env=env,
        cwd=str(data_dir),
        creationflags=_subprocess_flags(),
        **_subprocess_capture_kwargs(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"嵌入式 Python 自检失败 (code {result.returncode}): {detail}")


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

    env = _runtime_env(install_dir, data_dir)
    env["TENDER_DESKTOP"] = "1"
    env["ASPOSE_LICENSE_PATH"] = str(install_dir / "aspose" / "Aspose.License.txt")
    if _ACTIVE_PG_PORT is not None:
        env["TENDER_PG_PORT"] = str(_ACTIVE_PG_PORT)
    env["TENDER_PG_HOST"] = _ACTIVE_PG_HOST

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


def _stop_postgres(
    data_dir: Path, install_dir: Path, port: int | None = None
) -> None:
    global _PG_PROC
    if _PG_PROC is not None and _PG_PROC.poll() is None:
        _log(f"stopping postgres pid={_PG_PROC.pid}")
        _kill_process_tree(_PG_PROC.pid)
        try:
            _PG_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        _PG_PROC = None
        return

    pg_ctl = _postgres_bin(install_dir, "pg_ctl.exe")
    pgdata = data_dir / "pgdata"
    if port is None:
        port = _read_pg_port_from_state(data_dir) or _ACTIVE_PG_PORT
    if pg_ctl.is_file() and pgdata.is_dir():
        subprocess.Popen(
            [str(pg_ctl), "-D", str(pgdata), "stop", "fast"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_postgres_env(install_dir, pgdata, port),
            creationflags=_subprocess_flags(),
        )
        _wait_for_port_close("127.0.0.1", port or PG_PORT_DEFAULT, 15)


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


def _run_check_only(install_dir: Path, data_dir: Path) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    _init_log(data_dir)
    _log(f"check-only install_dir={install_dir}")
    try:
        _verify_install_layout(install_dir)
        _log("install layout ok")
        _verify_runtime_imports(install_dir, data_dir)
        _log("runtime imports ok")
        _log("check-only passed")
        return 0
    except Exception as exc:
        _log(f"check-only failed: {exc}")
        print(str(exc), file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="TenderAgent backend sidecar")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="验证安装目录与嵌入式 Python，不启动服务",
    )
    args = parser.parse_args()

    install_dir = _install_dir()
    data_dir = _data_dir()
    if args.check_only:
        return _run_check_only(install_dir, data_dir)

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
