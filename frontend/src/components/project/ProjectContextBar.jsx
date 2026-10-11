import React from 'react'

export default function ProjectContextBar({ context, onToggleChecklist, checklistOpen }) {
  if (!context) return null
  const tpl = context.template || {}
  const cl = context.field_checklist || {}
  const missing = (cl.missing_required || []).length
  const verify = (cl.needs_verify || []).length

  return (
    <div className="project-context-bar">
      <div className="project-context-main">
        <strong>{tpl.name || '未选模板'}</strong>
        <span className="tag">{tpl.mode === 'replace' ? '占位符替换' : 'AI 创作'}</span>
        {tpl.placeholder_count != null ? (
          <span className="muted">占位符 {tpl.placeholder_count}</span>
        ) : null}
      </div>
      <div className="project-context-stats">
        <span>待填 {missing}</span>
        <span className={verify ? 'tag-warn' : ''}>待核实 {verify}</span>
        <button type="button" className="ghost tiny" onClick={onToggleChecklist}>
          {checklistOpen ? '收起清单' : '待填清单'}
        </button>
      </div>
    </div>
  )
}
