import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'
import AdminFormSection, { AdminField } from '../../components/admin/AdminFormSection'
import { FIELD_TYPES, TEMPLATE_CODES } from '../../constants/admin'

const EMPTY = {
  name: '', key: '', field_type: '文本', required: true, default_value: '',
  options: '', module: '', validation: '', template_code: 'common', sort_order: 0,
  is_company_default: false, company_field: '', desensitized: false,
}

export default function FieldDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { showToast, refreshBaseData } = useApp()
  const isNew = id === 'new'
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (isNew) {
      setForm(EMPTY)
      return
    }
    api.getField(id).then(setForm).catch((e) => showToast(e.message))
  }, [id, isNew, showToast])

  const save = async () => {
    setSaving(true)
    try {
      if (isNew) await api.createField(form)
      else await api.updateField(id, form)
      await refreshBaseData?.()
      showToast('字段已保存')
      navigate('/admin/fields')
    } catch (e) {
      showToast(e.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    try {
      await api.deleteField(id)
      await refreshBaseData?.()
      showToast('字段已删除')
      navigate('/admin/fields')
    } catch (e) {
      showToast(e.message)
    }
  }

  return (
    <>
      <AdminDetailHeader
        title={isNew ? '新增字段' : `字段：${form.name || form.key}`}
        backTo="/admin/fields"
        onSave={save}
        onDelete={isNew ? null : () => setConfirmDelete(true)}
        saving={saving}
      />
      <div className="card-block">
        <AdminFormSection title="基本信息">
          <AdminField label="名称"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></AdminField>
          <AdminField label="英文 key"><input value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></AdminField>
          <AdminField label="类型">
            <select value={form.field_type} onChange={(e) => setForm({ ...form, field_type: e.target.value })}>
              {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </AdminField>
          <AdminField label="所属模块"><input value={form.module} onChange={(e) => setForm({ ...form, module: e.target.value })} /></AdminField>
          <AdminField label="模板维度">
            <select value={form.template_code} onChange={(e) => setForm({ ...form, template_code: e.target.value })}>
              {TEMPLATE_CODES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </AdminField>
          <AdminField label="排序"><input type="number" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })} /></AdminField>
        </AdminFormSection>
        <AdminFormSection title="默认值与校验">
          <AdminField label="默认值"><input value={form.default_value} onChange={(e) => setForm({ ...form, default_value: e.target.value })} /></AdminField>
          <AdminField label="下拉选项" hint="分号分隔"><input value={form.options} onChange={(e) => setForm({ ...form, options: e.target.value })} /></AdminField>
          <AdminField label="校验规则"><input value={form.validation} onChange={(e) => setForm({ ...form, validation: e.target.value })} /></AdminField>
          <AdminField label="企业档案字段"><input value={form.company_field} onChange={(e) => setForm({ ...form, company_field: e.target.value })} /></AdminField>
          <label className="field row"><input type="checkbox" checked={!!form.required} onChange={(e) => setForm({ ...form, required: e.target.checked })} /> 必填</label>
          <label className="field row"><input type="checkbox" checked={!!form.is_company_default} onChange={(e) => setForm({ ...form, is_company_default: e.target.checked })} /> 企业档案默认</label>
          <label className="field row"><input type="checkbox" checked={!!form.desensitized} onChange={(e) => setForm({ ...form, desensitized: e.target.checked })} /> 脱敏待核实</label>
        </AdminFormSection>
      </div>
      <AdminConfirmDialog
        open={confirmDelete}
        title="删除字段"
        message="删除后无法恢复，确认继续？"
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => { setConfirmDelete(false); remove() }}
      />
    </>
  )
}
