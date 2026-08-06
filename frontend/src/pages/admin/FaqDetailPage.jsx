import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'
import AdminFormSection, { AdminField } from '../../components/admin/AdminFormSection'
import { TEMPLATE_CODES } from '../../constants/admin'

const EMPTY = { category: '', question: '', answer: '', source: '', template_code: 'common' }

export default function FaqDetailPage() {
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
    api.getFaq(id).then(setForm).catch((e) => showToast(e.message))
  }, [id, isNew, showToast])

  const save = async () => {
    setSaving(true)
    try {
      if (isNew) await api.createFaq(form)
      else await api.updateFaq(id, form)
      showToast('FAQ 已保存，Chatbot 将立即使用新答案')
      navigate('/admin/faqs')
    } catch (e) {
      showToast(e.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    await api.deleteFaq(id)
    showToast('FAQ 已删除')
    navigate('/admin/faqs')
  }

  return (
    <>
      <AdminDetailHeader
        title={isNew ? '新增 FAQ' : 'FAQ 详情'}
        backTo="/admin/faqs"
        onSave={save}
        onDelete={isNew ? null : () => setConfirmDelete(true)}
        saving={saving}
      />
      <div className="card-block">
        <AdminFormSection title="问答内容">
          <AdminField label="类别"><input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></AdminField>
          <AdminField label="模板维度">
            <select value={form.template_code} onChange={(e) => setForm({ ...form, template_code: e.target.value })}>
              {TEMPLATE_CODES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </AdminField>
          <AdminField label="问题" full><textarea rows={3} value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} /></AdminField>
          <AdminField label="答案" full><textarea rows={8} value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })} /></AdminField>
          <AdminField label="来源材料" full><input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></AdminField>
        </AdminFormSection>
      </div>
      <AdminConfirmDialog
        open={confirmDelete}
        title="删除 FAQ"
        message="删除后无法恢复，确认继续？"
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => { setConfirmDelete(false); remove() }}
      />
    </>
  )
}
