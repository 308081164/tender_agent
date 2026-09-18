import React, { useState } from 'react'
import { CardShell } from './CardShell'

export default function RevisionCollectCard({ card, message, acting, onAction }) {
  const { submit_action, finish_action, placeholder } = card.payload || {}
  const [instruction, setInstruction] = useState('')
  const active = card.state === 'active'

  return (
    <CardShell
      card={card}
      footer={active ? (
        <>
          <button type="button" className="ghost" disabled={acting}
            onClick={() => onAction(message, card, finish_action, {})}>
            完成修订
          </button>
          <button type="button" disabled={acting || !instruction.trim()}
            onClick={() => onAction(message, card, submit_action, { instruction })}>
            {acting ? '修订中…' : '提交修订'}
          </button>
        </>
      ) : null}
    >
      <div className="field">
        <label>修订指令</label>
        <textarea
          rows={3}
          value={instruction}
          disabled={!active || acting}
          placeholder={placeholder || '描述要如何修改当前标书…'}
          onChange={(e) => setInstruction(e.target.value)}
          style={{ width: '100%' }}
        />
      </div>
      <div className="chat-card-hint">也可直接在对话框输入修订要求；发送「完成」结束修订。</div>
    </CardShell>
  )
}
