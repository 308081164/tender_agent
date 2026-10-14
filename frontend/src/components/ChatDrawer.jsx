import React from 'react'
import { formatTime } from '../utils/format'
import ChatTranscript from './chat/ChatTranscript'
import ChatAttachmentControls from './chat/ChatAttachmentControls'
import ChatComposer from './chat/ChatComposer'
import ComposerContextBar from './chat/ComposerContextBar'

export default function ChatDrawer({
  open,
  onClose,
  sessions,
  sessionId,
  messages,
  chatInput,
  setChatInput,
  webSearch = false,
  onToggleWebSearch,
  askChat,
  loading,
  showHistory,
  setShowHistory,
  onNewChat,
  onSelectSession,
  onCardAction,
  actingCardId,
  onUploadFiles,
  onPickFolderFiles,
  onImportFolderPath,
  pendingMaterials = [],
  onRemoveAttachment,
  replyStreaming = false,
  showToast,
  boundProjectId = null,
  workspace = {},
  onWorkspaceDirChange,
  mentions = [],
  mentionItems = [],
  onMentionQuery,
  onPickMention,
  onRemoveMention,
}) {
  const workspaceDir = (workspace?.workspace_dir || '').trim()
  if (!open) return null

  return (
    <div className="chat-drawer-root">
      <div className="chat-drawer-mask" onClick={onClose} />
      <aside className="chat-drawer" role="dialog" aria-label={boundProjectId ? '标书 Copilot' : '企业问答'}>
        <header className="chat-drawer-head">
          <div>
            <div className="wizard-kicker">{boundProjectId ? '标书 Copilot' : '企业问答'}</div>
            <h3>{boundProjectId ? '项目助手' : '智能助手'}</h3>
          </div>
          <div className="chat-drawer-tools">
            <button type="button" className="ghost" onClick={onNewChat} disabled={loading}>
              New Chat
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setShowHistory((v) => !v)}
            >
              {showHistory ? '返回对话' : '历史'}
            </button>
            <a className="ghost linkish" href="/chat" onClick={(e) => { e.preventDefault(); onClose(); window.location.href = '/chat' }}>全屏模式</a>
            <button type="button" className="ghost" onClick={onClose} aria-label="关闭">
              ×
            </button>
          </div>
        </header>

        {showHistory ? (
          <div className="chat-history-list">
            {sessions.length === 0 && <div className="empty">暂无历史对话</div>}
            {sessions.map((s) => (
              <button
                type="button"
                key={s.id}
                className={`chat-history-item ${sessionId === s.id ? 'active' : ''}`}
                onClick={() => onSelectSession(s.id)}
              >
                <strong>{s.title || `会话 #${s.id}`}</strong>
                <span>{formatTime(s.updated_at || s.created_at)}</span>
              </button>
            ))}
          </div>
        ) : (
          <>
            <div className="chat-drawer-messages">
              <ChatTranscript
                messages={messages}
                loading={loading}
                streaming={replyStreaming}
                onCardAction={onCardAction}
                actingCardId={actingCardId}
                empty={(
                  <p className="chat-empty-intro">
                    {boundProjectId
                      ? '你好，我是标书 Copilot，已绑定当前项目。可问模板、缺项与编写要求；附件会先留在输入框，发送后显示为资料芯片。'
                      : '你好，我是标书智能体助手。可询问资质、业绩、人员，或打开项目页后在此继续 Copilot 对话。'}
                  </p>
                )}
              />
            </div>
            <ChatComposer
              className="chat-drawer-input"
              value={chatInput}
              onChange={setChatInput}
              onSend={askChat}
              loading={loading}
              attachments={pendingMaterials}
              onRemoveAttachment={onRemoveAttachment}
              mentions={mentions}
              mentionItems={mentionItems}
              onMentionQuery={onMentionQuery}
              onPickMention={onPickMention}
              onRemoveMention={onRemoveMention}
              placeholder={webSearch ? '联网检索公开资料，回复会附来源链接…' : '可粘贴文件夹路径并说明「读取录入」…'}
              webSearch={webSearch}
              onToggleWebSearch={onToggleWebSearch}
              contextBar={(
                <ComposerContextBar
                  workspaceDir={workspaceDir}
                  onWorkspaceDirChange={onWorkspaceDirChange}
                  disabled={loading}
                  showProjectPicker={!boundProjectId}
                />
              )}
              left={(
                <ChatAttachmentControls
                  compact
                  disabled={loading}
                  showToast={showToast}
                  onUploadFiles={onUploadFiles}
                  onPickFolderFiles={onPickFolderFiles}
                  onImportFolderPath={onImportFolderPath}
                  onImportFolderZip={(file) => onUploadFiles?.([file])}
                />
              )}
            />
          </>
        )}
      </aside>
    </div>
  )
}
