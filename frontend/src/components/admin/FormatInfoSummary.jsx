import React from 'react'

function fmtStyle(row) {
  if (!row) return '—'
  const parts = []
  if (row.font_name) parts.push(row.font_name)
  if (row.font_size_pt) parts.push(`${row.font_size_pt}pt`)
  if (row.bold) parts.push('加粗')
  if (row.alignment && row.alignment !== 'left') {
    const alignMap = { center: '居中', right: '右对齐', justify: '两端对齐' }
    parts.push(alignMap[row.alignment] || row.alignment)
  }
  if (row.indent_pt) parts.push(`缩进 ${row.indent_pt}pt`)
  return parts.length ? parts.join(' · ') : '—'
}

export function paragraphPreviewStyle(p) {
  if (!p) return undefined
  const style = {}
  if (p.font_name && p.font_name !== '默认') style.fontFamily = p.font_name
  if (p.font_size_pt) style.fontSize = `${p.font_size_pt}pt`
  if (p.bold) style.fontWeight = 'bold'
  if (p.italic) style.fontStyle = 'italic'
  if (p.alignment) style.textAlign = p.alignment
  if (p.indent_pt) style.paddingLeft = `${Math.min(p.indent_pt, 48)}pt`
  return Object.keys(style).length ? style : undefined
}

export default function FormatInfoSummary({ formatInfo }) {
  if (!formatInfo || (!formatInfo.default_body && !formatInfo.heading_styles?.length)) {
    return null
  }
  return (
    <div className="format-info-summary">
      <h4>文档格式信息</h4>
      {formatInfo.default_body ? (
        <p className="muted format-info-line">
          <strong>正文：</strong>{fmtStyle(formatInfo.default_body)}
        </p>
      ) : null}
      {(formatInfo.heading_styles || []).map((h) => (
        <p key={h.level} className="muted format-info-line">
          <strong>{`标题 ${h.level}：`}</strong>{fmtStyle(h)}
        </p>
      ))}
    </div>
  )
}
