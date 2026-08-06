import React, { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAdminList } from '../../hooks/useAdminList'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminToolbar from '../../components/admin/AdminToolbar'
import AdminEmptyState from '../../components/admin/AdminEmptyState'
import Pagination from '../../components/Pagination'
import { TEMPLATE_CODES, TEMPLATE_KINDS } from '../../constants/admin'

export default function TemplatesListPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('template')

  const fetchFn = useCallback(({ page, pageSize, q, kind, enabled }) =>
    api.adminTemplates({ page, pageSize, q, kind, enabled }), [])

  const {
    items, total, page, setPage, pageSize, search, setSearch,
    filters, setFilters, loading, totalPages,
  } = useAdminList(fetchFn, { initialFilters: { kind: 'template', enabled: '' } })

  const tabs = useMemo(() => ([
    { id: 'template', label: '工程化模板', kind: 'template' },
    { id: 'history', label: '历史标书', kind: 'history' },
    { id: 'skeleton', label: '骨架模板', kind: 'skeleton' },
    { id: 'disabled', label: '已停用', enabled: 'false' },
  ]), [])

  const switchTab = (t) => {
    setTab(t.id)
    if (t.enabled) setFilters({ kind: '', enabled: t.enabled })
    else setFilters({ kind: t.kind, enabled: '' })
  }

  return (
    <>
      <AdminPageHeader
        title="模板管理"
        lead="工程化模板、历史标书与骨架模板。支持系统内预览、占位符查看与 DOCX 下载。"
        actions={<button type="button" onClick={() => navigate('/admin/templates/new')}>上传模板</button>}
      />
      <div className="filter-tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`filter-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => switchTab(t)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <AdminToolbar search={search} onSearchChange={setSearch} searchPlaceholder="搜索模板名称…" />
      {loading ? <div className="admin-loading">加载中…</div> : null}
      {!loading && items.length === 0 ? (
        <AdminEmptyState title="暂无模板" action={<button type="button" onClick={() => navigate('/admin/templates/new')}>上传 DOCX</button>} />
      ) : (
        <>
          <table className="data-table admin-table">
            <thead>
              <tr><th>名称</th><th>类型</th><th>代码</th><th>启用</th><th>占位符</th><th>操作</th></tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link className="linkish" to={`/admin/templates/${t.id}/preview`}>{t.name}</Link>
                  </td>
                  <td>{t.kind}</td>
                  <td>{t.template_code}</td>
                  <td>{t.enabled ? '是' : '否'}</td>
                  <td>{(t.placeholders?.list || []).length}</td>
                  <td className="admin-row-actions">
                    <Link className="linkish" to={`/admin/templates/${t.id}/preview`}>查看</Link>
                    <Link className="linkish" to={`/admin/templates/${t.id}`}>编辑</Link>
                  </td>
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
