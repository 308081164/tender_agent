#!/usr/bin/env python3
"""规范化和远客户材料：修复双后缀、复制到 customer_data、生成 manifest。"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "标书智能体参考资料-和远智能-20260729"
DST = ROOT / "customer_data" / "heyuanzhineng_20260729" / "pack"

DOUBLE_EXT = re.compile(
    r"\.(jpg|jpeg|png|pdf|docx|xlsx|doc|jgp)\.\1$",
    re.IGNORECASE,
)
TYPO_EXT = {".jgp": ".jpg", ".JGP": ".jpg"}


def fix_name(name: str) -> str:
    n = name
    # 重复扩展名：file.jpg.jpg -> file.jpg
    while True:
        m = DOUBLE_EXT.search(n)
        if not m:
            break
        n = n[: m.start()] + "." + m.group(1).lower()
    for bad, good in TYPO_EXT.items():
        if n.lower().endswith(bad.lower()) and not n.lower().endswith(good):
            n = n[: -len(bad)] + good
    # 规范空格
    n = n.replace("  ", " ").strip()
    return n


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"源目录不存在: {SRC}")
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source": str(SRC.relative_to(ROOT)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
    }

    for src in sorted(SRC.rglob("*")):
        if not src.is_file():
            continue
        if src.name.startswith("."):
            continue
        rel = src.relative_to(SRC)
        parts = list(rel.parts[:-1]) + [fix_name(rel.name)]
        dest = DST.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        manifest["files"].append(
            {
                "src": str(rel).replace("\\", "/"),
                "dst": str(dest.relative_to(DST)).replace("\\", "/"),
                "size": dest.stat().st_size,
                "sha16": file_hash(dest),
                "ext": dest.suffix.lower(),
            }
        )

    out = DST.parent / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"规范化完成: {len(manifest['files'])} 个文件 → {DST}")
    print(f"manifest → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
