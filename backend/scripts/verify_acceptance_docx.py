#!/usr/bin/env python3
"""Verify acceptance docx: sections and minimum word counts per major heading."""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

from docx import Document

MIN_AI_PARA_CHARS = 80
STUB_PATTERNS = ("待填写", "TBD", "xxx")
AI_TITLES = [
    "竞标函",
    "法定代表人身份证明",
    "资格证明资料",
    "竞标人基本情况表",
    "履约信用证明",
    "其他材料",
    "竞标物资技术规格书",
    "生产组织供应能力分析表",
    "拟投入本项目的主要生产设备、检验设备表",
    "关于产品符合相关标准的承诺书",
]


def norm_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/cursor/stores/self/media/acceptance-full-bid-sample.docx")
    doc = Document(str(path))
    full = "\n".join(p.text for p in doc.paragraphs if p.text)
    total = norm_len(full)
    ai_paras = [
        p.text.strip()
        for p in doc.paragraphs
        if p.text
        and (
            "针对招标项目「" in p.text
            or "华远智通" in p.text
            or (p.text.startswith("关于「") and ("作如下说明" in p.text or "内容：" in p.text))
        )
    ]
    failures: list[str] = []
    report_lines = [
        f"DOCX: {path}",
        f"paragraphs_total={len(doc.paragraphs)}",
        f"total_chars={total}",
        f"ai_substantive_paragraphs={len(ai_paras)}",
        "",
    ]

    for title in AI_TITLES:
        hits = [t for t in ai_paras if title in t and norm_len(t) >= MIN_AI_PARA_CHARS]
        ok = bool(hits) and not any(s in (hits[0] if hits else "") for s in STUB_PATTERNS)
        flag = "OK" if ok else "FAIL"
        report_lines.append(f"{flag} {title} ({len(hits)} hit(s), sample={norm_len(hits[0]) if hits else 0} chars)")
        if not ok:
            failures.append(title)

    print("\n".join(report_lines))
    if failures or total < 5000:
        if total < 5000:
            failures.append(f"total_chars<{5000}")
        print("\nFAILED:", failures, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
