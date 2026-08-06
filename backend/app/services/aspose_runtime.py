"""Aspose.Words 运行时：授权加载与可用性检查。"""
from __future__ import annotations

import os
from functools import lru_cache

import aspose.words as aw

_license_ready = False


@lru_cache
def license_path() -> str:
    env_path = os.environ.get("ASPOSE_LICENSE_PATH", "").strip()
    if env_path:
        return env_path
    from app.config import get_settings

    return get_settings().aspose_license_path


def ensure_license(path: str | None = None) -> None:
    global _license_ready
    if _license_ready:
        return
    lic_path = path or license_path()
    if not lic_path or not os.path.isfile(lic_path):
        raise RuntimeError(
            f"Aspose 授权文件不存在: {lic_path}。"
            "请将 Aspose.License.txt 挂载到容器并设置 ASPOSE_LICENSE_PATH。"
        )
    aw.License().set_license(lic_path)
    _license_ready = True


def smoke_test() -> dict:
    """生成最小 docx，用于部署后自检。"""
    ensure_license()
    doc = aw.Document()
    builder = aw.DocumentBuilder(doc)
    builder.writeln("Aspose.Words smoke test OK")
    return {"ok": True, "engine": "aspose.words", "license": license_path()}
