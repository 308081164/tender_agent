import React from 'react'
import { CardShell } from './CardShell'

export default function ProjectInfoCard({ card }) {
  const p = card.payload || {}
  return (
    <CardShell card={card}>
      <div className="info-grid">
        <div className="info-row"><span>标书</span><strong>{p.title}</strong></div>
        {p.template_name ? <div className="info-row"><span>模板</span><strong>{p.template_name}</strong></div> : null}
        <div className="info-row"><span>已填字段</span><strong>{p.field_count} 项</strong></div>
      </div>
    </CardShell>
  )
}
