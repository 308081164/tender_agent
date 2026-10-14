import React from 'react'
import { Link } from 'react-router-dom'
import ChatDrawer from './ChatDrawer'

export default function FloatingChat({ chat, projectPath = '' }) {
  const m = projectPath.match(/^\/projects\/(\d+)/)
  const workspaceHref = m ? `/projects/${m[1]}/workspace` : null

  return (
    <>
      {!chat.open && (
        <div className="floating-chat-wrap">
          {workspaceHref ? (
            <Link to={workspaceHref} className="floating-chat-workspace-link">
              打开创作工作台
            </Link>
          ) : null}
          <button
            type="button"
            className="floating-chat-btn"
            onClick={chat.openDrawer}
            aria-label="打开 AI 助手"
          >
            <span className="floating-chat-icon">AI</span>
            <span className="floating-chat-label">AI 助手</span>
          </button>
        </div>
      )}
      <ChatDrawer
        open={chat.open}
        onClose={chat.closeDrawer}
        workspaceHref={workspaceHref}
        sessions={chat.sessions}
        sessionId={chat.sessionId}
        messages={chat.messages}
        chatInput={chat.chatInput}
        setChatInput={chat.setChatInput}
        webSearch={chat.webSearch}
        onToggleWebSearch={chat.setWebSearch}
        askChat={chat.askChat}
        loading={chat.loading}
        replyStreaming={chat.replyStreaming}
        pendingMaterials={chat.pendingMaterials}
        onRemoveAttachment={chat.removePendingMaterial}
        showHistory={chat.showHistory}
        setShowHistory={chat.setShowHistory}
        onNewChat={chat.newChat}
        onSelectSession={chat.loadSession}
        onCardAction={chat.handleCardAction}
        actingCardId={chat.actingCardId}
        onUploadFiles={chat.stageFiles}
        onPickFolderFiles={chat.stageFolderFiles}
        onImportFolderPath={chat.stageFolderPath}
        showToast={chat.showToast}
        boundProjectId={chat.boundProjectId}
        workspace={chat.workspace}
        onWorkspaceDirChange={chat.patchWorkspaceDir}
      />
    </>
  )
}
