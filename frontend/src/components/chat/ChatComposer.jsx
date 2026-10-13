import React from 'react'
import { useAutoResizeTextarea } from '../../hooks/useAutoResizeTextarea'

/**
 * Agent 对话输入：现代卡片式 Composer；Enter 发送，Shift+Enter 换行。
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
  contextBar = null,
  loadingHint = null,
  innerPrefix = null,
}) {
  const textareaRef = useAutoResizeTextarea(value, { minRows: 2, maxRows: 12 })

  const handleKeyDown = (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
    e.preventDefault()
    if (!loading && value.trim()) onSend?.()
  }

  return (
    <footer className={`chat-composer-shell${compact ? ' compact' : ''}${className ? ` ${className}` : ''}`}>
      {contextBar}
      <div className="composer-card">
        {loadingHint ? <div className="composer-loading-hint">{loadingHint}</div> : null}
        {innerPrefix}
        <textarea
          ref={textareaRef}
          className="composer-card-input"
          rows={2}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={loading}
          aria-label="对话输入"
        />
        <div className="composer-card-toolbar">
          <div className="composer-card-toolbar-left">{left}</div>
          <button
            type="button"
            className="composer-card-send"
            onClick={() => onSend?.()}
            disabled={loading || !value.trim()}
          >
            {sendLabel}
          </button>
        </div>
      </div>
    </footer>
  )
}
