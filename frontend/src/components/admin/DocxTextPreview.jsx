import React from 'react'

const PLACEHOLDER_RE = /\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g

export function renderPlaceholderText(text) {
  if (!text) return text
  const parts = []
  let last = 0
  let match
  const re = new RegExp(PLACEHOLDER_RE.source, 'g')
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index))
    }
    parts.push(
      <mark
        key={`${match.index}-${match[1]}`}
        className="placeholder-token"
        title={`占位符字段：${match[1]}`}
      >
        {match[0]}
      </mark>,
    )
    last = match.index + match[0].length
  }
  if (last < text.length) {
    parts.push(text.slice(last))
  }
  return parts.length ? parts : text
}

export default function DocxTextPreview({ paragraphs = [], truncated = false }) {
  if (!paragraphs.length) {
    return <div className="admin-empty">未能提取正文内容</div>
  }
  return (
    <div className="preview-doc preview-text admin-template-text">
      {paragraphs.map((p, i) => (
        p.is_heading ? (
          <div key={i} className={`preview-h level-${Math.min(p.level || 1, 3)}`}>
            {renderPlaceholderText(p.text)}
          </div>
        ) : (
          <p key={i} className="preview-p">{renderPlaceholderText(p.text)}</p>
        )
      ))}
      {truncated ? <p className="muted preview-truncated">内容较长，此处仅展示前 800 段；完整版请下载 DOCX。</p> : null}
    </div>
  )
}
