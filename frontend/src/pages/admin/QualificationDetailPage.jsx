import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'
import AdminFormSection, { AdminField } from '../../components/admin/AdminFormSection'
import AdminFilePreview from '../../components/admin/AdminFilePreview'

const EMPTY = {
  category: '', name: '', issuer: '', file_type: 'jpg', file_name: '',
  keywords: '', section_hint: '', sort_order: 0,
  valid_from: '', valid_to: '', is_long_term: false, ocr_text: '',
}

export default function QualificationDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { showToast, refreshBaseData } = useApp()
  const isNew = id === 'new'
  const [form, setForm] = useState(EMPTY)
  const [categories, setCategories] = useState([])
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)

  useEffect(() => {
    api.qualCategories().then(setCategories).catch(() => {})
  }, [])

  useEffect(() => {
    if (isNew) {
      setForm(EMPTY)
      return
    }
    api.getQual(id).then(setForm).catch((e) => showToast(e.message))
  }, [id, isNew, showToast])

  const save = async () => {
    setSaving(true)
    try {
      let qual
      if (isNew) {
        qual = await api.createQual(form)
        if (uploadFile) qual = await api.replaceQualFile(qual.id, uploadFile)
      } else {
        qual = await api.updateQual(id, form)
        if (uploadFile) qual = await api.replaceQualFile(id, uploadFile)
      }
      await refreshBaseData?.()
      showToast('资质已保存')
      navigate(`/admin/qualifications/${qual.id}`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    await api.deleteQual(id)
    await refreshBaseData?.()
    showToast('资质已删除')
    navigate('/admin/qualifications')
  }

  const previewUrl = !isNew && form.object_key ? api.adminQualFileUrl(id, true) : null

  return (
    <>
      <AdminDetailHeader
        title={isNew ? '新增资质' : form.name || '资质详情'}
        backTo="/admin/qualifications"
        onSave={save}
        onDelete={isNew ? null : () => setConfirmDelete(true)}
        saving={saving}
        extra={!isNew && form.object_key ? (
          <a className="ghost linkish" href={api.adminQualFileUrl(id)} download>下载原件</a>
        ) : null}
      />
      <div className="admin-detail-grid">
        <div className="card-block">
          <AdminFormSection title="基本信息">
            <AdminField label="分类">
              <input list="qual-cats" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
              <datalist id="qual-cats">{categories.map((c) => <option key={c} value={c} />)}</datalist>
            </AdminField>
            <AdminField label="名称"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></AdminField>
            <AdminField label="颁发机构"><input value={form.issuer} onChange={(e) => setForm({ ...form, issuer: e.target.value })} /></AdminField>
            <AdminField label="关键词"><input value={form.keywords} onChange={(e) => setForm({ ...form, keywords: e.target.value })} /></AdminField>
            <AdminField label="插入章节提示"><input value={form.section_hint} onChange={(e) => setForm({ ...form, section_hint: e.target.value })} /></AdminField>
            <AdminField label="排序"><input type="number" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })} /></AdminField>
          </AdminFormSection>
          <AdminFormSection title="有效期">
            <AdminField label="生效日"><input type="date" value={form.valid_from || ''} onChange={(e) => setForm({ ...form, valid_from: e.target.value })} /></AdminField>
            <AdminField label="失效日"><input type="date" value={form.valid_to || ''} onChange={(e) => setForm({ ...form, valid_to: e.target.value })} disabled={form.is_long_term} /></AdminField>
            <label className="field row"><input type="checkbox" checked={!!form.is_long_term} onChange={(e) => setForm({ ...form, is_long_term: e.target.checked })} /> 长期有效</label>
          </AdminFormSection>
          <AdminFormSection title="附件">
            <AdminField label={isNew ? '上传文件' : '替换文件'}>
              <input type="file" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} />
            </AdminField>
            {form.file_name ? <p className="muted">当前：{form.file_name}</p> : null}
          </AdminFormSection>
        </div>
        <aside className="card-block">
          <h3>文件预览</h3>
          <AdminFilePreview url={previewUrl} fileType={form.file_type} name={form.file_name || form.name} />
        </aside>
      </div>
      <AdminConfirmDialog
        open={confirmDelete}
        title="删除资质"
        message="删除后无法恢复，确认继续？"
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => { setConfirmDelete(false); remove() }}
      />
    </>
  )
}
