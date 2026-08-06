import React from 'react'

export default function Pagination({ page, totalPages, total, pageSize, onPageChange }) {
  if (total <= pageSize) return null

  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)

  return (
    <div className="pagination">
      <span className="pagination-meta">
        显示 {from}–{to} / 共 {total} 项
      </span>
      <div className="pagination-actions">
        <button type="button" className="ghost" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          上一页
        </button>
        <span className="pagination-page">{page} / {totalPages}</span>
        <button
          type="button"
          className="ghost"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  )
}
