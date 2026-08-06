#!/usr/bin/env python3
"""将客户半空白模板工程化为含 {{key}} 的可替换模板。"""
from __future__ import annotations

import json
import os
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PACK = ROOT / "customer_data" / "heyuanzhineng_20260729" / "pack"
OUT = ROOT / "customer_data" / "heyuanzhineng_20260729" / "engineered_templates"
FIELD_KEYS = ROOT / "customer_data" / "heyuanzhineng_20260729" / "field_keys.json"

# 模板内已知原文 → 占位符（按长度降序替换，避免短串误伤）
TPL1_REPLACEMENTS = [
    (
        "中铁电气化局集团有限公司城铁公司北京地铁12号线工程合建柳芳110千伏轨道交通共建变电站总承包项目电气火灾监控设备、矿物质电缆及附件包件二次采购",
        "{{project_name}}",
    ),
    ("中铁电气化局集团有限公司城铁公司", "{{tenderer}}"),
    ("和远智能科技股份有限公司", "{{bidder_name}}"),
    ("EEBWTP2026-120（1）", "{{tender_no}}"),
    ("EEBWTP2026-120", "{{tender_no}}"),
    ("DLZM08", "{{package_no}}"),
    ("济南市高新区新泺大街1166号奥盛大厦1号楼7层", "{{address}}"),
    ("奥盛大厦", "{{address}}"),
    ("www.hyzn77.com", "{{website}}"),
    ("0531-68621670", "{{phone}}"),
    ("0531-68621770", "{{phone}}"),
    ("0531-68621679", "{{fax}}"),
    ("250100", "{{postcode}}"),
    ("张方恒", "{{legal_name}}"),
    ("5270万元", "{{registered_capital}}"),
    ("中国建设银行股份有限公司济南黄金时代支行", "{{bank_name}}"),
    ("建设银行", "{{bank_name}}"),
]

TPL3_REPLACEMENTS = [
    (
        "中铁四局集团电气化工程有限公司龙烟市域铁路 LYSG-2标四电项目RTU及能管系统采购",
        "{{project_name}}",
    ),
    (
        "中铁四局电气化公司龙烟市域铁路LYSG-2标四电项目RTU及能管系统采购",
        "{{project_name}}",
    ),
    ("中铁四局集团电气化工程有限公司", "{{tenderer}}"),
    ("和远智能科技股份有限公司", "{{bidder_name}}"),
    ("ZTSJWZ-DQH-2025-041", "{{tender_no}}"),
    ("RTU及能管系统", "{{material_type}}"),
    ("DL-01", "{{package_no}}"),
    ("济南市高新区新泺大街1166号奥盛大厦1号楼7层", "{{address}}"),
    ("奥盛大厦", "{{address}}"),
    ("www.hyzn77.com", "{{website}}"),
    ("0531-68621670", "{{phone}}"),
    ("0531-68621770", "{{phone}}"),
    ("0531-68621679", "{{fax}}"),
    ("250100", "{{postcode}}"),
    ("张方恒", "{{legal_name}}"),
    ("5270万元", "{{registered_capital}}"),
    ("建设银行", "{{bank_name}}"),
]


def ensure_license():
    lic = os.environ.get("ASPOSE_LICENSE_PATH") or str(
        ROOT
        / "docs"
        / "Aspose.Words for Python  Developer OEM证书"
        / "Word究极工具"
        / "aspose-words"
        / "Aspose.License.txt"
    )
    os.environ["ASPOSE_LICENSE_PATH"] = lic
    from app.services.aspose_runtime import ensure_license as _el

    _el(lic)


def apply_replacements(doc, pairs: list[tuple[str, str]]) -> int:
    import aspose.words as aw

    options = aw.replacing.FindReplaceOptions()
    count = 0
    # 长串优先
    for old, new in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
        if not old or old == new:
            continue
        n = doc.range.replace(old, new, options)
        count += int(n or 0)
    return count


def append_ai_markers(doc, chapters: list[str]):
    import aspose.words as aw

    builder = aw.DocumentBuilder(doc)
    builder.move_to_document_end()
    builder.insert_break(aw.BreakType.PAGE_BREAK)
    builder.paragraph_format.style_identifier = aw.StyleIdentifier.HEADING1
    builder.writeln("AI辅助生成章节（系统占位）")
    builder.paragraph_format.style_identifier = aw.StyleIdentifier.NORMAL
    for ch in chapters:
        builder.paragraph_format.style_identifier = aw.StyleIdentifier.HEADING2
        builder.writeln(ch)
        builder.paragraph_format.style_identifier = aw.StyleIdentifier.NORMAL
        builder.writeln(f"【AI_GENERATED:{ch}】")


def build_skeleton_template(chapters: list[str]) -> bytes:
    """当源模板不可用时生成最小可替换骨架。"""
    import aspose.words as aw

    doc = aw.Document()
    b = aw.DocumentBuilder(doc)
    b.writeln("投标文件")
    b.writeln("项目名称：{{project_name}}")
    b.writeln("招标编号：{{tender_no}}")
    b.writeln("包件号：{{package_no}}")
    b.writeln("采购人：{{tenderer}}")
    b.writeln("投标人：{{bidder_name}}")
    b.writeln("投标总价（大写）：{{bid_amount_upper}}")
    b.writeln("投标总价（小写）：{{bid_amount_lower}}")
    b.writeln("日期：{{bid_date}}")
    b.writeln("地址：{{address}}")
    b.writeln("电话：{{phone}}")
    b.writeln("法定代表人：{{legal_name}}")
    b.writeln("项目经理：{{project_manager}}")
    append_ai_markers(doc, chapters)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def engineer_one(src: Path, dst: Path, pairs: list[tuple[str, str]], chapters: list[str]) -> dict:
    import aspose.words as aw
    import re

    doc = aw.Document(str(src))
    n = apply_replacements(doc, pairs)
    text = doc.get_text() or ""
    # 若几乎未命中，仍追加 AI 标记并保存，同时记录
    if "【AI_GENERATED:" not in text:
        append_ai_markers(doc, chapters)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    data = out.getvalue()
    dst.write_bytes(data)
    ph = sorted(set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", data.decode("latin-1", errors="ignore"))))
    # better extract via aspose text
    text2 = aw.Document(BytesIO(data)).get_text() or ""
    ph = sorted(set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", text2)))
    ai = sorted(set(re.findall(r"【AI_GENERATED:([^】]+)】", text2)))
    return {"src": src.name, "dst": dst.name, "replacements": n, "placeholders": ph, "ai": ai}


def main() -> int:
    ensure_license()
    OUT.mkdir(parents=True, exist_ok=True)
    meta = json.loads(FIELD_KEYS.read_text(encoding="utf-8"))
    chapters = meta.get("ai_chapters") or []

    tpl_dir = PACK / "02-word标书模板" / "1-标准投标word模板"
    jobs = [
        ("铁路工程投标模板1-半空白.docx", "铁路工程投标模板1-工程化.docx", TPL1_REPLACEMENTS, "tpl1"),
        ("铁路工程投标模板3- 半空白.docx", "铁路工程投标模板3-工程化.docx", TPL3_REPLACEMENTS, "tpl3"),
    ]
    report = []
    for src_name, dst_name, pairs, code in jobs:
        src = tpl_dir / src_name
        dst = OUT / dst_name
        if not src.exists():
            # 模糊匹配
            cands = list(tpl_dir.glob("*.docx"))
            src = next((p for p in cands if code[-1] in p.name or ("模板1" in p.name and code == "tpl1") or ("模板3" in p.name and code == "tpl3")), None)
        if not src or not src.exists():
            print(f"[warn] 缺少源模板 {src_name}，生成骨架")
            dst.write_bytes(build_skeleton_template(chapters))
            report.append({"dst": dst_name, "mode": "skeleton", "template_code": code})
            continue
        info = engineer_one(src, dst, pairs, chapters)
        info["template_code"] = code
        # 若占位符过少，叠加骨架页保证可测
        if len(info["placeholders"]) < 5:
            import aspose.words as aw

            doc = aw.Document(str(dst))
            sk = aw.Document(BytesIO(build_skeleton_template(chapters)))
            doc.append_document(sk, aw.ImportFormatMode.KEEP_SOURCE_FORMATTING)
            buf = BytesIO()
            doc.save(buf, aw.SaveFormat.DOCX)
            dst.write_bytes(buf.getvalue())
            text2 = aw.Document(BytesIO(dst.read_bytes())).get_text() or ""
            import re

            info["placeholders"] = sorted(set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", text2)))
            info["mode"] = "hybrid"
        else:
            info["mode"] = "engineered"
        report.append(info)
        print(f"[ok] {dst.name}: replacements={info.get('replacements')} placeholders={len(info['placeholders'])}")

    # 额外输出纯骨架，便于联调
    (OUT / "骨架模板-通用.docx").write_bytes(build_skeleton_template(chapters))
    report_path = OUT / "engineer_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告 → {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
