import React from 'react'

export default function AdminEmptyState({ title = '暂无数据', hint, action }) {
  return (
    <div className="admin-empty">
      <h3>{title}</h3>
      {hint ? <p>{hint}</p> : null}
      {action}
    </div>
  )
}
