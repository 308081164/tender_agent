import React, { useCallback, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import { useAdminList } from '../../hooks/useAdminList'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminToolbar from '../../components/admin/AdminToolbar'
import AdminEmptyState from '../../components/admin/AdminEmptyState'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'
import Pagination from '../../components/Pagination'
import { TEMPLATE_UPLOAD_OPTIONS, templateSourceLabel } from '../../constants/admin'

export default function TemplatesListPage() {
  const navigate = useNavigate()
  const { showToast, refreshBaseData } = useApp()
  const [tab, setTab] = useState('all')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [showUploadPicker, setShowUploadPicker] = useState(false)
  const [pendingUploadKind, setPendingUploadKind] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const fileRef = useRef(null)

  const fetchFn = useCallback(({ page, pageSize, q, kind, enabled }) =>
    api.adminTemplates({ page, pageSize, q, kind, enabled }), [])

  const {
    items, total, page, setPage, pageSize, search, setSearch,
    filters, setFilters, loading, totalPages, reload,
  } = useAdminList(fetchFn, { initialFilters: { kind: '', enabled: 'true' } })

  const tabs = useMemo(() => ([
    { id: 'all', label: '全部', kind: '', enabled: 'true' },
    { id: 'history', label: '基于完整标书创建', kind: 'history', enabled: 'true' },
    { id: 'blank', label: '基于空白模板创建', kind: 'blank', enabled: 'true' },
    { id: 'disabled', label: '已停用', kind: '', enabled: 'false' },
  ]), [])

  const switchTab = (t) => {
    setTab(t.id)
    setFilters({ kind: t.kind || '', enabled: t.enabled || '' })
  }

  const openUpload = () => {
    setUploadError('')
    setPendingUploadKind('')
    setShowUploadPicker(true)
  }

  const chooseUploadKind = (kind) => {
    setPendingUploadKind(kind)
    setShowUploadPicker(false)
    setTimeout(() => fileRef.current?.click(), 0)
  }

  const onUpload = async (file) => {
    if (!file || uploading) return
    const kind = pendingUploadKind
    if (!kind) {
      setUploadError('请先选择创建方式')
      setShowUploadPicker(true)
      return
    }
    setUploading(true)
    setUploadError('')
    try {
      const tpl = await api.uploadTemplate(file, { kind })
      await reload()
      await refreshBaseData?.()
      navigate(`/admin/templates/${tpl.id}/engineer`)
    } catch (e) {
      setUploadError(e.message || '上传失败')
    } finally {
      setUploading(false)
      setPendingUploadKind('')
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    try {
      await api.deleteTemplate(deleteTarget.id)
      await refreshBaseData?.()
      await reload()
      showToast(`已删除「${deleteTarget.name}」`)
      setDeleteTarget(null)
    } catch (e) {
      showToast(e.message || '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const uploadButton = (
    <button type="button" onClick={openUpload} disabled={uploading}>
      {uploading ? '上传中…' : '上传模板'}
    </button>
  )

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".docx"
        className="hidden"
        onChange={(e) => onUpload(e.target.files?.[0])}
      />
      <AdminPageHeader
        title="模板管理"
        lead="上传 Word 文档后进入工程化工作台。请先选择创建方式：完整标书需标记大量可变字段；空白模板含编写规则，生成时将全文供 AI 参考。"
        actions={uploadButton}
      />
      {uploadError ? <div className="banner err">{uploadError}</div> : null}

      {showUploadPicker ? (
        <div className="admin-dialog-backdrop" onClick={() => setShowUploadPicker(false)}>
          <div className="admin-dialog upload-kind-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>选择模板创建方式</h3>
            <p className="muted">两种方式的工程化策略不同，请按实际文档类型选择。</p>
            <div className="upload-kind-options">
              {TEMPLATE_UPLOAD_OPTIONS.map((opt) => (
                <button
                  key={opt.kind}
                  type="button"
                  className="upload-kind-option"
                  onClick={() => chooseUploadKind(opt.kind)}
                >
                  <strong>{opt.title}</strong>
                  <span>{opt.description}</span>
                </button>
              ))}
            </div>
            <div className="actions">
              <button type="button" className="ghost" onClick={() => setShowUploadPicker(false)}>取消</button>
            </div>
          </div>
        </div>
      ) : null}

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
        <AdminEmptyState title="暂无模板" action={(
          <button type="button" onClick={openUpload} disabled={uploading}>
            {uploading ? '上传中…' : '上传 DOCX'}
          </button>
        )} />
      ) : (
        <>
          <table className="data-table admin-table">
            <thead>
              <tr><th>名称</th><th>创建方式</th><th>代码</th><th>启用</th><th>占位符</th><th>操作</th></tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link className="linkish" to={`/admin/templates/${t.id}`}>{t.name}</Link>
                  </td>
                  <td>{templateSourceLabel(t.kind)}</td>
                  <td>{t.template_code}</td>
                  <td>{t.enabled ? '是' : '否'}</td>
                  <td>{(t.placeholders?.list || []).length}</td>
                  <td className="admin-row-actions">
                    <Link className="linkish" to={`/admin/templates/${t.id}`}>详情</Link>
                    <Link className="linkish" to={`/admin/templates/${t.id}/engineer`}>工程化</Link>
                    <button
                      type="button"
                      className="linkish danger-text"
                      onClick={() => setDeleteTarget(t)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
        </>
      )}

      <AdminConfirmDialog
        open={!!deleteTarget}
        title="删除模板"
        message={deleteTarget ? `确认删除「${deleteTarget.name}」？删除后无法恢复。` : ''}
        confirmLabel={deleting ? '删除中…' : '删除'}
        danger
        onCancel={() => { if (!deleting) setDeleteTarget(null) }}
        onConfirm={confirmDelete}
      />
    </>
  )
}
