"""Desktop OnlyOffice bundle detection and sidecar config."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

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
