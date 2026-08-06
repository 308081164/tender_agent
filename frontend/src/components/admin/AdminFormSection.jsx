import React from 'react'

export default function AdminFormSection({ title, children }) {
  return (
    <section className="admin-form-section">
      {title ? <h3>{title}</h3> : null}
      <div className="admin-form-grid">{children}</div>
    </section>
  )
}

export function AdminField({ label, children, full, hint }) {
  return (
    <label className={`field ${full ? 'full' : ''}`}>
      <span>{label}{hint ? <small className="field-hint"> {hint}</small> : null}</span>
      {children}
    </label>
  )
}
