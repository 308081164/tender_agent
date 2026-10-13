"""Aspose.Words 运行时：授权加载与可用性检查。"""
from __future__ import annotations

import os
from functools import lru_cache

_license_ready = False


def _license_candidates() -> list[str]:
    from app.config import BACKEND_ROOT, INSTALL_DIR, get_settings

    settings_path = get_settings().aspose_license_path
    env_path = os.environ.get("ASPOSE_LICENSE_PATH", "").strip()
    bundled = [
        env_path,
        settings_path,
        str(INSTALL_DIR / "aspose" / "Aspose.License.txt"),
        str(BACKEND_ROOT.parent / "docs" / "Aspose.Words for Python  Developer OEM证书" / "Word究极工具" / "aspose-words" / "Aspose.License.txt"),
        "/aspose/Aspose.License.txt",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in bundled:
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


@lru_cache
def license_path() -> str:
    for candidate in _license_candidates():
        if os.path.isfile(candidate):
            return candidate
    return _license_candidates()[0] if _license_candidates() else ""


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


def iter_collection(collection):
    """Aspose Python 绑定中 Section/Row/Cell 等集合的 for-in 会产出无类型 Node，需按下标迭代。"""
    count_attr = getattr(collection, "count", None)
    if isinstance(count_attr, int):
        total = count_attr
    else:
        try:
            total = len(collection)
        except TypeError:
            total = int(count_attr() if callable(count_attr) else 0)
    for i in range(total):
        yield collection[i]


def smoke_test() -> dict:
    """生成最小 docx，用于部署后自检。"""
    ensure_license()
    aw = _load_aspose()
    doc = aw.Document()
    builder = aw.DocumentBuilder(doc)
    builder.writeln("Aspose.Words smoke test OK")
    return {"ok": True, "engine": "aspose.words", "license": license_path()}
