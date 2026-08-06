import React from 'react'

export default function AdminSortableHeader({ label, field, sortBy, sortDir, onSort }) {
  const active = sortBy === field
  const indicator = active ? (sortDir === 'asc' ? '↑' : '↓') : '↕'
  return (
    <th className="sortable-th-cell">
      <button
        type="button"
        className={`sortable-th ${active ? 'active' : ''}`}
        onClick={() => onSort(field)}
        title={active ? `当前：${sortDir === 'asc' ? '升序' : '降序'}，点击切换` : `按${label}排序`}
      >
        <span>{label}</span>
        <span className="sortable-th-icon" aria-hidden>{indicator}</span>
      </button>
    </th>
  )
}
