import React from 'react'

export default function AdminConfirmDialog({ open, title, message, confirmLabel = '确认', danger, onConfirm, onCancel }) {
  if (!open) return null
  return (
    <div className="admin-dialog-backdrop" onClick={onCancel}>
      <div className="admin-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p>{message}</p>
        <div className="actions">
          <button type="button" className="ghost" onClick={onCancel}>取消</button>
          <button type="button" className={danger ? 'danger' : ''} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}
