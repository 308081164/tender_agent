import React, { useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAdminList } from '../../hooks/useAdminList'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminToolbar from '../../components/admin/AdminToolbar'
import AdminEmptyState from '../../components/admin/AdminEmptyState'
import Pagination from '../../components/Pagination'
import { TEMPLATE_CODES } from '../../constants/admin'

export default function ChecklistListPage() {
  const navigate = useNavigate()
  const fetchFn = useCallback(({ page, pageSize, q, template_code }) =>
    api.adminChecklist({ page, pageSize, q, template_code }), [])

  const {
    items, total, page, setPage, pageSize, search, setSearch,
    filters, setFilters, loading, totalPages,
  } = useAdminList(fetchFn)

  return (
    <>
      <AdminPageHeader
        title="校验清单"
        lead="按模板维度维护导出前条目完整性校验规则。"
        actions={<button type="button" onClick={() => navigate('/admin/checklist/new')}>新增条目</button>}
      />
      <AdminToolbar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="搜索分区或条目…"
        filters={(
          <select value={filters.template_code || ''} onChange={(e) => setFilters({ template_code: e.target.value })}>
            <option value="">全部模板</option>
            {TEMPLATE_CODES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        )}
      />
      {loading ? <div className="admin-loading">加载中…</div> : null}
      {!loading && items.length === 0 ? (
        <AdminEmptyState title="暂无清单条目" action={<button type="button" onClick={() => navigate('/admin/checklist/new')}>新增条目</button>} />
      ) : (
        <>
          <table className="data-table admin-table">
            <thead>
              <tr><th>模板</th><th>分区</th><th>条目</th><th>要求</th><th>章节</th><th /></tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>{c.template_code}</td>
                  <td>{c.section}</td>
                  <td>{c.name}</td>
                  <td>{c.required}</td>
                  <td>{c.chapter || '—'}</td>
                  <td><Link className="linkish" to={`/admin/checklist/${c.id}`}>查看</Link></td>
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
