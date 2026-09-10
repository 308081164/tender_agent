import React from 'react'
import { CardShell } from './CardShell'

const STATUS_LABEL = {
  green: '通过',
  yellow: '有警告',
  red: '需修改',
}

export default function DocReviewCard({ card }) {
  const { status, can_export, issue_count } = card.payload || {}
  const label = STATUS_LABEL[status] || status || '未知'

  return (
    <CardShell card={card}>
      <div className="chat-card-hint">
        审阅结果：<strong>{label}</strong>
        {typeof issue_count === 'number' ? ` · 问题 ${issue_count} 项` : null}
      </div>
      <div className="chat-card-hint" style={{ marginTop: 6 }}>
        {can_export ? '当前文档达到可导出标准，仍建议在向导中复核关键章节。' : '建议进入向导第 5 步查看审阅详情并修改后再导出。'}
      </div>
    </CardShell>
  )
}
