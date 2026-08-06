#!/usr/bin/env python3
"""规范化 → 工程化模板 → 导入数据库。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]):
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def main() -> int:
    force = "--force" in sys.argv
    run([sys.executable, str(ROOT / "scripts" / "normalize_customer_pack.py")])
    env = os.environ.copy()
    env.setdefault(
        "ASPOSE_LICENSE_PATH",
        str(
            ROOT
            / "docs"
            / "Aspose.Words for Python  Developer OEM证书"
            / "Word究极工具"
            / "aspose-words"
            / "Aspose.License.txt"
        ),
    )
    subprocess.check_call(
        [sys.executable, str(ROOT / "scripts" / "engineer_templates.py")],
        cwd=str(ROOT),
        env=env,
    )
    # 导入
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("DATABASE_URL", "postgresql://tender:tender123@127.0.0.1:5432/tender_agent")
    os.environ.setdefault("MINIO_ENDPOINT", "127.0.0.1:9000")
    os.environ.setdefault(
        "CUSTOMER_DATA_DIR",
        str(ROOT / "customer_data" / "heyuanzhineng_20260729"),
    )
    from app.database_migrate import ensure_schema
    from app.seed.import_customer_pack import run_import

    ensure_schema()
    print(run_import(force=force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
