#!/usr/bin/env python3
"""客户包工程化模板 + 渲染冒烟测试。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault(
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

from app.services import word  # noqa: E402


def main() -> int:
    eng = ROOT / "customer_data" / "heyuanzhineng_20260729" / "engineered_templates"
    files = sorted(eng.glob("*.docx"))
    if not files:
        print("FAIL: 无工程化模板，请先运行 scripts/engineer_templates.py")
        return 1
    fields = {
        "project_name": "验收测试项目-电气火灾监控设备采购",
        "tender_no": "TEST-2026-001",
        "package_no": "DL01",
        "tenderer": "测试招标人",
        "bidder_name": "和远智能科技股份有限公司",
        "bid_amount_upper": "人民币壹佰万元整",
        "bid_amount_lower": "¥1000000.00",
        "bid_date": "2026年7月29日",
        "phone": "0531-68621770",
        "legal_name": "张方恒",
        "address": "济南市高新区新泺大街1166号奥盛大厦1号楼7层",
        "project_manager": "测试经理",
    }
    chapters = {
        "售后服务方案": {"content": "提供7×24小时响应，质保期内免费维修。", "source": "test"},
    }
    for f in files:
        data = f.read_bytes()
        ph = word.extract_placeholders(data)
        rendered = word.render_document(data, fields, chapters, highlight=False)
        leftover = word.extract_placeholders(rendered)
        # 允许企业固定信息未完全替换的残留较少
        critical = [k for k in leftover if k in ("project_name", "tender_no", "package_no")]
        print(f"[ok] {f.name}: placeholders_in={len(ph)} leftover_critical={critical}")
        if critical:
            print("FAIL critical leftovers", critical)
            return 1
        # 嵌入一张空测也可跳过
    print("客户包渲染冒烟通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
