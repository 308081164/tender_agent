import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'
import TemplatePreviewPanel from '../../components/admin/TemplatePreviewPanel'
import FormatInfoSummary from '../../components/admin/FormatInfoSummary'
import { templateSourceLabel } from '../../constants/admin'

export default function TemplateDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { showToast, refreshBaseData } = useApp()
  const [tpl, setTpl] = useState(null)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      api.getTemplate(id),
      api.adminTemplatePreview(id).catch(() => null),
    ])
      .then(([t, pv]) => {
        if (cancelled) return
        setTpl(t)
        setPreview(pv)
      })
      .catch((e) => showToast(e.message))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [id, showToast])

  const remove = async () => {
    await api.deleteTemplate(id)
    await refreshBaseData?.()
    showToast('模板已删除')
    navigate('/admin/templates')
  }

  if (loading) return <div className="admin-loading">加载中…</div>
  if (!tpl) return <div className="admin-empty">模板不存在</div>

  const placeholders = tpl.placeholders?.list || []

  return (
    <>
      <AdminDetailHeader
        title={tpl.name || '模板详情'}
        backTo="/admin/templates"
        onDelete={() => setConfirmDelete(true)}
        extra={(
          <>
            <button type="button" className="primary" onClick={() => navigate(`/admin/templates/${id}/engineer`)}>
              进入工程化工作台
            </button>
            <button type="button" className="ghost" onClick={() => navigate(`/admin/templates/${id}/preview`)}>
              全屏预览
            </button>
            <a className="ghost linkish" href={api.adminTemplateDownloadUrl(id)} download>下载 DOCX</a>
          </>
        )}
      />

      <div className="admin-detail-grid">
        <div className="card-block">
          <h3>基本信息</h3>
          <dl className="admin-meta-dl">
            <dt>名称</dt><dd>{tpl.name || '—'}</dd>
            <dt>说明</dt><dd>{tpl.description || '—'}</dd>
            <dt>创建方式</dt><dd>{templateSourceLabel(tpl.kind)}</dd>
            <dt>模板代码</dt><dd><code>{tpl.template_code || 'common'}</code></dd>
            <dt>状态</dt><dd>{tpl.enabled ? '已启用' : '已停用'}</dd>
            <dt>占位符数量</dt><dd>{placeholders.length}</dd>
          </dl>
          <FormatInfoSummary formatInfo={preview?.format_info} />
        </div>

        <aside className="card-block">
          <h3>占位符 ({placeholders.length})</h3>
          {placeholders.length ? (
            <ul className="admin-tag-list">
              {placeholders.map((p) => <li key={p}><code className="placeholder-tag">{`{{${p}}}`}</code></li>)}
            </ul>
          ) : (
            <p className="muted">暂无占位符。请进入工程化工作台识别并应用可变字段。</p>
          )}
          {tpl.kind === 'history' && tpl.source_snapshot ? (
            <>
              <h3 style={{ marginTop: 16 }}>智能替换快照</h3>
              <pre className="admin-pre">{JSON.stringify(tpl.source_snapshot, null, 2).slice(0, 2000)}</pre>
            </>
          ) : null}
        </aside>
      </div>

      <div className="card-block admin-template-preview-page" style={{ marginTop: 16 }}>
        <div className="placeholder-preview-legend">
          <h3 style={{ margin: 0 }}>文档预览</h3>
          <div className="legend-items">
            <span><mark className="placeholder-token">{'{{key}}'}</mark> 已应用占位符</span>
            <span><mark className="ai-marker-token">AI 标记</mark> AI 生成章节位</span>
          </div>
        </div>
        <TemplatePreviewPanel templateId={id} compact />
      </div>

      <AdminConfirmDialog
        open={confirmDelete}
        title="删除模板"
        message="删除后无法恢复，确认继续？"
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => { setConfirmDelete(false); remove() }}
      />
    </>
  )
}
