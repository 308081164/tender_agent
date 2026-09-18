import React, { useEffect, useState } from 'react'
import { api } from '../../api/client'

const FIELD_TYPES = ['文本', '日期', '金额', '数字', '选项', '多行文本']

export default function CreateFieldInlineModal({ open, suggested, onClose, onCreated }) {
  const [modules, setModules] = useState(['临场填写', '项目信息', '基本信息', '其他'])
  const [form, setForm] = useState({
    name: '',
    key: '',
    field_type: '文本',
    module: '临场填写',
    default_value: '',
    required: false,
    template_code: 'common',
    runtime_fill: true,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    api.adminFieldModules()
      .then((res) => setModules(res.modules || []))
      .catch(() => {})
  }, [open])

  useEffect(() => {
    if (!open) return
    const isRuntime = (suggested?.module || '临场填写') === '临场填写'
    setForm({
      name: suggested?.name || '',
      key: suggested?.key || '',
      field_type: suggested?.field_type || '文本',
      module: suggested?.module || '临场填写',
      default_value: suggested?.default_value || '',
      required: false,
      template_code: 'common',
      runtime_fill: isRuntime,
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
    if (!form.runtime_fill && !form.default_value.trim()) {
      setError('非临场填写字段请填写预填充信息，或勾选「临场填写」')
      return
    }
    setSaving(true)
    setError('')
    try {
      const payload = {
        name: form.name.trim(),
        key: form.key.trim(),
        field_type: form.field_type,
        module: form.runtime_fill ? '临场填写' : form.module,
        required: form.required,
        template_code: form.template_code,
        default_value: form.runtime_fill ? '' : form.default_value.trim(),
        options: form.runtime_fill ? 'runtime_fill=true' : '',
      }
      const created = await api.createField(payload)
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
            <select
              value={form.runtime_fill ? '临场填写' : form.module}
              disabled={form.runtime_fill}
              onChange={(e) => setForm((f) => ({ ...f, module: e.target.value }))}
            >
              {modules.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.runtime_fill}
              onChange={(e) => setForm((f) => ({
                ...f,
                runtime_fill: e.target.checked,
                module: e.target.checked ? '临场填写' : (f.module === '临场填写' ? '项目信息' : f.module),
                default_value: e.target.checked ? '' : f.default_value,
              }))}
            />
            临场填写（生成时再决策，预填充可留空）
          </label>
          {!form.runtime_fill ? (
            <label>
              预填充信息
              <textarea
                rows={3}
                value={form.default_value}
                onChange={(e) => setForm((f) => ({ ...f, default_value: e.target.value }))}
                placeholder="创建字段时直接填入的默认内容，生成标书时可再调整"
              />
            </label>
          ) : (
            <p className="muted runtime-hint">已勾选临场填写：该字段在生成标书时由 AI/人工现场决策填写，不预设固定值。</p>
          )}
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
