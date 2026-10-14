import React from 'react'
import { useAutoResizeTextarea } from '../../hooks/useAutoResizeTextarea'
import ChatAttachmentChip from './ChatAttachmentChip'

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
  webSearch = false,
  onToggleWebSearch,
  attachments = [],
  onRemoveAttachment,
}) {
  const textareaRef = useAutoResizeTextarea(value, { minRows: 2, maxRows: 12 })
  const canSend = !loading && (Boolean(value.trim()) || attachments.length > 0)

  const handleKeyDown = (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
    e.preventDefault()
    if (canSend) onSend?.()
  }

  return (
    <footer className={`chat-composer-shell${compact ? ' compact' : ''}${className ? ` ${className}` : ''}`}>
      {contextBar}
      <div className="composer-card">
        {loadingHint ? <div className="composer-loading-hint">{loadingHint}</div> : null}
        {innerPrefix}
        {attachments.length ? (
          <div className="composer-attach-row">
            {attachments.map((item) => (
              <ChatAttachmentChip
                key={item.id || `${item.kind}-${item.name}`}
                item={item}
                onRemove={loading ? undefined : () => onRemoveAttachment?.(item.id)}
              />
            ))}
          </div>
        ) : null}
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
          <div className="composer-card-toolbar-left">
            <button
              type="button"
              className={`composer-web-toggle${webSearch ? ' on' : ''}`}
              aria-pressed={webSearch ? 'true' : 'false'}
              title="开启后，这条消息会联网检索公开资料，并在回复里附上标题和链接"
              disabled={loading}
              onClick={() => onToggleWebSearch?.(!webSearch)}
            >
              联网
            </button>
            {left}
          </div>
          <button
            type="button"
            className="composer-card-send"
            onClick={() => onSend?.()}
            disabled={!canSend}
          >
            {sendLabel}
          </button>
        </div>
      </div>
    </footer>
  )
}
