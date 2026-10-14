import React from 'react'

export default function ChatAttachmentChip({ item, onRemove }) {
  const count = Number(item?.count) > 1 ? Number(item.count) : 0
  const title = count ? `${item.name} · ${count} 个文件` : item.name
  return (
    <span className="attach-chip" title={title}>
      <span className="attach-chip-type">{item.type || (item.kind === 'folder' ? '文件夹' : '文件')}</span>
      <span className="attach-chip-name">{item.name}</span>
      {onRemove ? (
        <button
          type="button"
          className="attach-chip-remove"
          aria-label={`移除 ${item.name}`}
          onClick={onRemove}
        >
          ×
        </button>
      ) : null}
    </span>
  )
}
