import React, { useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAdminList } from '../../hooks/useAdminList'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminToolbar from '../../components/admin/AdminToolbar'
import AdminEmptyState from '../../components/admin/AdminEmptyState'
import Pagination from '../../components/Pagination'

export default function FaqsListPage() {
  const navigate = useNavigate()
  const fetchFn = useCallback(({ page, pageSize, q, category }) =>
    api.adminFaqs({ page, pageSize, q, category }), [])

  const {
    items, total, page, setPage, pageSize, search, setSearch,
    filters, setFilters, loading, totalPages,
  } = useAdminList(fetchFn)

  return (
    <>
      <AdminPageHeader
        title="FAQ 知识库"
        lead="企业问答内容，保存后 Chatbot 立即生效。"
        actions={<button type="button" onClick={() => navigate('/admin/faqs/new')}>新增 FAQ</button>}
      />
      <AdminToolbar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="搜索问题或答案…"
        filters={(
          <input
            placeholder="类别筛选"
            value={filters.category || ''}
            onChange={(e) => setFilters({ category: e.target.value })}
          />
        )}
      />
      {loading ? <div className="admin-loading">加载中…</div> : null}
      {!loading && items.length === 0 ? (
        <AdminEmptyState title="暂无 FAQ" action={<button type="button" onClick={() => navigate('/admin/faqs/new')}>新增 FAQ</button>} />
      ) : (
        <>
          <table className="data-table admin-table">
            <thead>
              <tr><th>类别</th><th>问题</th><th>答案摘要</th><th>模板</th><th /></tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.id}>
                  <td>{f.category}</td>
                  <td>{f.question}</td>
                  <td className="truncate-cell">{(f.answer || '').slice(0, 80)}</td>
                  <td>{f.template_code}</td>
                  <td><Link className="linkish" to={`/admin/faqs/${f.id}`}>查看</Link></td>
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
