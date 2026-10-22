"""Desktop OnlyOffice bundle detection and sidecar config."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop"))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.config import get_settings
from app.onlyoffice_const import ONLYOFFICE_DESKTOP_PORT
from app.services.onlyoffice_runtime import (
    classify_onlyoffice,
    inspect_bundle,
    load_manifest,
    probe_health,
    runtime_status,
)
from app.services.system_check import _check_onlyoffice
from onlyoffice_sidecar import (
    ONLYOFFICE_SCHEMA_GRANTS_SQL,
    _ensure_database,
    _prepare_nginx,
    build_local_config,
    nginx_launch_command,
    rewrite_nginx_conf,
)


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _complete_bundle(root: Path) -> None:
    _write(root / "nginx" / "nginx.exe")
    _write(root / "server" / "DocService" / "sources" / "server.js", "/* doc */")
    _write(root / "server" / "FileConverter" / "sources" / "convertermaster.js", "/* conv */")
    _write(root / "server" / "schema" / "postgresql" / "createdb.sql", "select 1;")
    _write(root / "config" / "default.json", "{}")
    _write(root / "node" / "node.exe")
    _write(root / "rabbitmq" / "sbin" / "rabbitmq-server.bat", "@echo off")
    _write(root / "erlang" / "bin" / "erl.exe")
    manifest = {
        "nginx": "nginx/nginx.exe",
        "docservice": "server/DocService/sources/server.js",
        "converter": "server/FileConverter/sources/convertermaster.js",
        "node": "node/node.exe",
        "schema": "server/schema/postgresql/createdb.sql",
        "config_dir": "config",
        "rabbitmq": "rabbitmq/sbin/rabbitmq-server.bat",
        "erlang_home": "erlang",
    }
    (root / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_classify_optional_when_server_mode_disabled():
    assert classify_onlyoffice(
        {"enabled": False, "healthy": False, "required": False, "bundled": False}
    ) == "info"


def test_classify_error_when_desktop_bundle_missing():
    assert classify_onlyoffice(
        {"enabled": True, "healthy": False, "required": True, "bundled": False}
    ) == "error"


def test_classify_ok_when_sidecar_healthy():
    assert classify_onlyoffice(
        {"enabled": True, "healthy": True, "required": True, "bundled": True}
    ) == "ok"


def test_inspect_bundle_roundtrip(tmp_path: Path):
    _complete_bundle(tmp_path)
    ok, missing = inspect_bundle(tmp_path)
    assert ok, missing
    assert missing == []


def test_inspect_native_windows_bundle_without_node(tmp_path: Path):
    _write(tmp_path / "documentserver" / "nginx" / "nginx.exe")
    _write(tmp_path / "documentserver" / "server" / "DocService" / "docservice.exe")
    _write(tmp_path / "documentserver" / "server" / "FileConverter" / "converter.exe")
    _write(tmp_path / "documentserver" / "server" / "schema" / "postgresql" / "createdb.sql", "select 1;")
    _write(tmp_path / "documentserver" / "config" / "default.json", "{}")
    _write(tmp_path / "rabbitmq" / "sbin" / "rabbitmq-server.bat", "@echo off")
    _write(tmp_path / "erlang" / "bin" / "erl.exe")
    manifest = {
        "nginx": "documentserver/nginx/nginx.exe",
        "docservice": "documentserver/server/DocService/docservice.exe",
        "converter": "documentserver/server/FileConverter/converter.exe",
        "schema": "documentserver/server/schema/postgresql/createdb.sql",
        "config_dir": "documentserver/config",
        "rabbitmq": "rabbitmq/sbin/rabbitmq-server.bat",
        "erlang_home": "erlang",
    }
    (tmp_path / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    ok, missing = inspect_bundle(tmp_path)
    assert ok, missing


def test_rabbitmq_config_uses_distribution_port_range(tmp_path: Path):
    from app.onlyoffice_const import ONLYOFFICE_AMQP_PORT, ONLYOFFICE_DIST_PORT
    from onlyoffice_sidecar import _rabbitmq_env

    env = _rabbitmq_env(tmp_path / "erlang", tmp_path)
    text = (tmp_path / "onlyoffice" / "rabbitmq" / "rabbitmq.conf").read_text(encoding="utf-8")
    assert "distribution.listener.port =" not in text
    assert f"distribution.listener.port_range.min = {ONLYOFFICE_DIST_PORT}" in text
    assert f"distribution.listener.port_range.max = {ONLYOFFICE_DIST_PORT}" in text
    assert f"listeners.tcp.default = 127.0.0.1:{ONLYOFFICE_AMQP_PORT}" in text
    assert env["RABBITMQ_DIST_PORT"] == str(ONLYOFFICE_DIST_PORT)


def test_rabbitmq_boot_does_not_require_distribution(tmp_path: Path):
    """Prelaunch must not die on onlyoffice_prelaunch_*@localhost nodistribution.

    The local broker also must not need a working Erlang distribution node
    or epmd just to open the AMQP port.
    """
    from app.onlyoffice_const import ONLYOFFICE_DIST_PORT, ONLYOFFICE_RABBIT_NODENAME
    from onlyoffice_sidecar import (
        _rabbitmq_env,
        local_broker_requires_erlang_distribution,
        rabbitmq_launch_command,
    )

    erlang = tmp_path / "erlang"
    (erlang / "bin").mkdir(parents=True)
    env = _rabbitmq_env(erlang, tmp_path)
    boot = Path(env["ONLYOFFICE_RABBIT_BOOT_DIR"])
    prelaunch = (boot / "rabbit_prelaunch_dist.erl").read_text(encoding="utf-8")
    starter = (boot / "onlyoffice_rabbit_boot.erl").read_text(encoding="utf-8")
    command = rabbitmq_launch_command(erlang / "bin" / "erl.exe", boot)

    assert env["RABBITMQ_NODENAME"] == ONLYOFFICE_RABBIT_NODENAME
    assert not env["RABBITMQ_NODENAME"].endswith("@localhost")
    assert "ERL_EPMD_PORT" not in env
    assert "ERL_EPMD_ADDRESS" not in env
    assert "onlyoffice_rabbit_boot" in command
    assert "-sname" not in command
    assert "-name" not in command
    assert command[command.index("-erl_epmd_port") + 1] == str(ONLYOFFICE_DIST_PORT)
    assert "rabbitmq-server.bat" not in " ".join(command)
    assert "net_kernel:start" not in prelaunch
    assert "@localhost" not in prelaunch
    assert "shortnames" not in prelaunch
    assert "onlyoffice_prelaunch_" not in prelaunch
    assert starter.index("stick_mod(rabbit_prelaunch_dist)") < starter.index("rabbit:boot()")
    assert local_broker_requires_erlang_distribution(env, command, prelaunch) is False


def _locate_erl() -> Path | None:
    home = os.environ.get("ERLANG_HOME", "").strip()
    if home:
        for name in ("erl", "erl.exe"):
            candidate = Path(home) / "bin" / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    found = shutil.which("erl")
    if not found:
        return None
    candidate = Path(found)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


def _erlang_home_of(erl: Path) -> Path:
    home = os.environ.get("ERLANG_HOME", "").strip()
    if home and (Path(home) / "bin" / erl.name).exists():
        return Path(home)
    return erl.resolve().parent.parent


def _locate_rabbitmq_home() -> Path | None:
    for key in ("RABBITMQ_HOME", "ONLYOFFICE_RABBITMQ_HOME"):
        raw = os.environ.get(key, "").strip()
        if raw and (Path(raw) / "plugins").is_dir():
            return Path(raw)
    found = shutil.which("rabbitmq-server") or shutil.which("rabbitmq-server.bat")
    if not found:
        return None
    home = Path(found).resolve().parent.parent
    if (home / "plugins").is_dir():
        return home
    return None


def _write_dead_epmd(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        "echo 'epmd disabled for onlyoffice regression' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _erlang_home_with_dead_epmd(erlang_home: Path, dest: Path) -> Path:
    """Copy the emulator tree and replace epmd with a program that exits.

    The VM starts epmd from its own erts bin directory, not from PATH, so a
    PATH shim is not enough to make shortname distribution fail.
    """
    fake = dest / "erlang-no-epmd"
    fake.mkdir(parents=True)
    for name in ("lib", "releases", "usr", "misc"):
        source = erlang_home / name
        if source.exists():
            (fake / name).symlink_to(source, target_is_directory=True)
    erts_dirs = [path for path in erlang_home.glob("erts-*") if path.is_dir()]
    if not erts_dirs:
        raise RuntimeError(f"Erlang installation has no erts directory: {erlang_home}")
    for erts in erts_dirs:
        bin_dir = fake / erts.name / "bin"
        bin_dir.mkdir(parents=True)
        for item in (erts / "bin").iterdir():
            target = bin_dir / item.name
            if item.name == "epmd":
                _write_dead_epmd(target)
                continue
            try:
                os.link(item, target)
            except OSError:
                if item.is_symlink():
                    target.symlink_to(os.readlink(item))
                else:
                    shutil.copy2(item, target)
    bin_dir = fake / "bin"
    bin_dir.mkdir()
    for item in (erlang_home / "bin").iterdir():
        target = bin_dir / item.name
        if item.name == "epmd":
            _write_dead_epmd(target)
            continue
        if item.is_dir():
            target.symlink_to(item, target_is_directory=True)
        else:
            target.symlink_to(item)
    return fake


def _amqp_connection_start(port: int, timeout: float) -> bytes:
    deadline = time.time() + timeout
    last = "not attempted"
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
                sock.settimeout(3)
                sock.sendall(b"AMQP\x00\x00\x09\x01")
                data = b""
                while len(data) < 11:
                    chunk = sock.recv(128)
                    if not chunk:
                        break
                    data += chunk
                if len(data) >= 11 and data[0] == 1:
                    return data
                last = repr(data)
        except OSError as exc:
            last = str(exc)
        time.sleep(0.3)
    raise AssertionError(f"127.0.0.1:{port} did not return an AMQP frame ({last})")


def _stop_process_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def test_amqp_connection_start_when_epmd_is_unusable(tmp_path: Path):
    """Boot the sidecar broker with epmd unusable and read connection.start.

    The old prelaunch path dies with nodistribution before 25673 opens.
    Absent erl skips; a string compare is not treated as the handshake.
    """
    erl = _locate_erl()
    if erl is None:
        pytest.skip(
            "erl is not available; refusing to treat a string match as an AMQP handshake"
        )
    rabbit_home = _locate_rabbitmq_home()
    if rabbit_home is None:
        pytest.fail(
            f"erl is available at {erl} but RabbitMQ plugins were not found "
            "(set RABBITMQ_HOME); the AMQP handshake was not performed"
        )
    from app.onlyoffice_const import ONLYOFFICE_AMQP_PORT
    from onlyoffice_sidecar import (
        _compile_rabbit_boot,
        _erlang_tool,
        _rabbitmq_env,
        rabbitmq_launch_command,
    )

    real_home = _erlang_home_of(erl)
    fake_home = _erlang_home_with_dead_epmd(real_home, tmp_path)
    data = tmp_path / "data"
    env = _rabbitmq_env(fake_home, data, rabbit_home)
    env["ERL_ROOTDIR"] = str(fake_home)
    env["ERLANG_HOME"] = str(fake_home)
    boot = Path(env["ONLYOFFICE_RABBIT_BOOT_DIR"])
    _compile_rabbit_boot(real_home, boot, lambda _message: None)
    command = rabbitmq_launch_command(_erlang_tool(fake_home, "erl"), boot)
    log_path = tmp_path / "broker.log"
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        cwd=str(rabbit_home),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
    )
    try:
        frame = _amqp_connection_start(ONLYOFFICE_AMQP_PORT, 45)
    except AssertionError:
        log_file.flush()
        detail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise AssertionError(
            f"broker did not accept AMQP on 127.0.0.1:{ONLYOFFICE_AMQP_PORT}\n{detail}"
        )
    finally:
        log_file.flush()
        _stop_process_group(proc)
        log_file.close()
    # method frame, connection.start (class 10, method 10)
    assert frame[0] == 1
    assert int.from_bytes(frame[7:9], "big") == 10
    assert int.from_bytes(frame[9:11], "big") == 10
    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "nodistribution" not in text
    assert "onlyoffice_prelaunch_" not in text


def test_stock_prelaunch_localhost_requires_distribution():
    from onlyoffice_sidecar import local_broker_requires_erlang_distribution

    env = {
        "RABBITMQ_NODENAME": "onlyoffice@localhost",
        "ERL_EPMD_PORT": "25679",
        "ERL_EPMD_ADDRESS": "127.0.0.1",
    }
    command = ["cmd.exe", "/d", "/c", "rabbitmq-server.bat"]
    source = (
        'PrelaunchName = onlyoffice_prelaunch_56120@localhost,\n'
        "net_kernel:start([PrelaunchName, shortnames])."
    )
    assert local_broker_requires_erlang_distribution(env, command, source) is True


def test_windows_package_copies_rabbit_boot_shim():
    root = Path(__file__).resolve().parents[2]
    build = (root / "desktop" / "build.ps1").read_text(encoding="utf-8")
    verify = (root / "scripts" / "verify_desktop_runtime.ps1").read_text(encoding="utf-8")
    assert "onlyoffice_rabbit" in build
    assert "rabbit_prelaunch_dist.erl" in verify
    assert "onlyoffice_rabbit_boot.erl" in verify


def test_settings_labels_listening_onlyoffice_as_normal():
    page = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "SettingsPage.jsx"
    text = page.read_text(encoding="utf-8")
    assert "ok: '正常'" in text


def test_tender_database_create_is_its_own_statement(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TENDER_DATA_DIR", str(tmp_path))
    desktop = Path(__file__).resolve().parents[2] / "desktop"
    spec = importlib.util.spec_from_file_location(
        "backend_launcher_db_sql",
        desktop / "backend_launcher.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.TENDER_DB_CREATE_SQL == "CREATE DATABASE tender_agent"
    assert "DO" not in module.TENDER_DB_CREATE_SQL
    assert "CREATE DATABASE" not in module.TENDER_DB_EXISTS_SQL


class _PsqlResult:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _record_psql(calls: list[list[str]], answers: dict[str, str]):
    def _fake(_psql, _env, args, _log):
        calls.append(list(args))
        joined = " ".join(args)
        for needle, stdout in answers.items():
            if needle in joined:
                return _PsqlResult(stdout)
        return _PsqlResult("")

    return _fake


def test_onlyoffice_create_database_is_not_inside_do_block(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "onlyoffice_sidecar._psql",
        _record_psql(calls, {}),
    )
    psql = tmp_path / "psql.exe"
    psql.write_text("", encoding="utf-8")
    schema = tmp_path / "createdb.sql"
    schema.write_text("CREATE TABLE doc_changes();", encoding="utf-8")
    _ensure_database(psql, "127.0.0.1", 25432, {}, schema, lambda _message: None)
    create_sql = " ".join(" ".join(args) for args in calls if any("CREATE DATABASE" in part for part in args))
    assert "CREATE DATABASE onlyoffice OWNER onlyoffice" in create_sql
    assert "DO" not in create_sql
    assert "DO" not in ONLYOFFICE_SCHEMA_GRANTS_SQL
    import_args = next(args for args in calls if "-f" in args)
    user_flag = import_args[import_args.index("-U") + 1]
    assert user_flag == "onlyoffice"


def test_existing_onlyoffice_schema_still_grants_role(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "onlyoffice_sidecar._psql",
        _record_psql(
            calls,
            {
                "pg_roles": "1",
                "pg_database": "1",
                "to_regclass": "doc_changes",
            },
        ),
    )
    psql = tmp_path / "psql.exe"
    psql.write_text("", encoding="utf-8")
    _ensure_database(psql, "127.0.0.1", 25432, {}, tmp_path / "missing.sql", lambda _message: None)
    granted = [args for args in calls if any("GRANT ALL ON ALL TABLES" in part for part in args)]
    assert granted
    assert not any("-f" in args for args in calls)
    assert not any("CREATE DATABASE" in part for args in calls for part in args)


def test_load_manifest_accepts_powershell5_utf8_bom(tmp_path: Path):
    payload = {"nginx": "nginx/nginx.exe", "docservice": "server/DocService/docservice.exe"}
    (tmp_path / "bundle.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    manifest = load_manifest(tmp_path)
    assert manifest == payload


def test_inspect_bundle_reports_missing_manifest(tmp_path: Path):
    ok, missing = inspect_bundle(tmp_path)
    assert ok is False
    assert "bundle.json" in missing


def test_rewrite_nginx_listen_binds_loopback():
    source = "server {\n    listen 80;\n    listen 8000;\n}\n"
    rewritten = rewrite_nginx_conf(source, 18080, r"C:\Program Files\ONLYOFFICE\DocumentServer")
    assert "listen 127.0.0.1:18080;" in rewritten
    assert "listen 8000;" in rewritten


def test_rewrite_nginx_collapses_windows_dual_listen():
    """Community ds.conf listens on IPv4 and IPv6 port 80. Both must not become the same socket."""
    source = (
        "include includes/http-common.conf;\n"
        "server {\n"
        "  listen 0.0.0.0:80;\n"
        "  listen [::]:80 default_server;\n"
        "  include includes/ds-*.conf;\n"
        "}\n"
    )
    rewritten = rewrite_nginx_conf(source, 18080, r"D:\TenderAgent\tools\onlyoffice\documentserver")
    assert rewritten.count("listen ") == 1
    assert "listen 127.0.0.1:18080;" in rewritten
    assert "[::]" not in rewritten
    assert "listen 0.0.0.0" not in rewritten


def _windows_nginx_tree(root: Path) -> Path:
    nginx = root / "nginx"
    conf = nginx / "conf"
    conf.mkdir(parents=True)
    (conf / "nginx.conf").write_text(
        "worker_processes 1;\n"
        "events { worker_connections 1024; }\n"
        "http {\n"
        "    include mime.types;\n"
        "    include ds.conf;\n"
        "}\n",
        encoding="utf-8",
    )
    (conf / "ds.conf").write_text(
        "include includes/http-common.conf;\n"
        "server {\n"
        "  listen 0.0.0.0:80;\n"
        "  listen [::]:80 default_server;\n"
        "  include includes/ds-*.conf;\n"
        "}\n",
        encoding="utf-8",
    )
    (conf / "mime.types").write_text("types { }\n", encoding="utf-8")
    exe = nginx / "nginx.exe"
    exe.write_text("", encoding="utf-8")
    return exe


def test_prepare_nginx_uses_full_config_not_server_fragment(tmp_path: Path):
    exe = _windows_nginx_tree(tmp_path)
    target = _prepare_nginx(exe, 18080)
    assert target.name == "nginx.bundled.conf"
    main = target.read_text(encoding="utf-8")
    assert "events" in main
    assert "http {" in main
    assert "include ds.bundled.conf;" in main
    assert "include ds.conf;" not in main
    bundled = (exe.parent / "conf" / "ds.bundled.conf").read_text(encoding="utf-8")
    assert bundled.count("listen ") == 1
    assert "listen 127.0.0.1:18080;" in bundled
    assert "server {" in bundled
    assert not bundled.lstrip().startswith("worker_processes")
    command = nginx_launch_command(exe, target)
    assert command[-2:] == ["-c", "conf/nginx.bundled.conf"]
    assert (exe.parent / "logs").is_dir()
    assert (exe.parent / "temp" / "client_body_temp").is_dir()
    assert (exe.parent / "temp" / "proxy_temp").is_dir()


def test_prepare_nginx_wraps_fragment_when_main_config_missing(tmp_path: Path):
    nginx = tmp_path / "nginx"
    conf = nginx / "conf"
    conf.mkdir(parents=True)
    (conf / "ds.conf").write_text(
        "server {\n  listen 0.0.0.0:80;\n  listen [::]:80 default_server;\n}\n",
        encoding="utf-8",
    )
    exe = nginx / "nginx.exe"
    exe.write_text("", encoding="utf-8")
    target = _prepare_nginx(exe, 18080)
    text = target.read_text(encoding="utf-8")
    assert "events {" in text
    assert "http {" in text
    assert text.count("listen ") == 1
    assert "listen 127.0.0.1:18080;" in text
    assert nginx_launch_command(exe, target)[-1] == "conf/nginx.bundled.conf"


def test_rewrite_nginx_replaces_program_files_prefix():
    source = "root C:/Program Files/ONLYOFFICE/DocumentServer/var;\n"
    rewritten = rewrite_nginx_conf(source, 18080, r"D:\TenderAgent\tools\onlyoffice\documentserver")
    assert "D:/TenderAgent/tools/onlyoffice/documentserver/var" in rewritten


def test_local_config_points_at_desktop_postgres_and_private_ip():
    payload = build_local_config(pg_host="127.0.0.1", pg_port=25432, jwt_secret="secret")
    sql = payload["services"]["CoAuthoring"]["sql"]
    assert sql["dbPort"] == "25432"
    assert sql["dbName"] == "onlyoffice"
    assert payload["services"]["CoAuthoring"]["secret"]["inbox"]["string"] == "secret"
    assert payload["services"]["CoAuthoring"]["request-filtering-agent"]["allowPrivateIPAddress"] is True
    assert payload["rabbitmq"]["url"].endswith(":25673")


def test_system_check_desktop_missing_bundle_is_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TENDER_DESKTOP", "1")
    monkeypatch.setenv("ONLYOFFICE_ENABLED", "true")
    monkeypatch.setenv("ONLYOFFICE_DOCUMENT_SERVER_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ONLYOFFICE_BUNDLE_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        item = _check_onlyoffice()
    finally:
        get_settings.cache_clear()
    assert item["status"] == "error"
    assert item["status"] != "info"
    assert "缺少" in item["detail"]["message"]


def test_system_check_desktop_healthy_bundle_is_ok(tmp_path: Path, monkeypatch):
    _complete_bundle(tmp_path)
    monkeypatch.setenv("TENDER_DESKTOP", "1")
    monkeypatch.setenv("ONLYOFFICE_ENABLED", "true")
    monkeypatch.setenv("ONLYOFFICE_DOCUMENT_SERVER_URL", f"http://127.0.0.1:{ONLYOFFICE_DESKTOP_PORT}")
    monkeypatch.setenv("ONLYOFFICE_BUNDLE_DIR", str(tmp_path))
    monkeypatch.setattr("app.services.onlyoffice_runtime.probe_health", lambda *_args, **_kwargs: True)
    get_settings.cache_clear()
    try:
        item = _check_onlyoffice()
    finally:
        get_settings.cache_clear()
    assert item["status"] == "ok"
    assert item["detail"]["healthy"] is True
    assert "已就绪" in item["detail"]["message"]


def test_desktop_defaults_enable_bundled_server(monkeypatch):
    monkeypatch.setenv("TENDER_DESKTOP", "1")
    monkeypatch.delenv("ONLYOFFICE_ENABLED", raising=False)
    monkeypatch.delenv("ONLYOFFICE_DOCUMENT_SERVER_URL", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.onlyoffice_enabled is True
        assert settings.onlyoffice_document_server_url == f"http://127.0.0.1:{ONLYOFFICE_DESKTOP_PORT}"
        assert settings.onlyoffice_internal_url.startswith("http://127.0.0.1:")
    finally:
        get_settings.cache_clear()


def test_launcher_exposes_sidecar_under_embed_pth(tmp_path: Path, monkeypatch):
    """Embed python311._pth drops the script directory; the launcher must put it back."""
    monkeypatch.setenv("TENDER_DATA_DIR", str(tmp_path))
    desktop = Path(__file__).resolve().parents[2] / "desktop"
    launcher_path = desktop / "backend_launcher.py"
    isolated = [entry for entry in sys.path if entry not in ("", str(desktop))]
    monkeypatch.setattr(sys, "path", isolated)
    spec = importlib.util.spec_from_file_location("backend_launcher_embed_pth", launcher_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert str(desktop) in sys.path
    sidecar = importlib.import_module("onlyoffice_sidecar")
    assert sidecar.__file__
    assert Path(sidecar.__file__).resolve().parent == desktop


def test_probe_health_rejects_closed_port():
    assert probe_health("http://127.0.0.1:9", timeout=0.3) is False


def test_server_mode_stays_optional_without_desktop_flag(monkeypatch):
    monkeypatch.delenv("TENDER_DESKTOP", raising=False)
    monkeypatch.setenv("ONLYOFFICE_ENABLED", "false")
    monkeypatch.setenv("ONLYOFFICE_BUNDLE_DIR", str(Path("/tmp/onlyoffice-absent-bundle")))
    get_settings.cache_clear()
    try:
        payload = runtime_status()
    finally:
        get_settings.cache_clear()
    assert classify_onlyoffice(payload) == "info"
