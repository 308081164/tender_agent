import React from 'react'
import { formatTime } from '../utils/format'

export default function HistoryCard({ project, onOpen, onPreview }) {
  const s = project.summary || {}
  const progressPct = Math.round((s.progress || (project.current_step || 1) / 6) * 100)
  const exported = project.status === 'exported'

  return (
    <article className="history-card">
      <div className="history-card-top">
        <span className={`status-pill ${exported ? 'exported' : 'draft'}`}>
          {s.status_label || (exported ? '已导出' : '起草中')}
        </span>
        <span className="history-time">{formatTime(project.updated_at || project.created_at)}</span>
      </div>
      <h3 onClick={() => onOpen(project)} style={{ cursor: 'pointer' }}>
        {s.project_name || project.title || `标书 #${project.id}`}
      </h3>
      <p className="history-brief" onClick={() => onOpen(project)} style={{ cursor: 'pointer' }}>
        {s.brief || '尚未填写关键信息，可继续完善。'}
      </p>
      <div className="history-meta">
        {s.tender_no ? <span>编号 {s.tender_no}</span> : null}
        {s.project_type ? <span>{s.project_type}</span> : null}
        <span>{s.step_name || `步骤 ${project.current_step}/6`}</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${progressPct}%` }} />
      </div>
      <div className="history-card-foot">
        <span>进度 {progressPct}%</span>
        <div className="history-card-actions" onClick={(e) => e.stopPropagation()}>
          {exported && (
            <button
              type="button"
              className="ghost"
              style={{ padding: '4px 12px', fontSize: 12 }}
              onClick={() => onPreview?.(project)}
            >
              预览
            </button>
          )}
          <button
            type="button"
            className="ghost"
            style={{ padding: '4px 12px', fontSize: 12 }}
            onClick={() => onOpen(project)}
          >
            继续编辑
          </button>
        </div>
      </div>
    </article>
  )
}
