import React from 'react'

export function CardShell({ card, children, footer }) {
  const resolved = card.state && card.state !== 'active'
  return (
    <div className={`chat-card ${resolved ? `resolved ${card.state}` : ''}`}>
      <div className="chat-card-head">
        <strong>{card.title}</strong>
        {resolved && (
          <span className={`chat-card-state ${card.state}`}>
            {card.state === 'confirmed' ? '已确认' : card.state === 'cancelled' ? '已取消' : '已完成'}
          </span>
        )}
      </div>
      {card.result_label ? <div className="chat-card-result">{card.result_label}</div> : null}
      <div className="chat-card-body">{children}</div>
      {footer ? <div className="chat-card-foot">{footer}</div> : null}
    </div>
  )
}
