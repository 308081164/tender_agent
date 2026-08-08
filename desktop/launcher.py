"""标书智能体桌面开发启动器 — 开发环境启动 Electron 壳。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    root = _repo_root()
    electron_dir = root / "desktop" / "electron"
    if not electron_dir.is_dir():
        print("desktop/electron 目录不存在", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.setdefault("TENDER_INSTALL_DIR", str(root))
    local = os.environ.get("LOCALAPPDATA")
    if local and "TENDER_DATA_DIR" not in env:
        env["TENDER_DATA_DIR"] = str(Path(local) / "TenderAgent" / "data")

    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    print(f"Starting Electron dev shell (install_dir={env['TENDER_INSTALL_DIR']})")
    try:
        return subprocess.call([npm, "start"], cwd=str(electron_dir), env=env)
    except FileNotFoundError:
        print("未找到 npm，请先安装 Node.js", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
