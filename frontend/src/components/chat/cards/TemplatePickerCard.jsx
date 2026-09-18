import React, { useState } from 'react'
import { CardShell } from './CardShell'

export default function TemplatePickerCard({ card, message, acting, onAction }) {
  const { templates = [], select_action, cancel_action } = card.payload || {}
  const [selected, setSelected] = useState(null)
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
          <button type="button" disabled={acting || !selected}
            onClick={() => onAction(message, card, select_action, { template_id: selected })}>
            {acting ? '处理中…' : '使用此模板'}
          </button>
        </>
      ) : null}
    >
      <div className="tpl-picker-list">
        {templates.map((t) => (
          <button
            type="button"
            key={t.id}
            disabled={!active || acting}
            className={`tpl-picker-item ${selected === t.id ? 'selected' : ''}`}
            onClick={() => setSelected(t.id)}
          >
            <span className="tpl-picker-name">{t.name}</span>
            <span className="tpl-picker-meta">
              {t.kind === 'skeleton' ? '框架模板' : '工程化模板'} · {t.placeholder_count} 个占位符
            </span>
          </button>
        ))}
      </div>
    </CardShell>
  )
}
