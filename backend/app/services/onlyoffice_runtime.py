"""Detect the desktop OnlyOffice bundle and whether its sidecar is healthy."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.config import INSTALL_DIR, get_settings
from app.onlyoffice_const import ONLYOFFICE_DESKTOP_PORT

BUNDLE_MANIFEST = "bundle.json"
_FILE_KEYS = ("nginx", "docservice", "converter", "schema", "rabbitmq")
_DIR_KEYS = ("config_dir", "erlang_home")


def desktop_required() -> bool:
    value = os.environ.get("TENDER_DESKTOP", "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def bundle_root(install_dir: Path | None = None) -> Path:
    override = os.environ.get("ONLYOFFICE_BUNDLE_DIR", "").strip()
    if override:
        return Path(override)
    base = Path(install_dir) if install_dir is not None else INSTALL_DIR
    return base / "tools" / "onlyoffice"


def load_manifest(root: Path) -> dict[str, Any] | None:
    data, _problem = _read_manifest(root)
    return data


def _read_manifest(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (manifest, problem). problem is None when the file parses."""
    path = root / BUNDLE_MANIFEST
    if not path.is_file():
        return None, "missing"
    try:
        # Windows PowerShell 5.1 Set-Content -Encoding UTF8 writes a BOM.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "not an object"
    return data, None


def _needs_node(manifest: dict[str, Any]) -> bool:
    for key in ("docservice", "converter"):
        rel = str(manifest.get(key) or "")
        if rel.lower().endswith(".js"):
            return True
    return False


def inspect_bundle(root: Path | None = None) -> tuple[bool, list[str]]:
    """Return (complete, missing_keys). missing_keys is empty when complete."""
    bundle = root if root is not None else bundle_root()
    manifest, problem = _read_manifest(bundle)
    if manifest is None:
        if problem and problem != "missing":
            return False, [f"{BUNDLE_MANIFEST}: {problem}"]
        return False, [BUNDLE_MANIFEST]
    missing: list[str] = []
    for key in _FILE_KEYS:
        rel = manifest.get(key)
        if not rel or not (bundle / str(rel)).is_file():
            missing.append(key)
    for key in _DIR_KEYS:
        rel = manifest.get(key)
        if not rel or not (bundle / str(rel)).is_dir():
            missing.append(key)
    if _needs_node(manifest):
        rel = manifest.get("node")
        if not rel or not (bundle / str(rel)).is_file():
            missing.append("node")
    return len(missing) == 0, missing


def resolve_manifest_path(root: Path, key: str) -> Path | None:
    manifest = load_manifest(root)
    if not manifest:
        return None
    rel = manifest.get(key)
    if not rel:
        return None
    path = root / str(rel)
    return path if path.exists() else None


def probe_health(base_url: str, timeout: float = 1.5) -> bool:
    if not base_url:
        return False
    url = base_url.rstrip("/") + "/healthcheck"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return False
            body = resp.read(64).decode("utf-8", errors="replace").strip().lower()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    return body.startswith("true")


def classify_onlyoffice(payload: dict[str, Any]) -> str:
    """Map runtime facts to the settings badge: ok / error / info.

    Desktop (and any install that actually shipped the bundle) treats OnlyOffice
    as required. A missing or stopped sidecar is an error, not an optional info.
    Server/docker installs keep the external Document Server optional.
    """
    ready = bool(payload.get("healthy") and payload.get("enabled"))
    if payload.get("required") or payload.get("bundled"):
        return "ok" if ready else "error"
    return "ok" if payload.get("enabled") else "info"


def _message(payload: dict[str, Any]) -> str:
    url = payload.get("document_server_url") or f"http://127.0.0.1:{ONLYOFFICE_DESKTOP_PORT}"
    missing = payload.get("missing") or []
    if payload.get("healthy") and payload.get("enabled"):
        if payload.get("bundled") or payload.get("required"):
            return f"内置 Document Server 已就绪（{url}）"
        return f"Document Server 已连接（{url}）"
    if payload.get("required") or payload.get("bundled"):
        if not payload.get("bundled"):
            text = "安装包缺少 OnlyOffice 组件（tools/onlyoffice）。Word 编辑不可用。"
            if missing:
                text += " 缺少：" + "、".join(str(item) for item in missing[:6])
            return text
        if not payload.get("enabled"):
            return "桌面端需要启用内置 OnlyOffice，但 ONLYOFFICE_ENABLED 被关闭。"
        return f"内置 OnlyOffice 未响应（{url}）。请查看数据目录中的 onlyoffice.log。"
    if payload.get("enabled"):
        return "已配置外部 Document Server"
    return "未启用"


def runtime_status(install_dir: Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    root = bundle_root(install_dir)
    bundled, missing = inspect_bundle(root)
    required = desktop_required()
    configured_url = (settings.onlyoffice_document_server_url or "").rstrip("/")
    enabled = bool(settings.onlyoffice_enabled and configured_url)
    visible_url = configured_url if (enabled or required or bundled) else ""
    healthy = False
    if (required or bundled) and visible_url:
        healthy = probe_health(visible_url)
    payload: dict[str, Any] = {
        "enabled": enabled,
        "healthy": healthy,
        "bundled": bundled,
        "required": required,
        "document_server_url": visible_url,
        "jwt_enabled": bool(settings.onlyoffice_jwt_secret),
        "port": ONLYOFFICE_DESKTOP_PORT,
        "bundle_dir": str(root),
        "missing": missing,
    }
    payload["message"] = _message(payload)
    return payload
