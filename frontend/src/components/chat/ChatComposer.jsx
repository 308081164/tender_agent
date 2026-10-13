import React from 'react'
import { useAutoResizeTextarea } from '../../hooks/useAutoResizeTextarea'

/**
 * Agent 对话输入：多行、自动增高；Enter 发送，Shift+Enter 换行。
 */
export default function ChatComposer({
  value,
  onChange,
  onSend,
  loading = false,
  placeholder = '',
  compact = false,
  left = null,
  sendLabel = '发送',
  className = '',
}) {
  const textareaRef = useAutoResizeTextarea(value, { minRows: 2, maxRows: 12 })

  const handleKeyDown = (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
    e.preventDefault()
    if (!loading && value.trim()) onSend?.()
  }

  return (
    <footer className={`chat-composer${compact ? ' compact' : ''}${className ? ` ${className}` : ''}`}>
      {left}
      <textarea
        ref={textareaRef}
        className="chat-composer-input"
        rows={2}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={loading}
        aria-label="对话输入"
      />
      <button type="button" className="chat-composer-send" onClick={() => onSend?.()} disabled={loading || !value.trim()}>
        {sendLabel}
      </button>
    </footer>
  )
}
