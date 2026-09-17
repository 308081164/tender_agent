import React, { useEffect, useState } from 'react'
import { api } from '../../api/client'

const FIELD_TYPES = ['文本', '日期', '金额', '数字', '选项', '多行文本']

export default function CreateFieldInlineModal({ open, suggested, onClose, onCreated }) {
  const [form, setForm] = useState({
    name: '',
    key: '',
    field_type: '文本',
    module: '临场填写',
    required: false,
    template_code: 'common',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setForm({
      name: suggested?.name || '',
      key: suggested?.key || '',
      field_type: suggested?.field_type || '文本',
      module: suggested?.module || '临场填写',
      required: false,
      template_code: 'common',
    })
    setError('')
  }, [open, suggested])

  if (!open) return null

  const submit = async (e) => {
    e.preventDefault()
    if (!form.name.trim() || !form.key.trim()) {
      setError('请填写字段名称与 key')
      return
    }
    setSaving(true)
    setError('')
    try {
      const created = await api.createField({
        ...form,
        name: form.name.trim(),
        key: form.key.trim(),
      })
      onCreated?.(created)
      onClose?.()
    } catch (err) {
      setError(err.message || '创建失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="inline-modal-backdrop" onClick={onClose}>
      <div className="inline-modal card-block" onClick={(e) => e.stopPropagation()}>
        <h3>现场创建映射字段</h3>
        <p className="muted">新字段将写入「字段定义」，可在生成标书时统一管理与填写。</p>
        <form className="inline-field-form" onSubmit={submit}>
          <label>
            显示名称
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="如：投标截止日期"
            />
          </label>
          <label>
            字段 key
            <input
              value={form.key}
              onChange={(e) => setForm((f) => ({ ...f, key: e.target.value.replace(/\s/g, '_') }))}
              placeholder="如：bid_deadline"
            />
          </label>
          <label>
            类型
            <select
              value={form.field_type}
              onChange={(e) => setForm((f) => ({ ...f, field_type: e.target.value }))}
            >
              {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label>
            所属模块
            <input
              value={form.module}
              onChange={(e) => setForm((f) => ({ ...f, module: e.target.value }))}
            />
          </label>
          {error ? <div className="form-error">{error}</div> : null}
          <div className="inline-modal-actions">
            <button type="button" className="ghost" onClick={onClose}>取消</button>
            <button type="submit" className="primary" disabled={saving}>
              {saving ? '创建中…' : '创建并绑定'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
