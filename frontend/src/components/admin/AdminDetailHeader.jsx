import React from 'react'
import { useNavigate } from 'react-router-dom'

export default function AdminDetailHeader({ title, backTo, onSave, onDelete, saving, extra }) {
  const navigate = useNavigate()
  return (
    <div className="admin-detail-header">
      <button type="button" className="ghost" onClick={() => navigate(backTo)}>← 返回列表</button>
      <h2>{title}</h2>
      <div className="admin-page-actions">
        {extra}
        {onDelete ? (
          <button type="button" className="ghost danger-text" onClick={onDelete}>删除</button>
        ) : null}
        {onSave ? (
          <button type="button" onClick={onSave} disabled={saving}>保存</button>
        ) : null}
      </div>
    </div>
  )
}
