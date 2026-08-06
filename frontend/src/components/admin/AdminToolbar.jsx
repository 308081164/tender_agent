import React from 'react'

export default function AdminToolbar({ search, onSearchChange, searchPlaceholder, filters, actions }) {
  return (
    <div className="admin-toolbar">
      {search !== undefined ? (
        <input
          className="admin-search"
          type="search"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder || '搜索…'}
        />
      ) : null}
      {filters ? <div className="admin-toolbar-filters">{filters}</div> : null}
      {actions ? <div className="admin-toolbar-actions">{actions}</div> : null}
    </div>
  )
}
