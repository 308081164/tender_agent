#!/usr/bin/env python3
"""生成标书智能体系统完整测试材料包，并输出到 release/ 目录。

用法：
    python scripts/build_test_materials_pack.py

产出：
    release/tender-agent-test-materials-<version>.zip
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
PACK_NAME = "heyuanzhineng_20260729"
VERSION = "1.0.0"
STAGING = ROOT / ".build" / PACK_NAME

FIELD_KEYS_SRC = ROOT / "customer_data" / PACK_NAME / "field_keys.json"


def _docx_bytes(doc: Document) -> bytes:
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _extract_placeholders(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="ignore")
    return sorted(set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", text)))


def _heading(doc: Document, text: str, level: int = 1) -> None:
    doc.add_heading(text, level=level)


def build_engineered_doc(
    title: str,
    fields: list[tuple[str, str]],
    ai_chapters: list[str],
) -> bytes:
    doc = Document()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(18)
    for label, key in fields:
        doc.add_paragraph(f"{label}：{{{{{key}}}}}")
    doc.add_page_break()
    _heading(doc, "第一卷 商务标")
    _heading(doc, "第一章 投标函", 2)
    doc.add_paragraph(
        "致 {{tenderer}}：我方已仔细研究 {{project_name}}（招标编号：{{tender_no}}）"
        "招标文件，愿以 {{bid_amount_upper}}（小写：{{bid_amount_lower}}）的投标总价完成本项目。"
    )
    _heading(doc, "第二卷 技术标")
    for ch in ai_chapters:
        _heading(doc, ch, 2)
        doc.add_paragraph(f"【AI_GENERATED:{ch}】")
    return _docx_bytes(doc)


def build_semi_blank_doc(title: str, values: list[tuple[str, str]]) -> bytes:
    doc = Document()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(18)
    for label, value in values:
        doc.add_paragraph(f"{label}：{value}")
    doc.add_paragraph("本文件用于测试模板上传与占位符自动识别。")
    return _docx_bytes(doc)


def build_history_doc(title: str, project: str, tenderer: str, amount: str) -> bytes:
    doc = Document()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
    doc.add_paragraph(f"项目名称：{project}")
    doc.add_paragraph("招标编号：EEBWTP2026-DEMO-001")
    doc.add_paragraph(f"采购人：{tenderer}")
    doc.add_paragraph("投标人：和远智能科技股份有限公司")
    doc.add_paragraph(f"投标总价：{amount}")
    doc.add_paragraph("项目经理：张方恒")
    _heading(doc, "施工组织设计", 2)
    doc.add_paragraph("本工程采用分段流水施工，严格执行铁路工程施工质量验收标准。")
    return _docx_bytes(doc)


def build_qual_doc(title: str, body: str) -> bytes:
    doc = Document()
    p = doc.add_paragraph()
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
    for line in body.strip().splitlines():
        doc.add_paragraph(line)
    return _docx_bytes(doc)


def write_txt(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def write_xlsx(path: Path, headers: list, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def write_checklist_workbook(path: Path, sheets: dict[str, list[list]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    first = True
    for sheet_name, rows in sheets.items():
        if first:
            ws = wb.active
            ws.title = sheet_name
            first = False
        else:
            ws = wb.create_sheet(sheet_name)
        headers = ["序号", "条目名称", "是否必含", "对应章节", "备注"]
        ws.append(headers)
        for row in rows:
            ws.append(row)
    wb.save(path)


def build_pack(meta: dict) -> None:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)

    if FIELD_KEYS_SRC.exists():
        shutil.copy2(FIELD_KEYS_SRC, STAGING / "field_keys.json")
    else:
        (STAGING / "field_keys.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    field_meta = json.loads((STAGING / "field_keys.json").read_text(encoding="utf-8"))
    ai_chapters = field_meta.get("ai_chapters") or []

    common_fields = [
        ("项目名称", "project_name"),
        ("招标编号", "tender_no"),
        ("包件号", "package_no"),
        ("采购人", "tenderer"),
        ("投标人", "bidder_name"),
        ("投标总价（大写）", "bid_amount_upper"),
        ("投标总价（小写）", "bid_amount_lower"),
        ("日期", "bid_date"),
        ("地址", "address"),
        ("电话", "phone"),
        ("法定代表人", "legal_name"),
        ("项目经理", "project_manager"),
    ]

    eng_dir = STAGING / "engineered_templates"
    eng_dir.mkdir(parents=True, exist_ok=True)

    tpl1 = build_engineered_doc("铁路工程投标模板1-工程化", common_fields, ai_chapters)
    (eng_dir / "铁路工程投标模板1-工程化.docx").write_bytes(tpl1)
    tpl3_fields = common_fields + [("物资品种", "material_type")]
    tpl3 = build_engineered_doc("铁路工程投标模板3-工程化", tpl3_fields, ai_chapters)
    (eng_dir / "铁路工程投标模板3-工程化.docx").write_bytes(tpl3)
    skeleton = build_engineered_doc("骨架模板-通用", common_fields[:8], ai_chapters[:3])
    (eng_dir / "骨架模板-通用.docx").write_bytes(skeleton)

    pack = STAGING / "pack"

    write_txt(
        pack / "01-企业与项目基础信息" / "1.企业基本信息【必填】.txt",
        """
企业全称：和远智能科技股份有限公司
企业简称：和远智能
统一社会信用代码：91370100MA3C8XXXXXX
注册地址：济南市高新区新泺大街1166号奥盛大厦1号楼7层
办公地址：济南市高新区新泺大街1166号奥盛大厦1号楼7层
法定代表人：张方恒
注册资本：5270万元
成立日期：2010-03-15
联系电话：0531-68621670
企业邮箱：demo@hyzn77.com
开户银行：中国建设银行股份有限公司济南黄金时代支行
银行账号：370000000000000001
企业简介：和远智能科技股份有限公司专注于铁路、轨道交通智能化设备与系统集成。
主营业务：RTU及能管系统、电气火灾监控、能源管理抄表、运维监控
铁路/轨道交通相关资质概述：高新技术企业；多项铁路行业供货业绩
""",
    )
    write_txt(
        pack / "01-企业与项目基础信息" / "2.典型投标项目说明【建议】.txt",
        "1. 铁路四电项目 RTU 及能管系统采购\n2. 地铁电气火灾监控设备采购\n3. 变电站共建项目设备包件采购\n",
    )

    semi_dir = pack / "02-word标书模板" / "1-标准投标word模板"
    semi_dir.mkdir(parents=True, exist_ok=True)
    semi1 = build_semi_blank_doc(
        "铁路工程投标模板1-半空白",
        [
            ("项目名称", "中铁电气化局集团有限公司城铁公司北京地铁12号线工程合建柳芳110千伏轨道交通共建变电站总承包项目电气火灾监控设备、矿物质电缆及附件包件二次采购"),
            ("采购人", "中铁电气化局集团有限公司城铁公司"),
            ("投标人", "和远智能科技股份有限公司"),
            ("招标编号", "EEBWTP2026-120（1）"),
            ("包件号", "DLZM08"),
            ("地址", "济南市高新区新泺大街1166号奥盛大厦1号楼7层"),
        ],
    )
    (semi_dir / "铁路工程投标模板1-半空白.docx").write_bytes(semi1)
    semi3 = build_semi_blank_doc(
        "铁路工程投标模板3-半空白",
        [
            ("项目名称", "中铁四局集团电气化工程有限公司龙烟市域铁路 LYSG-2标四电项目RTU及能管系统采购"),
            ("采购人", "中铁四局集团电气化工程有限公司"),
            ("投标人", "和远智能科技股份有限公司"),
            ("招标编号", "ZTSJWZ-DQH-2025-041"),
            ("物资品种", "RTU及能管系统"),
            ("包件号", "DL-01"),
        ],
    )
    (semi_dir / "铁路工程投标模板3- 半空白.docx").write_bytes(semi3)
    write_txt(
        pack / "02-word标书模板" / "3-模板格式规范说明【建议】.txt",
        "正文宋体小四；一级标题黑体三号；页边距上下2.54cm左右3.17cm。\n",
    )

    hist_dir = pack / "03-历史投标文件" / "1-完整历史标书"
    hist_dir.mkdir(parents=True, exist_ok=True)
    histories = [
        ("历史标书-地铁12号线电气火灾监控-2025.docx", "北京地铁12号线电气火灾监控设备采购", "中铁电气化局集团有限公司城铁公司", "人民币壹仟贰佰万元整"),
        ("历史标书-龙烟铁路RTU采购-2024.docx", "龙烟市域铁路 RTU 及能管系统采购", "中铁四局集团电气化工程有限公司", "人民币捌佰伍拾万元整"),
    ]
    for fname, project, tenderer, amount in histories:
        (hist_dir / fname).write_bytes(build_history_doc(fname.replace(".docx", ""), project, tenderer, amount))
    write_txt(
        pack / "03-历史投标文件" / "3-AI生成内容风格参考【建议】.txt",
        "语言正式严谨；技术方案需包含供货计划、运输方案、售后服务与质量保证措施。\n",
    )

    checklist_dir = pack / "05-条目完整性校验清单"
    biz_rows = [[1, "投标函", "必含", "第一章", ""], [2, "法定代表人身份证明", "必含", "第二章", ""]]
    write_checklist_workbook(
        checklist_dir / "1-商务标条目清单.xlsx",
        {"模板1": biz_rows, "模板3": biz_rows},
    )
    tech_rows = [[1, "技术规格书条款点对点应答", "必含", "第二章", ""], [2, "生产供应计划方案", "必含", "第三章", ""]]
    write_checklist_workbook(
        checklist_dir / "2-技术标条目清单.xlsx",
        {"模板1": tech_rows, "模板3": tech_rows},
    )
    write_checklist_workbook(
        checklist_dir / "3-报价标条目清单.xlsx",
        {"模板1": [[1, "投标报价表", "必含", "第一章", ""]], "模板3": [[1, "投标报价表", "必含", "第一章", ""]]},
    )
    write_checklist_workbook(
        checklist_dir / "4-资质材料必附清单.xlsx",
        {"模板1": [[1, "营业执照", "必附", "企业资质", ""]], "模板3": [[1, "营业执照", "必附", "企业资质", ""]]},
    )

    qual_root = pack / "06-资质数据库参考资料"
    today = date.today()
    quals = [
        ("企业资质包", "营业执照", "企业资质_营业执照.docx", True, "市场监督管理局"),
        ("企业资质包", "高新技术企业证书", "企业资质_高新技术企业证书.docx", False, "科技厅"),
        ("业绩包", "地铁12号线中标通知书", "业绩_地铁12号线中标通知.docx", True, "中铁电气化局"),
        ("人员信息包", "项目经理简历", "人员_项目经理张方恒.docx", False, "企业内部"),
        ("财务信息包", "近三年审计报告", "财务_近三年审计报告.docx", True, "会计师事务所"),
        ("信誉与法律包", "无行贿犯罪证明", "信誉_无行贿证明.docx", False, "检察机关"),
        ("技术方案包", "供货及售后服务方案", "技术_供货售后服务方案.docx", True, "企业内部"),
        ("商务文件包", "投标函", "商务_投标函.docx", True, "企业内部"),
    ]
    qual_rows = []
    for i, (cat, name, fname, long_term, issuer) in enumerate(quals, 1):
        expire = "" if long_term else (today + timedelta(days=730)).isoformat()
        start = (today - timedelta(days=365)).isoformat()
        body = f"材料名称：{name}\n颁发机构：{issuer}\n有效期起：{start}\n有效期止：{expire or '长期有效'}\n（测试材料，仅供系统验收）"
        qual_file = qual_root / cat / fname
        qual_file.parent.mkdir(parents=True, exist_ok=True)
        qual_file.write_bytes(build_qual_doc(name, body))
        qual_rows.append([
            i, cat, name, fname, start, expire or "长期", issuer, "docx", name,
            "是" if long_term else "否", "测试材料",
        ])
    write_xlsx(
        qual_root / "资质材料清单.xlsx",
        ["序号", "分类", "材料名称", "文件名", "有效期起", "有效期止", "颁发机构", "文件类型", "关键词标签", "是否长期有效", "备注"],
        qual_rows,
    )
    write_txt(qual_root / "08-资质插入规则说明.txt", "企业资质章节附营业执照；人员章节附项目经理简历；业绩章节附中标通知书。\n")

    faq_dir = pack / "07-企业问答chatbot参考"
    write_xlsx(
        faq_dir / "企业问答参考.xlsx",
        ["序号", "问题类别", "问题内容", "标准答案", "答案来源材料", "备注"],
        [
            [1, "企业资质类", "是否具备高新技术企业资质？", "是，我公司为高新技术企业。", "企业资质_高新技术企业证书.docx", ""],
            [2, "业绩类", "是否有地铁项目供货业绩？", "有，已完成北京地铁12号线相关设备供货。", "业绩_地铁12号线中标通知.docx", ""],
            [3, "人员类", "项目经理是谁？", "拟任项目经理为张方恒。", "人员_项目经理张方恒.docx", ""],
            [4, "财务类", "能否提供近三年审计报告？", "可以，可提供近三年审计报告。", "财务_近三年审计报告.docx", ""],
            [5, "技术类", "售后服务方案包含哪些内容？", "包含安装调试、培训、质保期维保与应急响应。", "技术_供货售后服务方案.docx", ""],
        ],
    )

    manual = STAGING.parent / "manual_upload"
    if manual.exists():
        shutil.rmtree(manual)
    manual.mkdir(parents=True)
    (manual / "待上传-工程化模板（含占位符）.docx").write_bytes(tpl1)
    (manual / "待上传-半空白标书（Agent识别）.docx").write_bytes(semi1)
    (manual / "待上传-历史标书.docx").write_bytes(
        build_history_doc("历史标书-手动上传测试", "测试铁路工程项目", "测试采购人", "人民币伍佰万元整")
    )

    readme = STAGING.parent / "README-测试材料使用说明.md"
    readme.write_text(
        f"""# 标书智能体系统 · 测试材料包 v{VERSION}

本压缩包包含验收与日常测试所需的全部样例文件。

## 目录结构

```
{PACK_NAME}/                 # 一键导入包（数据管理 → 导入/备份）
  field_keys.json            # 字段定义
  engineered_templates/      # 工程化模板（含 {{{{占位符}}}}）
  pack/                      # 企业信息、历史标书、资质、清单、FAQ
manual_upload/               # 手动上传测试用 DOCX（不经过导入）
README-测试材料使用说明.md   # 本文件
```

## 快速开始

### 方式一：一键导入（推荐）

1. 解压本压缩包。
2. 将 `{PACK_NAME}` 文件夹复制到安装目录下的 `customer_data/`（桌面版：`%LOCALAPPDATA%\\\\TenderAgent\\\\customer_data\\\\`）。
3. 打开系统 → **数据管理 → 导入/备份** → 点击 **强制重新导入**。
4. 导入完成后，进入 **新建标书** 即可看到工程化模板与历史标书。

### 方式二：手动上传模板

使用 `manual_upload/` 中的 DOCX：

| 文件 | 用途 |
|------|------|
| 待上传-工程化模板（含占位符）.docx | 数据管理 → 模板管理 → 上传模板 |
| 待上传-半空白标书（Agent识别）.docx | 文档 Agent 上传后创建模板 |
| 待上传-历史标书.docx | 模板管理 → 历史标书 标签页上传 |

### 方式三：开发环境命令行导入

```bash
export CUSTOMER_DATA_DIR=/path/to/{PACK_NAME}
cd backend && python -m app.seed.import_customer_pack --force
```

## 可验证功能清单

- [ ] 导入/备份：增量导入、强制重导、导出 JSON 备份
- [ ] 新建标书：选择工程化模板1/3、历史标书智能替换
- [ ] 模板管理：上传、预览、占位符查看、工程化
- [ ] 资质管理：列表、预览附件、插入标书
- [ ] 清单校验：商务/技术/报价/资质条目检查
- [ ] 文档 Agent：上传半空白标书 → 识别占位符 → 创建模板
- [ ] Chatbot：FAQ 问答命中

## 注意事项

- 所有企业与项目信息均为 **虚构测试数据**，请勿用于真实投标。
- Agent 创建模板需完成占位符映射确认后才会在新建标书中可选。
- 桌面版首次安装若已自动导入演示数据，使用强制重导可替换为本材料包内容。
""",
        encoding="utf-8",
    )


def create_zip() -> Path:
    RELEASE.mkdir(parents=True, exist_ok=True)
    zip_path = RELEASE / f"tender-agent-test-materials-v{VERSION}.zip"
    if zip_path.exists():
        zip_path.unlink()
    base = STAGING.parent
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for folder in [STAGING, base / "manual_upload"]:
            if not folder.exists():
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(base).as_posix())
        readme = base / "README-测试材料使用说明.md"
        if readme.exists():
            zf.write(readme, readme.name)
    return zip_path


def main() -> int:
    meta = (
        json.loads(FIELD_KEYS_SRC.read_text(encoding="utf-8"))
        if FIELD_KEYS_SRC.exists()
        else {"fields": [], "ai_chapters": []}
    )
    build_pack(meta)
    zip_path = create_zip()
    size_kb = zip_path.stat().st_size // 1024
    ph_count = len(_extract_placeholders((STAGING / "engineered_templates" / "铁路工程投标模板1-工程化.docx").read_bytes()))
    print(f"测试材料包已生成: {zip_path} ({size_kb} KB, 模板1含 {ph_count} 个占位符)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
