import React from 'react'
import { CardShell } from './CardShell'

export default function ConfirmCard({ card, message, acting, onAction }) {
  const { message: text, confirm_label, cancel_label, confirm_action, cancel_action } = card.payload || {}
  const active = card.state === 'active'

  return (
    <CardShell
      card={card}
      footer={active ? (
        <>
          <button type="button" className="ghost" disabled={acting}
            onClick={() => onAction(message, card, cancel_action, {})}>
            {cancel_label || '取消'}
          </button>
          <button type="button" disabled={acting}
            onClick={() => onAction(message, card, confirm_action, {})}>
            {acting ? '处理中…' : (confirm_label || '确认')}
          </button>
        </>
      ) : null}
    >
      {text ? <p className="chat-card-text">{text}</p> : null}
    </CardShell>
  )
}
