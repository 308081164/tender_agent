import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'
import AdminFormSection, { AdminField } from '../../components/admin/AdminFormSection'
import { CHECKLIST_REQUIRED, TEMPLATE_CODES } from '../../constants/admin'

const EMPTY = {
  section: '', name: '', required: '必含', chapter: '', remark: '', template_code: 'common', sort_order: 0,
}

export default function ChecklistDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { showToast } = useApp()
  const isNew = id === 'new'
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (isNew) {
      setForm(EMPTY)
      return
    }
    api.getChecklistItem(id).then(setForm).catch((e) => showToast(e.message))
  }, [id, isNew, showToast])

  const save = async () => {
    setSaving(true)
    try {
      if (isNew) await api.createChecklist(form)
      else await api.updateChecklist(id, form)
      showToast('清单条目已保存')
      navigate('/admin/checklist')
    } catch (e) {
      showToast(e.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    await api.deleteChecklist(id)
    showToast('条目已删除')
    navigate('/admin/checklist')
  }

  return (
    <>
      <AdminDetailHeader
        title={isNew ? '新增清单条目' : form.name || '清单详情'}
        backTo="/admin/checklist"
        onSave={save}
        onDelete={isNew ? null : () => setConfirmDelete(true)}
        saving={saving}
      />
      <div className="card-block">
        <AdminFormSection title="条目信息">
          <AdminField label="模板维度">
            <select value={form.template_code} onChange={(e) => setForm({ ...form, template_code: e.target.value })}>
              {TEMPLATE_CODES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </AdminField>
          <AdminField label="分区"><input value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} /></AdminField>
          <AdminField label="条目名称"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></AdminField>
          <AdminField label="要求">
            <select value={form.required} onChange={(e) => setForm({ ...form, required: e.target.value })}>
              {CHECKLIST_REQUIRED.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </AdminField>
          <AdminField label="章节"><input value={form.chapter} onChange={(e) => setForm({ ...form, chapter: e.target.value })} /></AdminField>
          <AdminField label="排序"><input type="number" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })} /></AdminField>
          <AdminField label="备注" full><textarea rows={3} value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} /></AdminField>
        </AdminFormSection>
      </div>
      <AdminConfirmDialog
        open={confirmDelete}
        title="删除条目"
        message="删除后无法恢复，确认继续？"
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => { setConfirmDelete(false); remove() }}
      />
    </>
  )
}
