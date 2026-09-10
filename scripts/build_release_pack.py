#!/usr/bin/env python3
"""生成 release/ 目录：手册、版本清单、验收脚本副本。"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
VERSION_FILE = ROOT / "VERSION"


def main() -> None:
    version = (VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "1.1.0")
    RELEASE.mkdir(parents=True, exist_ok=True)

    manifest = {
        "version": version,
        "display_version": f"v{version}",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deepseek_default_model": "deepseek-v4-pro",
        "doc_engine": "v2",
        "artifacts": {
            "windows_installer": f"TenderAgentSetup-v{version}.exe",
            "user_manual": f"tender-agent-manual-v{version}.md",
            "docs_zip": f"tender-agent-release-v{version}.zip",
        },
    }
    (RELEASE / "VERSION.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (RELEASE / "VERSION").write_text(version + "\n", encoding="utf-8")

    manual_src = ROOT / "docs" / "用户手册.md"
    manual_dst = RELEASE / f"tender-agent-manual-v{version}.md"
    if manual_src.exists():
        shutil.copy2(manual_src, manual_dst)
        shutil.copy2(manual_src, RELEASE / "用户手册.md")

    readme = RELEASE / "README.md"
    readme.write_text(
        f"""# Release {version}

本目录包含标书智能体 **v{version}** 发布物。

## 下载清单

| 文件 | 说明 |
|------|------|
| `TenderAgentSetup-v{version}.exe` | Windows 离线安装包（在 Windows 上运行 `package-desktop.ps1` 生成后复制至此） |
| `tender-agent-manual-v{version}.md` | 用户手册 |
| `tender-agent-release-v{version}.zip` | 手册 + 验收脚本 + 版本信息压缩包 |
| `VERSION.json` | 版本元数据 |

## Windows 打包命令

```powershell
.\\package-desktop.ps1 -AppVersion "{version}"
```

打包完成后安装包会复制到本目录。

## 验收

```powershell
.\\scripts\\verify_windows_features.ps1
```

""",
        encoding="utf-8",
    )

    # 验收脚本副本
    verify_ps1 = ROOT / "scripts" / "verify_windows_features.ps1"
    if verify_ps1.exists():
        shutil.copy2(verify_ps1, RELEASE / "verify_windows_features.ps1")

    zip_path = RELEASE / f"tender-agent-release-v{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("VERSION.json", "VERSION", "README.md", "用户手册.md", f"tender-agent-manual-v{version}.md"):
            p = RELEASE / name
            if p.exists():
                zf.write(p, arcname=name)
        if verify_ps1.exists():
            zf.write(verify_ps1, arcname="verify_windows_features.ps1")

    # 若 dist 已有安装包则复制
    setup = ROOT / "dist" / "TenderAgentSetup.exe"
    if setup.exists():
        dest = RELEASE / f"TenderAgentSetup-v{version}.exe"
        shutil.copy2(setup, dest)
        shutil.copy2(setup, RELEASE / "TenderAgentSetup.exe")
        print(f"Copied installer -> {dest}")

    print(f"Release pack ready: {RELEASE}")
    print(f"  version={version}")
    print(f"  zip={zip_path.name}")


if __name__ == "__main__":
    main()
