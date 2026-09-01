import React, { useState } from 'react'
import { CardShell } from './CardShell'

export default function MappingConfirmCard({ card, message, acting, onAction }) {
  const { mappings: initial = [], existing_placeholders = [], confirm_action, cancel_action } = card.payload || {}
  const [mappings, setMappings] = useState(initial)
  const active = card.state === 'active'
  const approvedCount = mappings.filter((m) => m.approved).length

  const toggle = (idx) => {
    if (!active || acting) return
    setMappings((list) => list.map((m, i) => (i === idx ? { ...m, approved: !m.approved } : m)))
  }
  const setAll = (value) => {
    if (!active || acting) return
    setMappings((list) => list.map((m) => ({ ...m, approved: value })))
  }

  return (
    <CardShell
      card={card}
      footer={active ? (
        <>
          <span className="chat-card-hint">已选 {approvedCount}/{mappings.length}</span>
          <span style={{ flex: 1 }} />
          <button type="button" className="ghost" disabled={acting}
            onClick={() => onAction(message, card, cancel_action, {})}>
            取消
          </button>
          <button type="button" disabled={acting || approvedCount === 0}
            onClick={() => onAction(message, card, confirm_action, { mappings })}>
            {acting ? '应用中…' : `确认应用（${approvedCount}）`}
          </button>
        </>
      ) : null}
    >
      {existing_placeholders.length > 0 && (
        <div className="chat-card-hint" style={{ marginBottom: 8 }}>
          文档已有占位符：{existing_placeholders.slice(0, 6).map((k) => `{{${k}}}`).join('、')}
          {existing_placeholders.length > 6 ? ' 等' : ''}
        </div>
      )}
      {active && mappings.length > 1 && (
        <div className="chat-card-tools">
          <button type="button" className="ghost tiny" onClick={() => setAll(true)}>全选</button>
          <button type="button" className="ghost tiny" onClick={() => setAll(false)}>全不选</button>
        </div>
      )}
      <div className="mapping-list">
        {mappings.map((m, i) => (
          <label key={`${m.key}-${i}`} className={`mapping-item ${m.approved ? 'approved' : ''}`}>
            <input
              type="checkbox"
              checked={!!m.approved}
              disabled={!active || acting}
              onChange={() => toggle(i)}
            />
            <span className="mapping-texts">
              <span className="mapping-original" title={m.original_text}>{m.original_text}</span>
              <span className="mapping-arrow">→</span>
              <span className="mapping-key">{`{{${m.key}}}`}</span>
              <span className="mapping-field">{m.field_name}</span>
            </span>
          </label>
        ))}
      </div>
    </CardShell>
  )
}
