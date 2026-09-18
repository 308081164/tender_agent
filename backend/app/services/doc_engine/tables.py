"""表格槽：按行模板填充表格数据。"""
from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

import aspose.words as aw

from app.services.aspose_runtime import ensure_license
from app.services.word import PLACEHOLDER_RE

TABLE_ROW_BIND_RE = re.compile(r"^\{\{(.+?)\}\}$")


def _load(docx_bytes: bytes) -> aw.Document:
    ensure_license()
    return aw.Document(BytesIO(docx_bytes))


def infer_table_slots(index: dict[str, Any]) -> list[dict[str, Any]]:
    """从文档索引推断 table_slot 块。"""
    blocks: list[dict[str, Any]] = []
    for tbl in index.get("tables") or []:
        t_idx = tbl.get("index", 0)
        rows = tbl.get("rows") or []
        if len(rows) < 2:
            continue
        columns: list[str] = []
        template_row = -1
        for r, row in enumerate(rows):
            keys: list[str] = []
            seen: set[str] = set()
            for cell in row:
                text = (cell.get("text") or "").strip()
                for ph in cell.get("placeholders") or PLACEHOLDER_RE.findall(text):
                    if ph not in seen:
                        seen.add(ph)
                        keys.append(ph)
                m = TABLE_ROW_BIND_RE.match(text)
                if m and m.group(1) not in seen:
                    seen.add(m.group(1))
                    keys.append(m.group(1))
            if keys:
                template_row = r
                columns = keys
                break
        if template_row < 0:
            continue
        first_cell_loc = rows[template_row][0].get("location") if rows[template_row] else f"tbl:{t_idx}:r{template_row}:c0"
        blocks.append({
            "id": f"table.{t_idx}",
            "type": "table_slot",
            "bind": columns[0] if len(columns) == 1 else f"table_{t_idx}_rows",
            "columns": columns,
            "table_index": t_idx,
            "header_rows": template_row,
            "template_row": template_row,
            "anchor": {"kind": "location", "location": first_cell_loc},
            "required": False,
        })
    return blocks


def parse_rows_data(raw: Any) -> list[dict[str, Any]]:
    """将字段值解析为行数据列表。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        if "rows" in raw and isinstance(raw["rows"], list):
            return [x for x in raw["rows"] if isinstance(x, dict)]
        return [raw]
    text = str(raw).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return parse_rows_data(data)
    except json.JSONDecodeError:
        return []


def resolve_table_rows(block: dict[str, Any], fields: dict[str, Any]) -> list[dict[str, Any]]:
    bind = block.get("bind") or ""
    columns = block.get("columns") or []
    if bind and bind in (fields or {}):
        rows = parse_rows_data(fields.get(bind))
        if rows:
            return rows
    # 尝试按列名逐项组装单行
    if columns:
        row = {col: str(fields.get(col) or "") for col in columns}
        if any(row.values()):
            return [row]
    return []


def fill_table_slot(
    docx_bytes: bytes,
    table_index: int,
    columns: list[str],
    rows: list[dict[str, Any]],
    *,
    header_rows: int = 1,
    template_row: int | None = None,
) -> bytes:
    """按模板行样式克隆并填充表格数据。"""
    if not rows:
        return docx_bytes
    doc = _load(docx_bytes)
    tbl_nodes = doc.get_child_nodes(aw.NodeType.TABLE, True)
    if table_index >= tbl_nodes.count:
        return docx_bytes
    tbl = tbl_nodes[table_index].as_table()
    tpl_row_idx = template_row if template_row is not None else header_rows
    if tpl_row_idx >= tbl.rows.count:
        tpl_row_idx = max(0, tbl.rows.count - 1)
    template_row_node = tbl.rows[tpl_row_idx]

    # 删除模板行之后的旧数据行
    while tbl.rows.count > tpl_row_idx + 1:
        tbl.rows.remove_at(tbl.rows.count - 1)

    for row_data in rows:
        new_row = template_row_node.clone(True).as_row()
        for c, col in enumerate(columns):
            if c >= new_row.cells.count:
                break
            cell = new_row.cells[c]
            cell.remove_all_children()
            para = aw.Paragraph(doc)
            para.append_child(aw.Run(doc, str(row_data.get(col) or "")))
            cell.append_child(para)
        tbl.rows.add(new_row)

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()
