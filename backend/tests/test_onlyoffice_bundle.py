"""Desktop OnlyOffice bundle detection and sidecar config."""
from __future__ import annotations

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
    probe_health,
    runtime_status,
)
from app.services.system_check import _check_onlyoffice
from onlyoffice_sidecar import build_local_config, rewrite_nginx_conf


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
    import json

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
    import json

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


def test_inspect_bundle_reports_missing_manifest(tmp_path: Path):
    ok, missing = inspect_bundle(tmp_path)
    assert ok is False
    assert "bundle.json" in missing


def test_rewrite_nginx_listen_binds_loopback():
    source = "server {\n    listen 80;\n    listen 8000;\n}\n"
    rewritten = rewrite_nginx_conf(source, 18080, r"C:\Program Files\ONLYOFFICE\DocumentServer")
    assert "listen 127.0.0.1:18080;" in rewritten
    assert "listen 8000;" in rewritten


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
