import React, { useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAdminList } from '../../hooks/useAdminList'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminToolbar from '../../components/admin/AdminToolbar'
import AdminEmptyState from '../../components/admin/AdminEmptyState'
import Pagination from '../../components/Pagination'
import { TEMPLATE_CODES } from '../../constants/admin'

export default function FieldsListPage() {
  const navigate = useNavigate()
  const fetchFn = useCallback(({ page, pageSize, q, template_code }) =>
    api.adminFields({ page, pageSize, q, template_code }), [])

  const {
    items, total, page, setPage, pageSize, search, setSearch,
    filters, setFilters, loading, totalPages,
  } = useAdminList(fetchFn)

  return (
    <>
      <AdminPageHeader
        title="字段定义"
        lead="维护标书录入字段、默认值与企业档案映射。"
        actions={<button type="button" onClick={() => navigate('/admin/fields/new')}>新增字段</button>}
      />
      <AdminToolbar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="搜索名称或 key…"
        filters={(
          <select
            value={filters.template_code || ''}
            onChange={(e) => setFilters({ template_code: e.target.value })}
          >
            <option value="">全部模板</option>
            {TEMPLATE_CODES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        )}
      />
      {loading ? <div className="admin-loading">加载中…</div> : null}
      {!loading && items.length === 0 ? (
        <AdminEmptyState title="暂无字段" hint="可新增字段或从导入页重新导入客户包。" />
      ) : (
        <>
          <table className="data-table admin-table">
            <thead>
              <tr>
                <th>名称</th><th>key</th><th>类型</th><th>模板</th><th>必填</th><th>排序</th><th />
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.id}>
                  <td>{f.name}{f.desensitized ? <span className="tag-warn"> 请核实</span> : null}</td>
                  <td><code>{f.key}</code></td>
                  <td>{f.field_type}</td>
                  <td>{f.template_code}</td>
                  <td>{f.required ? '是' : ''}</td>
                  <td>{f.sort_order}</td>
                  <td><Link className="linkish" to={`/admin/fields/${f.id}`}>查看</Link></td>
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
