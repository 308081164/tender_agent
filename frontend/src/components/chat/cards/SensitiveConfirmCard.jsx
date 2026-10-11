import React from 'react'
import { CardShell } from './CardShell'

export default function SensitiveConfirmCard({ card, message, acting, onAction }) {
  const { fields = [], confirm_action } = card.payload || {}
  const active = card.state === 'active'
  const keys = fields.map((f) => f.key)

  return (
    <CardShell
      card={card}
      footer={active ? (
        <button
          type="button"
          disabled={acting}
          onClick={() => onAction(message, card, confirm_action || 'confirm_sensitive_fields', { field_keys: keys })}
        >
          {acting ? '处理中…' : '确认以上敏感信息'}
        </button>
      ) : null}
    >
      <p className="chat-card-hint">以下字段需人工核实后方可写入或导出：</p>
      <ul>
        {fields.map((f) => (
          <li key={f.key} className="verify-field">{f.name}{f.value ? `：${f.value}` : ''}</li>
        ))}
      </ul>
    </CardShell>
  )
}
