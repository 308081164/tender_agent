import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'
import AdminFormSection, { AdminField } from '../../components/admin/AdminFormSection'
import TemplatePreviewPanel from '../../components/admin/TemplatePreviewPanel'
import { TEMPLATE_CODES, TEMPLATE_KINDS } from '../../constants/admin'

export default function TemplateDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { showToast, refreshBaseData } = useApp()
  const isNew = id === 'new'
  const [form, setForm] = useState({
    name: '', description: '', template_code: 'common', kind: 'template', enabled: true,
  })
  const [file, setFile] = useState(null)
  const [tpl, setTpl] = useState(null)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (isNew) return
    api.getTemplate(id).then((t) => {
      setTpl(t)
      setForm({
        name: t.name || '',
        description: t.description || '',
        template_code: t.template_code || 'common',
        kind: t.kind || 'template',
        enabled: t.enabled !== false,
      })
    }).catch((e) => showToast(e.message))
  }, [id, isNew, showToast])

  const save = async () => {
    setSaving(true)
    try {
      if (isNew) {
        if (!file) return showToast('请选择 DOCX 文件')
        await api.uploadTemplate(file, {
          name: form.name || file.name,
          template_code: form.template_code,
          kind: form.kind,
        })
      } else {
        await api.updateTemplate(id, form)
      }
      await refreshBaseData?.()
      showToast('模板已保存')
      navigate('/admin/templates')
    } catch (e) {
      showToast(e.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    await api.deleteTemplate(id)
    await refreshBaseData?.()
    showToast('模板已删除')
    navigate('/admin/templates')
  }

  const placeholders = tpl?.placeholders?.list || []

  return (
    <>
      <AdminDetailHeader
        title={isNew ? '上传模板' : form.name || '模板详情'}
        backTo="/admin/templates"
        onSave={save}
        onDelete={isNew ? null : () => setConfirmDelete(true)}
        saving={saving}
        extra={!isNew ? (
          <>
            <button type="button" className="ghost" onClick={() => navigate(`/admin/templates/${id}/preview`)}>查看内容</button>
            <a className="ghost linkish" href={api.adminTemplateDownloadUrl(id)} download>下载 DOCX</a>
          </>
        ) : null}
      />
      {!isNew ? (
        <div className="card-block admin-template-preview-page" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>文档预览</h3>
          <TemplatePreviewPanel templateId={id} compact />
        </div>
      ) : null}
      <div className="admin-detail-grid">
        <div className="card-block">
          <AdminFormSection title="元数据">
            <AdminField label="名称"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></AdminField>
            <AdminField label="说明"><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></AdminField>
            <AdminField label="模板代码">
              <select value={form.template_code} onChange={(e) => setForm({ ...form, template_code: e.target.value })}>
                {TEMPLATE_CODES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </AdminField>
            <AdminField label="类型">
              <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} disabled={!isNew}>
                {TEMPLATE_KINDS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </AdminField>
            {!isNew ? (
              <label className="field row">
                <input type="checkbox" checked={!!form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
                启用
              </label>
            ) : (
              <AdminField label="DOCX 文件"><input type="file" accept=".docx" onChange={(e) => setFile(e.target.files?.[0] || null)} /></AdminField>
            )}
          </AdminFormSection>
        </div>
        {!isNew ? (
          <aside className="card-block">
            <h3>占位符 ({placeholders.length})</h3>
            {placeholders.length ? (
              <ul className="admin-tag-list">
                {placeholders.map((p) => <li key={p}><code>{`{{${p}}}`}</code></li>)}
              </ul>
            ) : <p className="muted">未检测到占位符</p>}
            {tpl?.kind === 'history' && tpl?.source_snapshot ? (
              <>
                <h3 style={{ marginTop: 16 }}>智能替换快照</h3>
                <pre className="admin-pre">{JSON.stringify(tpl.source_snapshot, null, 2).slice(0, 2000)}</pre>
              </>
            ) : null}
          </aside>
        ) : null}
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
