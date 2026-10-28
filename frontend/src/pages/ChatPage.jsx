import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import BackChevron from '../components/chat/BackChevron'
import ChatTranscript from '../components/chat/ChatTranscript'
import ChatSessionSidebar from '../components/chat/ChatSessionSidebar'
import DocumentWorkspace from '../components/chat/DocumentWorkspace'
import ChatAttachmentControls from '../components/chat/ChatAttachmentControls'
import ChatComposer from '../components/chat/ChatComposer'
import ComposerContextBar from '../components/chat/ComposerContextBar'
import DocWorkspaceSidebarToggle from '../components/chat/DocWorkspaceSidebarToggle'
import WorkspaceTreeSlidePanel from '../components/chat/WorkspaceTreeSlidePanel'
import { useDocWorkspaceTreeOpen } from '../hooks/useDocWorkspaceTreeOpen'
import { useWorkspaceFileSelection } from '../hooks/useWorkspaceFileSelection'
import { usePendingMaterials } from '../components/chat/usePendingMaterials'
import { deliverChatMaterials } from '../components/chat/deliverChatMaterials'
import { appendStreamToken, buildAnchorPayload, keepStreamedReply } from '../components/chat/agentChatRuntime'
import { useChatMentions } from '../hooks/useChatMentions'

export default function ChatPage() {
  const { showToast } = useApp()
  const [searchParams] = useSearchParams()
  const projectParam = searchParams.get('project')
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [workspace, setWorkspace] = useState({})
  const [paragraphs, setParagraphs] = useState([])
  const [input, setInput] = useState('')
  const [webSearch, setWebSearch] = useState(false)
  const [loading, setLoading] = useState(false)
  const [features, setFeatures] = useState({ feature_cards: [], suggested_prompts: [] })
  const [selectedText, setSelectedText] = useState('')
  const [anchor, setAnchor] = useState(null)
  const [replyStreaming, setReplyStreaming] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const [actingCardId, setActingCardId] = useState(null)
  const [creatingChat, setCreatingChat] = useState(false)
  const [docPanelOpen, setDocPanelOpen] = useState(true)
  const [projects, setProjects] = useState([])
  const messagesRef = useRef(null)
  const materials = usePendingMaterials()
  const [memos, setMemos] = useState([])
  const ensureRef = useRef(null)
  const ensureForMentions = useCallback(() => ensureRef.current?.(), [])
  const mentions = useChatMentions(sessionId, ensureForMentions)

  const rememberAnchor = useCallback((next) => {
    setAnchor(next)
    setSelectedText(next?.selected_text || '')
  }, [])

  const {
    selectedPath: selectedWorkspaceFile,
    loadedFile,
    fileLoading,
    selectFile,
    clearFile,
    buildFileContext,
  } = useWorkspaceFileSelection(sessionId, showToast)

  const workspaceDir = (workspace?.workspace_dir || '').trim()
  const showFileTree = !!(workspaceDir || workspace?.project_id)
  const treeRootLabel = workspaceDir || '工程目录'
  const { treeOpen, toggleTree, setTreeOpen } = useDocWorkspaceTreeOpen({ enabled: showFileTree && docPanelOpen })

  useEffect(() => {
    const onKey = (e) => {
      if (!showFileTree || !docPanelOpen) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault()
        toggleTree()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showFileTree, docPanelOpen, toggleTree])

  const refreshWorkspace = async (id) => {
    if (!id) return
    const data = await api.getChatWorkspace(id)
    setWorkspace(data.workspace || {})
    setParagraphs(data.paragraphs || [])
  }

  const refreshSessions = async () => {
    const list = await api.listChatSessions()
    setSessions(list)
    return list
  }

  const loadSession = async (id) => {
    const data = await api.getChatSession(id)
    setSessionId(data.id)
    setMessages(data.messages || [])
    setWorkspace(data.workspace || {})
    materials.clear()
    await refreshWorkspace(id)
    setShowSessions(false)
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [list, feat, projList] = await Promise.all([
          refreshSessions(),
          api.getChatFeatures(),
          api.projects().catch(() => []),
        ])
        if (cancelled) return
        setFeatures(feat)
        setProjects(projList || [])
        const projectId = Number(projectParam)
        if (Number.isFinite(projectId) && projectId > 0) {
          const bound = await api.ensureProjectSession(projectId)
          if (cancelled) return
          try {
            await api.openProjectWorkspace(projectId)
          } catch {
            /* 开场失败时仍打开已绑定的文档 */
          }
          if (cancelled) return
          const sid = bound?.session?.id
          if (sid) {
            await loadSession(sid)
            return
          }
        }
        if (list[0]) await loadSession(list[0].id)
      } catch (e) {
        if (!cancelled) showToast(e.message)
      }
    })()
    return () => { cancelled = true }
  }, [showToast, projectParam])

  useEffect(() => {
    const el = messagesRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const ensureSession = async () => {
    if (sessionId) return sessionId
    const s = await api.createChatSession('新对话')
    setSessionId(s.id)
    await refreshSessions()
    return s.id
  }
  ensureRef.current = ensureSession

  useEffect(() => {
    const projectId = workspace?.project_id
    if (!projectId) {
      setMemos([])
      return undefined
    }
    let cancelled = false
    api.listProjectMemos(projectId)
      .then((res) => { if (!cancelled) setMemos(res.memos || []) })
      .catch(() => { if (!cancelled) setMemos([]) })
    return () => { cancelled = true }
  }, [workspace?.project_id, messages])

  const applySession = (session) => {
    if (!session) return
    setSessions((list) => [session, ...list.filter((s) => s.id !== session.id)])
    if (session.workspace) setWorkspace(session.workspace)
  }

  const send = async (text, { withMaterials = false } = {}) => {
    if (loading) return
    const staged = withMaterials ? materials.consume() : []
    const q = (text ?? input).trim()
    if (!q && !staged.length && !mentions.mentions.length) return
    setInput('')
    setLoading(true)
    const optimisticId = `tmp-${Date.now()}`
    const assistantId = `tmp-bot-${Date.now()}`
    const sentMentions = mentions.mentions
    const optimistic = {
      id: optimisticId,
      role: 'user',
      content: q,
      metadata: {
        ...(staged.length ? { attachments: staged.map(({ name, kind, type }) => ({ name, kind, type })) } : {}),
        ...(sentMentions.length ? { mentions: sentMentions } : {}),
      },
    }
    setMessages((m) => [
      ...m,
      optimistic,
      ...(q ? [{ id: assistantId, role: 'assistant', content: '' }] : []),
    ])
    if (q) setReplyStreaming(true)
    mentions.clearMentions()
    let delivered = []
    try {
      const id = await ensureSession()
      if (staged.length) {
        const uploaded = await deliverChatMaterials(api, id, staged)
        delivered = uploaded.messages
        if (uploaded.workspace) setWorkspace(uploaded.workspace)
        applySession(uploaded.session)
        await refreshWorkspace(id)
      }
      let textTurn = []
      if (q || sentMentions.length) {
        const ctx = {
          ...buildAnchorPayload(anchor || (selectedText ? { selected_text: selectedText } : null)),
          ...buildFileContext(),
        }
        if (webSearch) ctx.web_search = true
        if (sentMentions.length) ctx.mentions = sentMentions
        const res = await api.sendChatMessageStream(id, q, ctx, (tok, event) => {
          setMessages((m) => m.map((item) => (
            item.id === assistantId ? appendStreamToken(item, tok, event) : item
          )))
        })
        if (res.user_message) textTurn.push(res.user_message)
        if (res.assistant_message) textTurn.push(res.assistant_message)
        applySession(res.session)
        if (res.metadata?.workspace_updated || res.session?.workspace || res.metadata?.highlight_texts) {
          await refreshWorkspace(id)
        }
      }
      setMessages((m) => [
        ...m.filter((x) => x.id !== optimisticId && x.id !== assistantId),
        ...delivered,
        ...textTurn,
      ])
    } catch (e) {
      setMessages((m) => {
        const partial = m.find((x) => x.id === assistantId)
        const kept = keepStreamedReply(partial?.content, e.message)
        const base = m.filter((x) => x.id !== optimisticId && x.id !== assistantId)
        return [
          ...base,
          ...delivered,
          optimistic,
          {
            id: assistantId,
            role: 'assistant',
            content: kept,
            metadata: { ...(partial?.metadata || {}), stream_error: e.message },
          },
        ]
      })
      if (!delivered.length) materials.restore(staged)
      showToast(e.message)
    } finally {
      setReplyStreaming(false)
      setLoading(false)
    }
  }

  const newChat = async () => {
    if (creatingChat || loading) return
    setCreatingChat(true)
    try {
      const s = await api.createChatSession('新对话')
      setSessionId(s.id)
      setMessages([])
      setWorkspace({})
      setParagraphs([])
      setSelectedText('')
      setAnchor(null)
      mentions.clearMentions()
      materials.clear()
      clearFile()
      setSessions((list) => [s, ...list.filter((x) => x.id !== s.id)])
      setShowSessions(false)
    } catch (e) {
      showToast(e.message)
    } finally {
      setCreatingChat(false)
    }
  }

  const patchSessionWorkspace = async (patch) => {
    const id = sessionId || (await ensureSession())
    const updated = await api.patchChatSessionWorkspace(id, patch)
    setWorkspace(updated.workspace || {})
    if (!sessionId) setSessionId(id)
    return updated
  }

  const onWorkspaceDirChange = async (dir) => {
    try {
      await patchSessionWorkspace({ workspace_dir: dir || '' })
      clearFile()
      if (sessionId) await refreshWorkspace(sessionId)
    } catch (e) {
      showToast(e.message)
    }
  }

  const onBindProject = async (pid) => {
    try {
      if (!pid) {
        await patchSessionWorkspace({ project_id: 0 })
        return
      }
      await api.ensureProjectSession(pid)
      await patchSessionWorkspace({ project_id: pid })
      if (sessionId) await refreshWorkspace(sessionId)
    } catch (e) {
      showToast(e.message)
    }
  }

  const onParagraphEdit = async (paragraphIndex, text) => {
    if (!sessionId) return
    const res = await api.updateWorkspaceParagraph(sessionId, paragraphIndex, text)
    setWorkspace(res.workspace || {})
    setParagraphs(res.paragraphs || [])
    showToast('段落已保存')
  }

  const handleCardAction = async (message, card, action, payload) => {
    if (actingCardId || loading) return
    setActingCardId(card.id)
    try {
      const id = await ensureSession()
      const res = await api.sendChatAction(id, {
        message_id: message.id,
        card_id: card.id,
        action,
        payload: payload || {},
      })
      setMessages((list) => {
        const next = list.map((m) => (
          m.id && res.acted_message && m.id === res.acted_message.id ? res.acted_message : m
        ))
        if (res.user_message) next.push(res.user_message)
        if (res.assistant_message) next.push(res.assistant_message)
        return next
      })
      if (res.session) {
        setSessions((list) => [res.session, ...list.filter((s) => s.id !== res.session.id)])
        setWorkspace(res.session.workspace || {})
      }
      if (res.metadata?.workspace_updated || res.session?.workspace) {
        await refreshWorkspace(id)
      }
    } catch (e) {
      showToast(e.message)
    } finally {
      setActingCardId(null)
    }
  }

  return (
    <div className="chat-workspace-page">
      <header className="chat-workspace-topbar">
        <Link to="/" className="chat-back-btn" aria-label="返回首页">
          <BackChevron />
          <span>返回</span>
        </Link>
        <strong>文档 Agent 工作区</strong>
        <div className="chat-workspace-top-actions">
          <button
            type="button"
            className="ghost"
            onClick={() => setDocPanelOpen((v) => !v)}
            title={docPanelOpen ? '收起文档区，仅显示对话' : '展开文档工作区'}
          >
            {docPanelOpen ? '收起文档' : '展开文档'}
          </button>
          <button type="button" className="ghost" onClick={() => setShowSessions(true)}>历史对话</button>
          <button type="button" onClick={newChat} disabled={creatingChat || loading}>
            {creatingChat ? '创建中…' : '新对话'}
          </button>
        </div>
      </header>

      <ChatSessionSidebar
        open={showSessions}
        onClose={() => setShowSessions(false)}
        sessions={sessions}
        sessionId={sessionId}
        onSelectSession={loadSession}
        onNewChat={newChat}
        creatingChat={creatingChat}
        chatBusy={loading}
      />

      <div className={`chat-workspace-split${docPanelOpen ? '' : ' doc-collapsed'}`}>
        {docPanelOpen ? (
          <section className="chat-workspace-doc">
            <div className="chat-doc-layout">
              <div className="chat-doc-main">
                {showFileTree && !treeOpen ? (
                  <button
                    type="button"
                    className="ws-tree-edge-tab"
                    onClick={() => setTreeOpen(true)}
                    title="显示工程目录 · Ctrl+B"
                    aria-label="显示工程目录"
                  >
                    目录
                  </button>
                ) : null}
                <DocumentWorkspace
                  sessionId={sessionId}
                  workspace={workspace}
                  paragraphs={paragraphs}
                  selectedText={selectedText}
                  onSelectText={(text) => rememberAnchor({ ...(anchor || {}), selected_text: text, source: 'document' })}
                  onSelectAnchor={rememberAnchor}
                  onParagraphEdit={onParagraphEdit}
                  onRefresh={() => refreshWorkspace(sessionId)}
                  onlyOfficeReady={!!(features.onlyoffice?.enabled && features.onlyoffice?.healthy)}
                  highlightTexts={workspace?.review_highlight_texts || []}
                  toolbarLeading={showFileTree ? (
                    <DocWorkspaceSidebarToggle
                      active={treeOpen}
                      onClick={toggleTree}
                      disabled={!sessionId}
                    />
                  ) : null}
                />
                <WorkspaceTreeSlidePanel
                  open={showFileTree && treeOpen}
                  onClose={() => setTreeOpen(false)}
                  sessionId={sessionId}
                  workspaceRootLabel={treeRootLabel}
                  selectedPath={selectedWorkspaceFile}
                  onSelectFile={selectFile}
                />
              </div>
            </div>
          </section>
        ) : null}

        <aside className="chat-workspace-panel">
          <div className="chat-panel-head">
            <h3>Agent 对话</h3>
            <p className="muted">语义理解 → 调用系统能力 → 结合上下文精准回复</p>
          </div>

          <div className="chat-messages-area compact" ref={messagesRef}>
            <ChatTranscript
              messages={messages}
              loading={loading}
              streaming={replyStreaming}
              onCardAction={handleCardAction}
              actingCardId={actingCardId}
              empty={(
                <div className="chat-empty compact">
                  <p className="muted chat-empty-hint">
                    可查询企业信息、检索标书。附件会先留在输入框里，发送后显示为资料芯片。
                  </p>
                  <div className="chat-prompt-chips">
                    {(features.suggested_prompts || []).map((p) => (
                      <button key={p} type="button" className="chip" onClick={() => send(p)}>{p}</button>
                    ))}
                  </div>
                </div>
              )}
            />
          </div>

          {memos.length ? (
            <ul className="project-memo-list">
              {memos.map((memo) => (
                <li key={memo.id}>
                  <span>{memo.text}</span>
                  <button
                    type="button"
                    className="ghost tiny"
                    onClick={async () => {
                      const res = await api.deleteProjectMemo(workspace.project_id, memo.id)
                      setMemos(res.memos || [])
                    }}
                  >
                    删除
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {selectedText ? (
            <div className="chat-selection-hint">
              将修改选中文本：
              <em>{selectedText.slice(0, 60)}{selectedText.length > 60 ? '…' : ''}</em>
              <button type="button" className="ghost tiny" onClick={() => setSelectedText('')}>清除</button>
            </div>
          ) : null}
          <ChatComposer
            compact
            value={input}
            onChange={setInput}
            onSend={() => send(undefined, { withMaterials: true })}
            loading={loading}
            loadingHint={fileLoading ? '正在读取工程文件…' : null}
            attachments={materials.items}
            onRemoveAttachment={materials.remove}
            mentions={mentions.mentions}
            onRemoveMention={mentions.removeMention}
            mentionItems={mentions.mentionItems}
            onMentionQuery={mentions.onMentionQuery}
            onPickMention={mentions.pickMention}
            placeholder={webSearch ? '联网检索公开资料，回复会附来源链接…' : '提问、检索标书、编写/替换指令…'}
            webSearch={webSearch}
            onToggleWebSearch={setWebSearch}
            contextBar={(
              <ComposerContextBar
                workspaceDir={workspaceDir}
                onWorkspaceDirChange={onWorkspaceDirChange}
                disabled={loading}
                showProjectPicker
                projects={projects}
                projectId={workspace?.project_id || null}
                onProjectChange={onBindProject}
                currentFile={selectedWorkspaceFile ? {
                  path: selectedWorkspaceFile,
                  charCount: loadedFile?.charCount,
                } : null}
                onClearFile={clearFile}
                fileLoading={fileLoading}
              />
            )}
            left={(
              <ChatAttachmentControls
                compact
                disabled={loading}
                showToast={showToast}
                onUploadFiles={materials.addFiles}
                onPickFolderFiles={materials.addFolderFiles}
                onImportFolderPath={materials.addFolderPath}
                onImportFolderZip={materials.addFiles}
              />
            )}
          />
        </aside>
      </div>
    </div>
  )
}
