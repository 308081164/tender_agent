import React, { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAdminList } from '../../hooks/useAdminList'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminToolbar from '../../components/admin/AdminToolbar'
import AdminEmptyState from '../../components/admin/AdminEmptyState'
import AdminSortableHeader from '../../components/admin/AdminSortableHeader'
import Pagination from '../../components/Pagination'

const STATUS_FILTERS = [
  { value: '', label: '全部状态' },
  { value: 'expired', label: '过期' },
  { value: 'expiring', label: '临期（90天内）' },
  { value: 'normal', label: '正常' },
]

export default function QualificationsListPage() {
  const navigate = useNavigate()
  const [categories, setCategories] = useState([])

  useEffect(() => {
    api.qualCategories().then(setCategories).catch(() => {})
  }, [])

  const fetchFn = useCallback(({ page, pageSize, q, category, status, sortBy, sortDir }) =>
    api.adminQuals({ page, pageSize, q, category, status, sortBy, sortDir }), [])

  const {
    items, total, page, setPage, pageSize, search, setSearch,
    filters, setFilters, loading, totalPages,
  } = useAdminList(fetchFn, {
    initialFilters: { category: '', status: '', sortBy: '', sortDir: 'asc' },
  })

  const toggleSort = (field) => {
    setFilters((prev) => {
      const next = { ...prev }
      if (prev.sortBy !== field) {
        next.sortBy = field
        next.sortDir = 'asc'
        return next
      }
      next.sortDir = prev.sortDir === 'asc' ? 'desc' : 'asc'
      return next
    })
  }

  const clearSort = () => {
    setFilters((prev) => ({ ...prev, sortBy: '', sortDir: 'asc' }))
  }

  return (
    <>
      <AdminPageHeader
        title="资质库"
        lead="七大类资质材料，支持有效期管理与文件预览。"
        actions={<button type="button" onClick={() => navigate('/admin/qualifications/new')}>新增资质</button>}
      />
      <AdminToolbar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="搜索名称、机构或关键词…"
        filters={(
          <>
            <select value={filters.category || ''} onChange={(e) => setFilters((prev) => ({ ...prev, category: e.target.value }))}>
              <option value="">全部分类</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={filters.status || ''} onChange={(e) => setFilters((prev) => ({ ...prev, status: e.target.value }))}>
              {STATUS_FILTERS.map((s) => (
                <option key={s.value || 'all'} value={s.value}>{s.label}</option>
              ))}
            </select>
            {filters.sortBy ? (
              <button type="button" className="ghost-btn sort-reset-btn" onClick={clearSort}>
                清除排序
              </button>
            ) : null}
          </>
        )}
      />
      {loading ? <div className="admin-loading">加载中…</div> : null}
      {!loading && items.length === 0 ? (
        <AdminEmptyState title="暂无资质" action={<button type="button" onClick={() => navigate('/admin/qualifications/new')}>新增资质</button>} />
      ) : (
        <>
          <table className="data-table admin-table">
            <thead>
              <tr>
                <th>分类</th>
                <th>名称</th>
                <AdminSortableHeader
                  label="有效期"
                  field="valid_to"
                  sortBy={filters.sortBy}
                  sortDir={filters.sortDir}
                  onSort={toggleSort}
                />
                <th>章节提示</th>
                <AdminSortableHeader
                  label="状态"
                  field="status"
                  sortBy={filters.sortBy}
                  sortDir={filters.sortDir}
                  onSort={toggleSort}
                />
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((q) => (
                <tr key={q.id} className={q.expired ? 'row-expired' : q.expiring ? 'row-expiring' : ''}>
                  <td>{q.category}</td>
                  <td>{q.name}</td>
                  <td>{q.is_long_term ? '长期' : (q.valid_to || '—')}</td>
                  <td>{q.section_hint || '—'}</td>
                  <td>
                    {q.expired ? <span className="level-red">过期</span> : null}
                    {q.expiring ? <span className="level-yellow">临期</span> : null}
                    {!q.expired && !q.expiring ? <span className="level-green">正常</span> : null}
                  </td>
                  <td><Link className="linkish" to={`/admin/qualifications/${q.id}`}>查看</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
        </>
      )}
    </>
  )
}
