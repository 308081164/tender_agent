import React, { useEffect, useState } from 'react'
import { api } from '../../api/client'

/**
 * 字段驱动编辑，与左侧清单联动。Word 正文在「可编辑」页用内置 OnlyOffice 打开。
 */
export default function ProjectFieldEditorPane({
  projectId,
  context,
  onSaved,
  onFollowup,
  showToast,
}) {
  const cl = context?.field_checklist || {}
  const [values, setValues] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const next = {}
    ;(cl.filled || []).forEach((f) => { next[f.key] = f.value || '' })
    ;(cl.missing_required || []).forEach((f) => { next[f.key] = '' })
    ;(cl.needs_verify || []).forEach((f) => { next[f.key] = f.value || '' })
    setValues(next)
  }, [context])

  const rows = [
    ...(cl.missing_required || []).map((f) => ({ ...f, status: 'missing' })),
    ...(cl.needs_verify || []).map((f) => ({ ...f, status: 'verify' })),
    ...(cl.filled || []).slice(0, 12).map((f) => ({ ...f, status: 'filled' })),
  ]

  const save = async () => {
    if (!projectId || saving) return
    setSaving(true)
    try {
      const payload = { ...values }
      await api.updateFields(projectId, payload)
      showToast?.('字段已保存，正在刷新预览…')
      await onSaved?.()
      const fu = await api.projectWorkspaceFollowup(projectId, true)
      if (fu?.assistant_message) onFollowup?.(fu.assistant_message)
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (!context) {
    return <div className="doc-workspace-empty"><p className="muted">加载项目上下文…</p></div>
  }

  return (
    <div className="project-field-editor-pane">
      <p className="muted tiny">
        字段驱动编辑：修改后保存将重渲染草稿并刷新 PDF；待核实项保存后请在清单中点「确认」。
      </p>
      <div className="field-editor-list">
        {rows.length === 0 ? (
          <p className="muted">暂无字段清单，请先在向导中确认模板与字段模块。</p>
        ) : (
          rows.map((f) => (
            <label key={f.key} className={`field-editor-row status-${f.status}`}>
              <span className="field-editor-label">
                {f.name}
                {f.status === 'missing' ? <em className="req">必填</em> : null}
                {f.status === 'verify' ? <em className="verify">待核实</em> : null}
              </span>
              <input
                value={values[f.key] ?? ''}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.status === 'missing' ? '请填写' : ''}
              />
            </label>
          ))
        )}
      </div>
      <div className="field-editor-actions">
        <button type="button" onClick={save} disabled={saving || rows.length === 0}>
          {saving ? '保存中…' : '保存并重渲染'}
        </button>
      </div>
    </div>
  )
}
