"""表格槽：按行模板填充表格数据。"""
from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

import aspose.words as aw

from app.services.aspose_runtime import ensure_license, iter_collection
from app.services.word import PLACEHOLDER_RE

TABLE_ROW_BIND_RE = re.compile(r"^\{\{(.+?)\}\}$")


def _clean_cell_text(text: str) -> str:
    return (text or "").replace("\x07", "").replace("\a", "").strip()


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
                text = _clean_cell_text(cell.get("text") or "")
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
        header_join = ""
        if template_row < 0 and rows:
            header_cells = rows[0]
            header_texts = [_clean_cell_text(cell.get("text") or "") for cell in header_cells]
            header_join = "".join(header_texts)
            if any(token in header_join for token in ("序号", "认证", "名称", "编号", "备注")):
                columns = [text or f"列{i + 1}" for i, text in enumerate(header_texts)]
                template_row = 1 if len(rows) > 1 else 0
        if template_row < 0 or not columns:
            continue
        bind = columns[0] if len(columns) == 1 else f"table_{t_idx}_rows"
        if any(k in "".join(columns) for k in ("认证", "许可", "证书")):
            bind = f"cert_table_{t_idx}_rows"
        first_cell_loc = rows[template_row][0].get("location") if rows[template_row] else f"tbl:{t_idx}:r{template_row}:c0"
        blocks.append({
            "id": f"table.{t_idx}",
            "type": "table_slot",
            "bind": bind,
            "columns": columns,
            "table_index": t_idx,
            "header_rows": min(template_row, 1),
            "template_row": template_row,
            "title": header_join,
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
            col_key = _clean_cell_text(col)
            val = str(row_data.get(col) or row_data.get(col_key) or "")
            para.append_child(aw.Run(doc, val))
            cell.append_child(para)
        tbl.rows.add(new_row)

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def fill_cover_bidder_profile_table(docx_bytes: bytes, fields: dict[str, Any]) -> bytes:
    """封面「竞标人名称/注册地址」等标签-值表：按字段填相邻单元格，不用 LLM 多行叙事。"""
    bidder = str(fields.get("bidder_name") or fields.get("bidder") or "").strip()
    address = str(fields.get("address") or fields.get("office_address") or "").strip()
    if not bidder and not address:
        return docx_bytes
    label_map = {
        "竞标人名称": bidder,
        "注册地址": address,
        "单位地址": address,
        "通讯地址": address,
    }
    doc = _load(docx_bytes)
    tbl_nodes = doc.get_child_nodes(aw.NodeType.TABLE, True)
    if tbl_nodes.count < 1:
        return docx_bytes
    tbl = tbl_nodes[0].as_table()
    max_rows = min(5, tbl.rows.count)
    while tbl.rows.count > max_rows:
        tbl.rows.remove_at(tbl.rows.count - 1)
    for row in iter_collection(tbl.rows):
        for c in range(row.cells.count - 1):
            label = _clean_cell_text(row.cells[c].get_text())
            if label not in label_map or not label_map[label]:
                continue
            val = label_map[label]
            cell = row.cells[c + 1]
            cell.remove_all_children()
            p = aw.Paragraph(doc)
            p.append_child(aw.Run(doc, val))
            cell.append_child(p)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()
