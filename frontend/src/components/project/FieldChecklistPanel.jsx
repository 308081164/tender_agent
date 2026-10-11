import React from 'react'

export default function FieldChecklistPanel({ context, onConfirmSensitive }) {
  if (!context) return null
  const cl = context.field_checklist || {}

  return (
    <div className="field-checklist-panel">
      <section>
        <h4>未填必填项</h4>
        {(cl.missing_required || []).length === 0 ? (
          <p className="muted">无</p>
        ) : (
          <ul>
            {(cl.missing_required || []).map((f) => (
              <li key={f.key}>{f.name}</li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h4>待核实</h4>
        {(cl.needs_verify || []).length === 0 ? (
          <p className="muted">无</p>
        ) : (
          <ul>
            {(cl.needs_verify || []).map((f) => (
              <li key={f.key} className="verify-field">
                {f.name}
                {f.value ? `：${f.value}` : ''}
                {!f.confirmed && onConfirmSensitive ? (
                  <button type="button" className="ghost tiny" onClick={() => onConfirmSensitive([f.key])}>
                    确认
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h4>已填（节选）</h4>
        <ul>
          {(cl.filled || []).slice(0, 8).map((f) => (
            <li key={f.key}>{f.name}</li>
          ))}
        </ul>
      </section>
    </div>
  )
}
