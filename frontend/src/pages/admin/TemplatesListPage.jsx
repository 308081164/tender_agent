import React, { useCallback, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAdminList } from '../../hooks/useAdminList'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminToolbar from '../../components/admin/AdminToolbar'
import AdminEmptyState from '../../components/admin/AdminEmptyState'
import Pagination from '../../components/Pagination'
import { templateSourceLabel } from '../../constants/admin'

export default function TemplatesListPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('all')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [uploadKindChoice, setUploadKindChoice] = useState(null)
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

  const resolveUploadKind = () => {
    if (tab === 'history') return 'history'
    if (tab === 'blank') return 'template'
    if (tab === 'disabled') return 'template'
    return uploadKindChoice
  }

  const openUpload = () => {
    if (tab === 'all' && !uploadKindChoice) {
      setUploadKindChoice('pending')
      return
    }
    fileRef.current?.click()
  }

  const onUpload = async (file) => {
    if (!file || uploading) return
    const kind = resolveUploadKind()
    if (!kind || kind === 'pending') {
      setUploadError('请先选择创建方式')
      return
    }
    setUploading(true)
    setUploadError('')
    try {
      const tpl = await api.uploadTemplate(file, { kind })
      await reload()
      navigate(`/admin/templates/${tpl.id}/engineer`)
    } catch (e) {
      setUploadError(e.message || '上传失败')
    } finally {
      setUploading(false)
      setUploadKindChoice(null)
      if (fileRef.current) fileRef.current.value = ''
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
        lead="上传 Word 文档后进入工程化工作台，识别占位符并生成可复用模板。"
        actions={uploadButton}
      />
      {uploadError ? <div className="banner err">{uploadError}</div> : null}
      {uploadKindChoice === 'pending' ? (
        <div className="card-block upload-kind-picker" style={{ marginBottom: 16 }}>
          <p className="muted" style={{ marginTop: 0 }}>请选择本次上传的创建方式：</p>
          <div className="upload-kind-actions">
            <button
              type="button"
              onClick={() => {
                setUploadKindChoice('history')
                setTimeout(() => fileRef.current?.click(), 0)
              }}
            >
              基于完整标书创建
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setUploadKindChoice('template')
                setTimeout(() => fileRef.current?.click(), 0)
              }}
            >
              基于空白模板创建
            </button>
            <button type="button" className="ghost" onClick={() => setUploadKindChoice(null)}>取消</button>
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
