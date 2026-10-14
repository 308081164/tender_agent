import React from 'react'
import ChatDrawer from './ChatDrawer'

export default function FloatingChat({ chat }) {
  return (
    <>
      {!chat.open && (
        <div className="floating-chat-wrap">
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
        mentions={chat.mentions}
        mentionItems={chat.mentionItems}
        onMentionQuery={chat.onMentionQuery}
        onPickMention={chat.pickMention}
        onRemoveMention={chat.removeMention}
      />
    </>
  )
}
