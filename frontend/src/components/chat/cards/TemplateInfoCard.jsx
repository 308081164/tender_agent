import React from 'react'
import { CardShell } from './CardShell'

export default function TemplateInfoCard({ card }) {
  const p = card.payload || {}
  return (
    <CardShell card={card}>
      <div className="info-grid">
        <div className="info-row"><span>模板名称</span><strong>{p.name}</strong></div>
        <div className="info-row"><span>应用映射</span><strong>{p.applied_count} 处</strong></div>
        <div className="info-row"><span>占位符</span><strong>{p.placeholder_count} 个</strong></div>
      </div>
      {p.placeholders?.length ? (
        <div className="info-tags">
          {p.placeholders.slice(0, 10).map((k) => <code key={k}>{`{{${k}}}`}</code>)}
          {p.placeholders.length > 10 ? <span className="chat-card-hint">等</span> : null}
        </div>
      ) : null}
    </CardShell>
  )
}
