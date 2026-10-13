import React from 'react'
import { Link } from 'react-router-dom'
import { formatTime } from '../utils/format'
import ChatMessageBubble from './chat/ChatMessageBubble'
import ChatAttachmentControls from './chat/ChatAttachmentControls'
import ChatComposer from './chat/ChatComposer'
import ComposerContextBar from './chat/ComposerContextBar'

export default function ChatDrawer({
  open,
  onClose,
  workspaceHref,
  sessions,
  sessionId,
  messages,
  chatInput,
  setChatInput,
  askChat,
  loading,
  showHistory,
  setShowHistory,
  onNewChat,
  onSelectSession,
  onCardAction,
  actingCardId,
  onUploadFiles,
  onImportFolderPath,
  showToast,
  boundProjectId = null,
  workspace = {},
  onWorkspaceDirChange,
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
            {workspaceHref ? (
              <Link className="ghost linkish" to={workspaceHref} onClick={onClose}>创作工作台</Link>
            ) : null}
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
              {messages.length === 0 && (
                <div className="msg bot">
                  {boundProjectId
                    ? '你好，我是标书 Copilot，已绑定当前项目。可问模板、缺项与编写要求；支持 📎 上传招标文件与 📁 选择资质文件夹。'
                    : '你好，我是标书智能体助手。可询问资质、业绩、人员，或打开项目页后在此继续 Copilot 对话。'}
                </div>
              )}
              {messages.map((m, i) => (
                <ChatMessageBubble
                  key={m.id || i}
                  message={m}
                  onCardAction={onCardAction}
                  actingCardId={actingCardId}
                />
              ))}
              {loading && <div className="msg bot">思考中…</div>}
            </div>
            <ChatComposer
              className="chat-drawer-input"
              value={chatInput}
              onChange={setChatInput}
              onSend={askChat}
              loading={loading}
              loadingHint={loading ? '思考中…' : null}
              placeholder="可粘贴文件夹路径并说明「读取录入」…"
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
