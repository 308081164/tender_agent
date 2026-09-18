import React from 'react'
import { CardShell } from './CardShell'

const STATUS_LABEL = {
  green: '通过',
  yellow: '有警告',
  red: '需修改',
}

export default function DocReviewCard({ card }) {
  const { status, can_export, issue_count, warning_count, issues = [], warnings = [] } = card.payload || {}
  const label = STATUS_LABEL[status] || status || '未知'

  return (
    <CardShell card={card}>
      <div className="chat-card-hint">
        审阅结果：<strong>{label}</strong>
        {typeof issue_count === 'number' ? ` · 问题 ${issue_count} 项` : null}
        {typeof warning_count === 'number' ? ` · 警告 ${warning_count} 项` : null}
      </div>
      <div className="chat-card-hint" style={{ marginTop: 6 }}>
        {can_export ? '当前文档达到可导出标准，仍建议在向导中复核关键章节。' : '建议进入向导第 5 步查看审阅详情并修改后再导出。'}
      </div>
      {issues.length > 0 && (
        <ul className="review-issue-list" style={{ marginTop: 10, paddingLeft: 18 }}>
          {issues.map((it, i) => (
            <li key={i} style={{ color: 'var(--danger, #c0392b)' }}>{it.message || JSON.stringify(it)}</li>
          ))}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="review-issue-list" style={{ marginTop: 8, paddingLeft: 18 }}>
          {warnings.map((it, i) => (
            <li key={i} style={{ color: 'var(--warn, #b8860b)' }}>{it.message || JSON.stringify(it)}</li>
          ))}
        </ul>
      )}
    </CardShell>
  )
}
