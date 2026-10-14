"""Start the bundled OnlyOffice Document Server on localhost.

The Windows installer stages Community Edition files under tools/onlyoffice
(see scripts/ci/download-onlyoffice-windows.ps1). This module does not download
them. It writes local.json, reuses the app's PostgreSQL, and starts RabbitMQ,
FileConverter, DocService, and nginx bound to 127.0.0.1.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

DESKTOP_DIR = Path(__file__).resolve().parent
REPO_ROOT = DESKTOP_DIR.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.onlyoffice_const import (  # noqa: E402
    ONLYOFFICE_AMQP_PORT,
    ONLYOFFICE_DB_NAME,
    ONLYOFFICE_DB_PASSWORD,
    ONLYOFFICE_DB_USER,
    ONLYOFFICE_DESKTOP_JWT,
    ONLYOFFICE_DESKTOP_PORT,
    ONLYOFFICE_DIST_PORT,
    ONLYOFFICE_EPMD_PORT,
    ONLYOFFICE_STATE_FILE,
)
from app.services.onlyoffice_runtime import (  # noqa: E402
    bundle_root,
    inspect_bundle,
    probe_health,
    resolve_manifest_path,
)

LogFn = Callable[[str], None]
KillFn = Callable[[int], None]

_PROCS: list[subprocess.Popen] = []
# Port 80 on the IPv4 listen only. The Windows ds.conf has both
# `listen 0.0.0.0:80` and `listen [::]:80`. Rewriting both to
# 127.0.0.1:18080 makes nginx abort with "duplicate listen".
_IPV4_LISTEN_RE = re.compile(
    r"^([ \t]*)listen[ \t]+(?:(?:\*|0\.0\.0\.0|127\.0\.0\.1):)?80([ \t]+[^;]*)?;",
    re.MULTILINE,
)
_IPV6_LISTEN_RE = re.compile(
    r"^([ \t]*)listen[ \t]+\[::\]:80([ \t]+[^;]*)?;[ \t]*\r?\n?",
    re.MULTILINE,
)
_DS_INCLUDE_RE = re.compile(
    r"""^([ \t]*)include[ \t]+(['"]?)ds\.conf\2[ \t]*;""",
    re.MULTILINE,
)
_NGINX_RUNTIME_DIRS = (
    "logs",
    "temp/client_body_temp",
    "temp/proxy_temp",
    "temp/fastcgi_temp",
    "temp/uwsgi_temp",
    "temp/scgi_temp",
)
# Own statement, never a DO block. Tables created by the tender superuser
# stay invisible to DocService until this runs, including on later startups
# that find doc_changes already present.
ONLYOFFICE_SCHEMA_GRANTS_SQL = (
    "GRANT ALL ON SCHEMA public TO onlyoffice; "
    "GRANT ALL ON ALL TABLES IN SCHEMA public TO onlyoffice; "
    "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO onlyoffice"
)
_INSTALL_PREFIXES = (
    "C:/Program Files/ONLYOFFICE/DocumentServer",
    "C:/Program Files (x86)/ONLYOFFICE/DocumentServer",
    r"C:\Program Files\ONLYOFFICE\DocumentServer",
    r"C:\Program Files (x86)\ONLYOFFICE\DocumentServer",
)


def bundle_problem(install_dir: Path) -> str | None:
    root = bundle_root(install_dir)
    ok, missing = inspect_bundle(root)
    if ok:
        return None
    detail = "、".join(missing) if missing else BUNDLE_MANIFEST_HINT
    return f"安装包缺少 OnlyOffice 组件：{root}（{detail}）"


BUNDLE_MANIFEST_HINT = "bundle.json"


def build_local_config(
    *,
    pg_host: str,
    pg_port: int,
    jwt_secret: str,
    amqp_port: int = ONLYOFFICE_AMQP_PORT,
) -> dict[str, Any]:
    host = "127.0.0.1" if pg_host in ("", ".") else pg_host
    secret = jwt_secret or ONLYOFFICE_DESKTOP_JWT
    return {
        "services": {
            "CoAuthoring": {
                "sql": {
                    "type": "postgres",
                    "dbHost": host,
                    "dbPort": str(pg_port),
                    "dbName": ONLYOFFICE_DB_NAME,
                    "dbUser": ONLYOFFICE_DB_USER,
                    "dbPass": ONLYOFFICE_DB_PASSWORD,
                },
                "token": {
                    "enable": {
                        "browser": True,
                        "request": {"inbox": True, "outbox": True},
                    }
                },
                "secret": {
                    "browser": {"string": secret},
                    "inbox": {"string": secret},
                    "outbox": {"string": secret},
                    "session": {"string": secret},
                },
                "request-filtering-agent": {
                    "allowPrivateIPAddress": True,
                    "allowMetaIPAddress": True,
                },
            }
        },
        "rabbitmq": {"url": f"amqp://guest:guest@127.0.0.1:{amqp_port}"},
        "queue": {"type": "rabbitmq"},
    }


def _rewrite_listen_directives(text: str, port: int) -> str:
    """Bind Document Server to loopback without leaving two identical listens."""
    rewritten = _IPV4_LISTEN_RE.sub(
        lambda match: f"{match.group(1)}listen 127.0.0.1:{port}{match.group(2) or ''};",
        text,
    )
    if rewritten != text:
        return _IPV6_LISTEN_RE.sub("", rewritten)
    return _IPV6_LISTEN_RE.sub(
        lambda match: f"{match.group(1)}listen 127.0.0.1:{port}{match.group(2) or ''};\n",
        text,
    )


def rewrite_nginx_conf(conf: str, port: int, install_prefix: str | None = None) -> str:
    text = conf
    if install_prefix:
        slash = install_prefix.replace("\\", "/").rstrip("/")
        native = install_prefix.rstrip("\\/")
        for needle in _INSTALL_PREFIXES:
            if "/" in needle:
                text = text.replace(needle, slash)
            else:
                text = text.replace(needle, native)
    return _rewrite_listen_directives(text, port)


def jwt_secret() -> str:
    return os.environ.get("ONLYOFFICE_JWT_SECRET") or ONLYOFFICE_DESKTOP_JWT


def backend_env(backend_port: int) -> dict[str, str]:
    return {
        "ONLYOFFICE_ENABLED": "true",
        "ONLYOFFICE_DOCUMENT_SERVER_URL": f"http://127.0.0.1:{ONLYOFFICE_DESKTOP_PORT}",
        "ONLYOFFICE_JWT_SECRET": jwt_secret(),
        "ONLYOFFICE_INTERNAL_URL": f"http://127.0.0.1:{backend_port}",
    }


def _creationflags() -> int:
    if sys.platform != "win32":
        return 0
    return 0x08000000  # CREATE_NO_WINDOW


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _wait_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return False


def _spawn(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    log_file,
) -> subprocess.Popen:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=_creationflags(),
    )
    _PROCS.append(proc)
    return proc


def _service_command(entry: Path, node: Path | None) -> list[str]:
    if entry.suffix.lower() == ".js":
        if node is None:
            raise FileNotFoundError(f"启动 {entry.name} 需要 node.exe")
        return [str(node), str(entry)]
    if entry.suffix.lower() == ".bat":
        return ["cmd.exe", "/d", "/c", str(entry)]
    return [str(entry)]


def _write_local_json(config_dir: Path, payload: dict[str, Any]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "local.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def nginx_launch_command(nginx_exe: Path, conf: Path) -> list[str]:
    """Launch nginx with a full main config. ds.conf is only an http include."""
    return [str(nginx_exe), "-p", str(nginx_exe.parent), "-c", f"conf/{conf.name}"]


def _is_nginx_main_config(text: str) -> bool:
    return bool(re.search(r"(?m)^[ \t]*(?:events|http)[ \t]*\{", text))


def _wrap_server_fragment(fragment: str) -> str:
    body = fragment.strip("\r\n")
    indented = "\n".join(("    " + line) if line else line for line in body.splitlines())
    return (
        "worker_processes 1;\n"
        "error_log logs/error.log;\n"
        "pid logs/nginx.pid;\n"
        "events {\n"
        "    worker_connections 1024;\n"
        "}\n"
        "http {\n"
        "    include mime.types;\n"
        "    default_type application/octet-stream;\n"
        f"{indented}\n"
        "}\n"
    )


def _ensure_nginx_runtime_dirs(nginx_home: Path) -> None:
    # The installer creates these with [Dirs]; an innounp extract does not.
    # nginx exits before binding when logs/ or temp/ is missing.
    for relative in _NGINX_RUNTIME_DIRS:
        (nginx_home / relative).mkdir(parents=True, exist_ok=True)


def _prepare_nginx(nginx_exe: Path, port: int) -> Path:
    nginx_home = nginx_exe.parent
    conf_dir = nginx_home / "conf"
    _ensure_nginx_runtime_dirs(nginx_home)
    prefix = str(nginx_home.parent)
    ds_source = conf_dir / "ds.conf"
    main_source = conf_dir / "nginx.conf"
    if ds_source.is_file() and main_source.is_file():
        # Windows ships nginx.conf (events/http) which includes ds.conf.
        # ds.conf is a server{} fragment. `nginx -c ds.conf` exits at once,
        # so 18080 never opens and the desktop self-check stays 异常.
        bundled_ds = conf_dir / "ds.bundled.conf"
        bundled_ds.write_text(
            rewrite_nginx_conf(
                ds_source.read_text(encoding="utf-8", errors="replace"),
                port,
                prefix,
            ),
            encoding="utf-8",
        )
        main_text = rewrite_nginx_conf(
            main_source.read_text(encoding="utf-8", errors="replace"),
            port,
            prefix,
        )
        main_text = _DS_INCLUDE_RE.sub(
            lambda match: (
                f"{match.group(1)}include {match.group(2)}ds.bundled.conf{match.group(2)};"
            ),
            main_text,
        )
        bundled_main = conf_dir / "nginx.bundled.conf"
        bundled_main.write_text(main_text, encoding="utf-8")
        return bundled_main

    source = ds_source if ds_source.is_file() else None
    if source is None and conf_dir.is_dir():
        matches = [
            path
            for path in sorted(conf_dir.glob("*.conf"))
            if not path.name.endswith(".bundled.conf")
        ]
        source = matches[0] if matches else None
    if source is None or not source.is_file():
        raise FileNotFoundError(f"未找到 OnlyOffice nginx 配置：{conf_dir}")
    rewritten = rewrite_nginx_conf(
        source.read_text(encoding="utf-8", errors="replace"),
        port,
        prefix,
    )
    if not _is_nginx_main_config(rewritten):
        rewritten = _wrap_server_fragment(rewritten)
    target = conf_dir / "nginx.bundled.conf"
    target.write_text(rewritten, encoding="utf-8")
    return target


def _psql(
    psql: Path,
    pg_env: dict[str, str],
    args: list[str],
    log: LogFn,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(psql), *args],
        env=pg_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creationflags(),
        timeout=30,
        check=False,
    )


def _ensure_database(
    psql: Path | None,
    pg_host: str,
    pg_port: int,
    pg_env: dict[str, str],
    schema: Path,
    log: LogFn,
) -> None:
    if psql is None or not psql.is_file():
        log("onlyoffice: psql 不存在，跳过数据库初始化")
        return
    host = "127.0.0.1" if pg_host in ("", ".") else pg_host
    base = ["-h", host, "-p", str(pg_port), "-U", "tender"]
    # CREATE ROLE cannot run inside a DO block (it is a transaction).
    role_exists = _psql(
        psql,
        pg_env,
        [*base, "-d", "postgres", "-tAc", "SELECT 1 FROM pg_roles WHERE rolname = 'onlyoffice'"],
        log,
    )
    if "1" not in (role_exists.stdout or ""):
        role = _psql(
            psql,
            pg_env,
            [*base, "-d", "postgres", "-c", "CREATE ROLE onlyoffice LOGIN PASSWORD 'onlyoffice'"],
            log,
        )
        if role.returncode != 0:
            log(f"onlyoffice: create role failed: {(role.stderr or role.stdout).strip()}")
    exists = _psql(
        psql,
        pg_env,
        [*base, "-d", "postgres", "-tAc", "SELECT 1 FROM pg_database WHERE datname = 'onlyoffice'"],
        log,
    )
    if "1" not in (exists.stdout or ""):
        created = _psql(
            psql,
            pg_env,
            [*base, "-d", "postgres", "-c", "CREATE DATABASE onlyoffice OWNER onlyoffice;"],
            log,
        )
        if created.returncode != 0:
            log(f"onlyoffice: create database failed: {(created.stderr or created.stdout).strip()}")
            return
    granted = _psql(
        psql,
        pg_env,
        [*base, "-d", ONLYOFFICE_DB_NAME, "-c", ONLYOFFICE_SCHEMA_GRANTS_SQL],
        log,
    )
    if granted.returncode != 0:
        log(f"onlyoffice: grant failed: {(granted.stderr or granted.stdout).strip()[:500]}")
    table = _psql(
        psql,
        pg_env,
        [*base, "-d", ONLYOFFICE_DB_NAME, "-tAc", "SELECT to_regclass('public.doc_changes')"],
        log,
    )
    if (table.stdout or "").strip() not in ("", "null"):
        log("onlyoffice: schema already present")
        return
    if not schema.is_file():
        log(f"onlyoffice: schema missing: {schema}")
        return
    # Import as the onlyoffice role so DocService owns the tables. Trust auth
    # on the bundled cluster allows this without a password.
    applied = _psql(
        psql,
        pg_env,
        [
            "-h",
            host,
            "-p",
            str(pg_port),
            "-U",
            ONLYOFFICE_DB_USER,
            "-d",
            ONLYOFFICE_DB_NAME,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(schema),
        ],
        log,
    )
    if applied.returncode != 0:
        log(
            "onlyoffice: schema import as onlyoffice failed, retrying as superuser: "
            f"{(applied.stderr or applied.stdout).strip()[:500]}"
        )
        applied = _psql(
            psql,
            pg_env,
            [*base, "-d", ONLYOFFICE_DB_NAME, "-v", "ON_ERROR_STOP=1", "-f", str(schema)],
            log,
        )
        if applied.returncode != 0:
            log(f"onlyoffice: schema import failed: {(applied.stderr or applied.stdout).strip()[:500]}")
            return
        granted_again = _psql(
            psql,
            pg_env,
            [*base, "-d", ONLYOFFICE_DB_NAME, "-c", ONLYOFFICE_SCHEMA_GRANTS_SQL],
            log,
        )
        if granted_again.returncode != 0:
            log(
                "onlyoffice: grant after import failed: "
                f"{(granted_again.stderr or granted_again.stdout).strip()[:500]}"
            )
            return
    log("onlyoffice: schema imported")


def _rabbitmq_env(erlang_home: Path, data_dir: Path) -> dict[str, str]:
    base = data_dir / "onlyoffice" / "rabbitmq"
    for name in ("", "log", "mnesia"):
        (base / name).mkdir(parents=True, exist_ok=True)
    conf = base / "rabbitmq.conf"
    conf.write_text(
        "\n".join(
            [
                f"listeners.tcp.default = 127.0.0.1:{ONLYOFFICE_AMQP_PORT}",
                # RabbitMQ 3.13 has no distribution.listener.port. A single
                # dist port is a min=max range; the unknown key aborts boot.
                f"distribution.listener.port_range.min = {ONLYOFFICE_DIST_PORT}",
                f"distribution.listener.port_range.max = {ONLYOFFICE_DIST_PORT}",
                "loopback_users.guest = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["ERLANG_HOME"] = str(erlang_home)
    env["RABBITMQ_BASE"] = str(base)
    env["RABBITMQ_CONFIG_FILE"] = str(base / "rabbitmq")
    env["RABBITMQ_LOG_BASE"] = str(base / "log")
    env["RABBITMQ_MNESIA_BASE"] = str(base / "mnesia")
    env["RABBITMQ_NODE_PORT"] = str(ONLYOFFICE_AMQP_PORT)
    env["RABBITMQ_DIST_PORT"] = str(ONLYOFFICE_DIST_PORT)
    env["RABBITMQ_NODENAME"] = "onlyoffice@localhost"
    env["ERL_EPMD_PORT"] = str(ONLYOFFICE_EPMD_PORT)
    env["ERL_EPMD_ADDRESS"] = "127.0.0.1"
    path = str(erlang_home / "bin") + os.pathsep + env.get("PATH", "")
    env["PATH"] = path
    return env


def _node_env(config_dir: Path, node: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    env["NODE_ENV"] = "production-windows"
    env["NODE_CONFIG_DIR"] = str(config_dir)
    env["NODE_DISABLE_COLORS"] = "1"
    if node is not None:
        env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    return env


def _write_state(data_dir: Path, payload: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / ONLYOFFICE_STATE_FILE).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _public_url() -> str:
    return f"http://127.0.0.1:{ONLYOFFICE_DESKTOP_PORT}"


def _read_state(data_dir: Path) -> dict[str, Any]:
    path = data_dir / ONLYOFFICE_STATE_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _stop_tracked() -> None:
    for proc in list(_PROCS):
        if proc.poll() is None and proc.pid:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_creationflags(),
                    check=False,
                )
            else:
                proc.terminate()
    _PROCS.clear()


def ensure_onlyoffice(
    install_dir: Path,
    data_dir: Path,
    *,
    pg_host: str,
    pg_port: int,
    psql: Path | None,
    pg_env: dict[str, str],
    log: LogFn,
) -> None:
    """Start the sidecar when the bundle is present. Never raises for a missing bundle."""
    root = bundle_root(install_dir)
    ok, missing = inspect_bundle(root)
    if not ok:
        detail = "、".join(missing)
        log(f"onlyoffice bundle missing ({detail})")
        _write_state(
            data_dir,
            {"status": "missing", "port": ONLYOFFICE_DESKTOP_PORT, "missing": missing},
        )
        return

    if probe_health(_public_url(), timeout=1.0):
        log(f"onlyoffice already healthy on {ONLYOFFICE_DESKTOP_PORT}")
        previous = _read_state(data_dir)
        payload: dict[str, Any] = {
            "status": "ok",
            "port": ONLYOFFICE_DESKTOP_PORT,
            "reused": True,
        }
        if isinstance(previous.get("pids"), dict):
            payload["pids"] = previous["pids"]
        if previous.get("pid"):
            payload["pid"] = previous["pid"]
        _write_state(data_dir, payload)
        return

    log_path = data_dir / "onlyoffice.log"
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n--- onlyoffice start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.flush()
    pids: dict[str, int] = {}
    try:
        config_dir = resolve_manifest_path(root, "config_dir")
        schema = resolve_manifest_path(root, "schema")
        nginx_exe = resolve_manifest_path(root, "nginx")
        docservice = resolve_manifest_path(root, "docservice")
        converter = resolve_manifest_path(root, "converter")
        rabbit = resolve_manifest_path(root, "rabbitmq")
        erlang_home = resolve_manifest_path(root, "erlang_home")
        node = resolve_manifest_path(root, "node")
        if not all([config_dir, schema, nginx_exe, docservice, converter, rabbit, erlang_home]):
            raise FileNotFoundError("OnlyOffice bundle.json 路径无效")

        _write_local_json(
            config_dir,
            build_local_config(pg_host=pg_host, pg_port=pg_port, jwt_secret=jwt_secret()),
        )
        _ensure_database(psql, pg_host, pg_port, pg_env, schema, log)
        nginx_conf = _prepare_nginx(nginx_exe, ONLYOFFICE_DESKTOP_PORT)

        log("starting onlyoffice rabbitmq")
        rabbit_proc = _spawn(
            ["cmd.exe", "/d", "/c", str(rabbit)],
            rabbit.parent,
            _rabbitmq_env(erlang_home, data_dir),
            log_file,
        )
        pids["rabbitmq"] = rabbit_proc.pid
        if not _wait_port(ONLYOFFICE_AMQP_PORT, 60):
            raise RuntimeError(f"RabbitMQ 未在 127.0.0.1:{ONLYOFFICE_AMQP_PORT} 就绪")

        node_env = _node_env(config_dir, node)
        log("starting onlyoffice converter")
        converter_proc = _spawn(
            _service_command(converter, node),
            converter.parent,
            node_env,
            log_file,
        )
        pids["converter"] = converter_proc.pid
        log("starting onlyoffice docservice")
        doc_proc = _spawn(
            _service_command(docservice, node),
            docservice.parent,
            node_env,
            log_file,
        )
        pids["docservice"] = doc_proc.pid
        log("starting onlyoffice nginx")
        nginx_proc = _spawn(
            nginx_launch_command(nginx_exe, nginx_conf),
            nginx_exe.parent,
            os.environ.copy(),
            log_file,
        )
        pids["nginx"] = nginx_proc.pid

        deadline = time.time() + 90
        while time.time() < deadline:
            if nginx_proc.poll() is not None or doc_proc.poll() is not None:
                raise RuntimeError("OnlyOffice 进程提前退出，详见 onlyoffice.log")
            if probe_health(_public_url(), timeout=1.0):
                log(f"onlyoffice ready on {ONLYOFFICE_DESKTOP_PORT}")
                _write_state(
                    data_dir,
                    {
                        "status": "ok",
                        "port": ONLYOFFICE_DESKTOP_PORT,
                        "pid": nginx_proc.pid,
                        "pids": pids,
                    },
                )
                return
            time.sleep(0.5)
        raise RuntimeError("OnlyOffice /healthcheck 超时")
    except Exception as exc:
        log(f"onlyoffice start failed: {exc}")
        _stop_tracked()
        _write_state(
            data_dir,
            {
                "status": "unhealthy",
                "port": ONLYOFFICE_DESKTOP_PORT,
                "message": str(exc),
            },
        )
    finally:
        log_file.close()


def stop_onlyoffice(data_dir: Path, kill_tree: KillFn, log: LogFn | None = None) -> None:
    seen: set[int] = set()
    for proc in list(_PROCS):
        if proc.poll() is None and proc.pid:
            seen.add(proc.pid)
            kill_tree(proc.pid)
    _PROCS.clear()
    state_path = data_dir / ONLYOFFICE_STATE_FILE
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        pids = state.get("pids") if isinstance(state, dict) else None
        if isinstance(pids, dict):
            for pid in pids.values():
                try:
                    number = int(pid)
                except (TypeError, ValueError):
                    continue
                if number > 0 and number not in seen:
                    kill_tree(number)
        elif isinstance(state, dict) and state.get("pid"):
            try:
                number = int(state["pid"])
            except (TypeError, ValueError):
                number = 0
            if number > 0 and number not in seen:
                kill_tree(number)
    if log:
        log("onlyoffice stopped")
    state_path = data_dir / ONLYOFFICE_STATE_FILE
    if state_path.is_file():
        try:
            state_path.unlink()
        except OSError:
            pass
