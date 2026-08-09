"""Aspose.Words 运行时：授权加载与可用性检查。"""
from __future__ import annotations

import os
from functools import lru_cache

_license_ready = False


@lru_cache
def license_path() -> str:
    env_path = os.environ.get("ASPOSE_LICENSE_PATH", "").strip()
    if env_path:
        return env_path
    from app.config import get_settings

    return get_settings().aspose_license_path


def _load_aspose():
    try:
        import aspose.words as aw
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "无法加载 Aspose.Words 运行时。请确认已安装 Visual C++ 2015-2022 运行库，"
            f"并重新安装本程序。原始错误: {exc}"
        ) from exc
    return aw


def ensure_license(path: str | None = None) -> None:
    global _license_ready
    if _license_ready:
        return
    lic_path = path or license_path()
    if not lic_path or not os.path.isfile(lic_path):
        raise RuntimeError(
            f"Aspose 授权文件不存在: {lic_path}。"
            "请重新安装桌面版，或联系技术支持。"
        )
    aw = _load_aspose()
    aw.License().set_license(lic_path)
    _license_ready = True


def smoke_test() -> dict:
    """生成最小 docx，用于部署后自检。"""
    ensure_license()
    aw = _load_aspose()
    doc = aw.Document()
    builder = aw.DocumentBuilder(doc)
    builder.writeln("Aspose.Words smoke test OK")
    return {"ok": True, "engine": "aspose.words", "license": license_path()}
