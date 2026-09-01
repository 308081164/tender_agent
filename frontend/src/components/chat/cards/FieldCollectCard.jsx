import React, { useState } from 'react'
import { CardShell } from './CardShell'

export default function FieldCollectCard({ card, message, acting, onAction }) {
  const { fields = [], template_name, confirm_action, cancel_action } = card.payload || {}
  const [values, setValues] = useState(() => {
    const init = {}
    for (const f of fields) init[f.key] = f.default || ''
    return init
  })
  const active = card.state === 'active'
  const missingRequired = fields.filter((f) => f.required && !(values[f.key] || '').trim())

  return (
    <CardShell
      card={card}
      footer={active ? (
        <>
          <button type="button" className="ghost" disabled={acting}
            onClick={() => onAction(message, card, cancel_action, {})}>
            取消
          </button>
          <button type="button" disabled={acting || missingRequired.length > 0}
            onClick={() => onAction(message, card, confirm_action, { fields: values })}>
            {acting ? '生成中…' : '确认并生成标书'}
          </button>
        </>
      ) : null}
    >
      {template_name ? <div className="chat-card-hint" style={{ marginBottom: 10 }}>模板：{template_name}</div> : null}
      <div className="field-collect-grid">
        {fields.map((f) => (
          <div className="field" key={f.key}>
            <label>{f.name}{f.required ? ' *' : ''}</label>
            {f.options?.length ? (
              <select
                value={values[f.key] || ''}
                disabled={!active || acting}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              >
                <option value="">请选择</option>
                {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                value={values[f.key] || ''}
                disabled={!active || acting}
                placeholder={f.default || ''}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            )}
          </div>
        ))}
      </div>
      {active && missingRequired.length > 0 && (
        <div className="chat-card-hint" style={{ marginTop: 8 }}>
          待填写：{missingRequired.map((f) => f.name).join('、')}
        </div>
      )}
    </CardShell>
  )
}
