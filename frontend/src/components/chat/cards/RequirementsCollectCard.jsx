import React, { useState } from 'react'
import { CardShell } from './CardShell'

export default function RequirementsCollectCard({ card, message, acting, onAction }) {
  const { template_name, confirm_action, cancel_action, placeholder } = card.payload || {}
  const [requirements, setRequirements] = useState('')
  const active = card.state === 'active'

  return (
    <CardShell
      card={card}
      footer={active ? (
        <>
          <button type="button" className="ghost" disabled={acting}
            onClick={() => onAction(message, card, cancel_action, {})}>
            取消
          </button>
          <button type="button" disabled={acting || !requirements.trim()}
            onClick={() => onAction(message, card, confirm_action, { requirements })}>
            {acting ? '创作中…' : '确认并智能创作'}
          </button>
        </>
      ) : null}
    >
      {template_name ? <div className="chat-card-hint" style={{ marginBottom: 10 }}>模板：{template_name}</div> : null}
      <div className="field">
        <label>编写要求 *</label>
        <textarea
          rows={5}
          value={requirements}
          disabled={!active || acting}
          placeholder={placeholder || '请描述章节重点、风格与约束…'}
          onChange={(e) => setRequirements(e.target.value)}
          style={{ width: '100%', resize: 'vertical' }}
        />
      </div>
    </CardShell>
  )
}
