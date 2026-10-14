import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import BackChevron from '../components/chat/BackChevron'
import ChatTranscript from '../components/chat/ChatTranscript'
import ProjectContextBar from '../components/project/ProjectContextBar'
import FieldChecklistPanel from '../components/project/FieldChecklistPanel'
import ProjectDocumentPane from '../components/project/ProjectDocumentPane'
import WorkspaceDeliveryDrawer from '../components/project/WorkspaceDeliveryDrawer'
import ChatComposer from '../components/chat/ChatComposer'
import ChatAttachmentControls from '../components/chat/ChatAttachmentControls'
import ComposerContextBar from '../components/chat/ComposerContextBar'
import { useProjectContext } from '../hooks/useProjectContext'
import { usePendingMaterials } from '../components/chat/usePendingMaterials'
import { chipPayload } from '../components/chat/chatTranscriptModel'
import { appendStreamToken, buildAnchorPayload, keepStreamedReply } from '../components/chat/agentChatRuntime'
import { useChatMentions } from '../hooks/useChatMentions'
import WorkspaceReviewPanel from '../components/project/WorkspaceReviewPanel'

export default function ProjectWorkspacePage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const projectId = Number(id)
  const { showToast, quals } = useApp()
  const { context, refresh: refreshContext } = useProjectContext(projectId)
  const [project, setProject] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [workspace, setWorkspace] = useState({})
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [webSearch, setWebSearch] = useState(false)
  const [loading, setLoading] = useState(false)
  const [replyStreaming, setReplyStreaming] = useState(false)
  const [actingCardId, setActingCardId] = useState(null)
  const [checklistOpen, setChecklistOpen] = useState(true)
  const [deliveryOpen, setDeliveryOpen] = useState(false)
  const [previewToken, setPreviewToken] = useState(Date.now())
  const [features, setFeatures] = useState({ onlyoffice: { enabled: false, required: false }, suggested_prompts: [] })
  const [guidedIntake, setGuidedIntake] = useState(true)
  const [referenceText, setReferenceText] = useState('')
  const [reviewHighlights, setReviewHighlights] = useState([])
  const [lastImageAttachmentKey, setLastImageAttachmentKey] = useState(null)
  const [referenceOpen, setReferenceOpen] = useState(false)
  const messagesRef = useRef(null)
  const materials = usePendingMaterials()
  const ensureRef = useRef(null)
  const ensureForMentions = useCallback(() => ensureRef.current?.(), [])
  const mentions = useChatMentions(sessionId, ensureForMentions)
  const ensureSession = async () => {
    if (sessionId) return sessionId
    const opened = await api.openProjectWorkspace(projectId, true)
    setSessionId(opened.session.id)
    setWorkspace(opened.session.workspace || {})
    return opened.session.id
  }
  ensureRef.current = ensureSession
  const [anchor, setAnchor] = useState(null)
  const [memos, setMemos] = useState([])

  const boundProjectTitle =
    project?.fields?.project_name || project?.title || (projectId ? `项目 #${projectId}` : '')

  useEffect(() => {
    const hl = workspace?.review_highlight_texts
    if (Array.isArray(hl) && hl.length) {
      setReviewHighlights(hl)
    }
  }, [workspace?.review_highlight_texts])

  useEffect(() => {
    ;(async () => {
      try {
        const [p, feat] = await Promise.all([
          api.getProject(projectId),
          api.getChatFeatures(),
        ])
        setProject(p)
        setFeatures(feat)
        const opened = await api.openProjectWorkspace(projectId, true)
        setSessionId(opened.session.id)
        setWorkspace(opened.session.workspace || {})
        const full = await api.getChatSession(opened.session.id)
        let msgs = full.messages || []
        if (opened.assistant_message) {
          const hasOpening = msgs.some((m) => m.metadata?.kind === 'workspace_opening')
          if (!hasOpening) msgs = [...msgs, opened.assistant_message]
        }
        setMessages(msgs)
        const memoRes = await api.listProjectMemos(projectId).catch(() => ({ memos: [] }))
        setMemos(memoRes.memos || [])
      } catch (e) {
        showToast(e.message)
      }
    })()
  }, [projectId, showToast])

  useEffect(() => {
    if (!project) return
    if ((project.current_step || 1) < 3) {
      navigate(`/projects/${projectId}/step/${Math.max(project.current_step || 1, 1)}`, { replace: true })
    }
  }, [project, projectId, navigate])

  useEffect(() => {
    const el = messagesRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const bumpPreview = () => setPreviewToken(Date.now())

  const workspaceDir = (project?.workspace_dir || workspace?.workspace_dir || '').trim()

  const onWorkspaceDirChange = async (dir) => {
    try {
      if (dir) {
        await api.patchProjectWorkspaceDir(projectId, dir)
        setProject((p) => (p ? { ...p, workspace_dir: dir } : p))
      }
      if (sessionId) {
        const updated = await api.patchChatSessionWorkspace(sessionId, { workspace_dir: dir || '' })
        setWorkspace(updated.workspace || {})
      }
    } catch (e) {
      showToast(e.message)
    }
  }

  const uploadProjectFiles = async (files) => {
    let imageKey = lastImageAttachmentKey
    for (const file of files) {
      const res = await api.uploadProjectAttachment(projectId, file)
      if (/\.(png|jpe?g|gif|webp)$/i.test(file.name) && res.attachment?.object_key) {
        imageKey = res.attachment.object_key
      }
      if (res.suggested_field_patch?.length) {
        const safe = res.suggested_field_patch.filter((x) => x.auto_apply)
        if (safe.length) {
          await api.applyAttachmentPatch(projectId, res.attachment.id, safe.map((x) => x.key))
        }
      }
    }
    if (imageKey) setLastImageAttachmentKey(imageKey)
    return imageKey
  }

  const send = async (text, { withMaterials = false } = {}) => {
    if (loading || !sessionId) return
    const staged = withMaterials ? materials.consume() : []
    const q = (text ?? input).trim()
    const sentMentions = mentions.mentions
    if (!q && !staged.length && !sentMentions.length) return
    setInput('')
    setLoading(true)
    const inlineItems = staged.filter((item) => !item.path)
    const pathFolders = staged.filter((item) => item.kind === 'folder' && item.path)
    const inlineChips = chipPayload(inlineItems)
    const optimisticId = `tmp-${Date.now()}`
    const assistantId = `tmp-bot-${Date.now()}`
    const streamReply = Boolean(q || sentMentions.length)
    if (streamReply) setReplyStreaming(true)
    const optimisticUser = {
      id: optimisticId,
      role: 'user',
      content: q,
      metadata: {
        ...(inlineChips.length ? { attachments: inlineChips } : {}),
        ...(sentMentions.length ? { mentions: sentMentions } : {}),
      },
    }
    mentions.clearMentions()
    setMessages((m) => [
      ...m,
      optimisticUser,
      ...(streamReply ? [{ id: assistantId, role: 'assistant', content: '' }] : []),
    ])
    let progressed = false
    let folderMessages = []
    try {
      const files = []
      for (const item of inlineItems) {
        if (item.files?.length) files.push(...item.files)
        else if (item.file) files.push(item.file)
      }
      let imageKey = lastImageAttachmentKey
      if (files.length) {
        imageKey = await uploadProjectFiles(files)
        progressed = true
        showToast(files.length === 1 ? `已上传：${files[0].name}` : `已上传 ${files.length} 个文件`)
        bumpPreview()
        await refreshContext()
      }
      for (const folder of pathFolders) {
        const imported = await api.importChatFolder(sessionId, folder.path, folder.label || '选择资质文件夹')
        progressed = true
        if (imported.user_message) folderMessages.push(imported.user_message)
        if (imported.assistant_message) folderMessages.push(imported.assistant_message)
      }
      let textTurn = []
      if (q || inlineChips.length || sentMentions.length) {
        const ctx = {
          project_id: projectId,
          guided_intake: guidedIntake,
          ...buildAnchorPayload(anchor),
        }
        if (webSearch) ctx.web_search = true
        if (referenceText.trim()) ctx.reference_snippets = [referenceText.trim()]
        if (imageKey) ctx.attachment_object_key = imageKey
        if (inlineChips.length) ctx.attachments = inlineChips
        if (sentMentions.length) ctx.mentions = sentMentions
        const res = await api.sendChatMessageStream(sessionId, q, ctx, (tok, event) => {
          setMessages((m) => m.map((x) => (
            x.id === assistantId ? appendStreamToken(x, tok, event) : x
          )))
        })
        if (res.user_message) textTurn.push(res.user_message)
        if (res.assistant_message) textTurn.push(res.assistant_message)
        if (res.session) setWorkspace(res.session.workspace || {})
        if (res.metadata?.project_context || res.metadata?.intent === 'project_memo') {
          await refreshContext()
          const memoRes = await api.listProjectMemos(projectId).catch(() => ({ memos: [] }))
          setMemos(memoRes.memos || [])
        }
        if (res.metadata?.highlight_texts) setReviewHighlights(res.metadata.highlight_texts)
        if (res.metadata?.export_result || res.metadata?.export_flow === 'done') {
          const p = await api.getProject(projectId)
          setProject(p)
        }
        bumpPreview()
      }
      setMessages((m) => [
        ...m.filter((x) => x.id !== optimisticId && x.id !== assistantId),
        ...folderMessages,
        ...textTurn,
      ])
    } catch (e) {
      setMessages((m) => {
        const partial = m.find((x) => x.id === assistantId)
        const kept = keepStreamedReply(partial?.content, e.message)
        return [
          ...m.filter((x) => x.id !== optimisticId && x.id !== assistantId),
          ...folderMessages,
          optimisticUser,
          {
            id: assistantId,
            role: 'assistant',
            content: kept,
            metadata: { ...(partial?.metadata || {}), stream_error: e.message },
          },
        ]
      })
      if (!progressed) materials.restore(staged)
      showToast(e.message)
    } finally {
      setReplyStreaming(false)
      setLoading(false)
    }
  }

  const handleCardAction = async (message, card, action, payload) => {
    if (actingCardId || loading || !sessionId) return
    setActingCardId(card.id)
    try {
      const res = await api.sendChatAction(sessionId, {
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
      if (res.session) setWorkspace(res.session.workspace || {})
      await refreshContext()
      bumpPreview()
      const p = await api.getProject(projectId)
      setProject(p)
    } catch (e) {
      showToast(e.message)
    } finally {
      setActingCardId(null)
    }
  }

  const confirmSensitive = async (keys) => {
    try {
      await api.confirmSensitiveFields(projectId, keys)
      await refreshContext()
      showToast('已确认敏感字段')
    } catch (e) {
      showToast(e.message)
    }
  }

  const workspacePrompts = [
    '请帮我导出标书',
    '审查一下文档有没有矛盾',
    '按左侧选中内容改写',
  ]

  return (
    <div className="chat-workspace-page project-workspace-page">
      <header className="chat-workspace-topbar">
        <Link to={`/projects/${projectId}/step/2`} className="chat-back-btn">
          <BackChevron /><span>向导</span>
        </Link>
        <strong>{project?.title || '创作工作台'}</strong>
        <div className="chat-workspace-top-actions">
          <button type="button" className="ghost" onClick={() => setDeliveryOpen(true)}>交付与资质</button>
          <Link to="/" className="ghost">工作台</Link>
        </div>
      </header>

      <ProjectContextBar
        context={context}
        checklistOpen={checklistOpen}
        onToggleChecklist={() => setChecklistOpen((v) => !v)}
      />

      <div className="chat-workspace-split">
        <section className="chat-workspace-doc">
          {checklistOpen ? (
            <FieldChecklistPanel context={context} onConfirmSensitive={confirmSensitive} />
          ) : null}
          <ProjectDocumentPane
            projectId={projectId}
            sessionId={sessionId}
            workspace={workspace}
            context={context}
            onlyOfficeEnabled={!!(features.onlyoffice?.enabled || features.onlyoffice?.required)}
            refreshToken={previewToken}
            highlightTexts={reviewHighlights}
            showToast={showToast}
            onPreviewError={(msg) => showToast(msg || '预览失败')}
            onFieldsSaved={refreshContext}
            onAgentFollowup={(msg) => setMessages((m) => [...m, msg])}
            onAnchor={setAnchor}
          />
          <WorkspaceReviewPanel
            projectId={projectId}
            onReviewComplete={() => bumpPreview()}
            onHighlightTexts={setReviewHighlights}
            showToast={showToast}
            onFixed={(result) => {
              setReviewHighlights(result.highlight_texts || [])
              setMessages((m) => [...m, {
                role: 'assistant',
                content: result.answer || '已复审这一条。',
                metadata: { tool_trace: [{ tool: 'fix_review_issue', ok: !!result.ok }], highlight_texts: result.highlight_texts || [] },
              }])
              bumpPreview()
            }}
          />
        </section>

        <aside className="chat-workspace-panel">
          <div className="chat-panel-head">
            <h3>项目 Agent</h3>
            <p className="muted">语义理解 → 调用系统能力 → 结合项目上下文精准回复</p>
            <label className="check-row tiny">
              <input type="checkbox" checked={guidedIntake} onChange={(e) => setGuidedIntake(e.target.checked)} />
              引导补全
            </label>
            {memos.length ? (
              <ul className="project-memo-list">
                {memos.map((memo) => (
                  <li key={memo.id}>
                    <span>{memo.text}</span>
                    <button
                      type="button"
                      className="ghost tiny"
                      onClick={async () => {
                        try {
                          const res = await api.deleteProjectMemo(projectId, memo.id)
                          setMemos(res.memos || [])
                        } catch (err) {
                          showToast(err.message)
                        }
                      }}
                    >
                      删除
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
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
                    可修改字段、附上材料后再发送。资料会显示为芯片，对话中说「请帮我导出标书」完成审查与导出。
                  </p>
                  <div className="chat-prompt-chips">
                    {workspacePrompts.map((p) => (
                      <button key={p} type="button" className="chip" onClick={() => send(p)}>{p}</button>
                    ))}
                  </div>
                </div>
              )}
            />
          </div>
          <ChatComposer
            compact
            value={input}
            onChange={setInput}
            onSend={() => send(undefined, { withMaterials: true })}
            loading={loading}
            attachments={materials.items}
            onRemoveAttachment={materials.remove}
            mentions={mentions.mentions}
            onRemoveMention={mentions.removeMention}
            mentionItems={mentions.mentionItems}
            onMentionQuery={mentions.onMentionQuery}
            onPickMention={mentions.pickMention}
            placeholder={webSearch ? '联网检索公开资料，回复会附来源链接…' : '修改字段、提问、导出标书…'}
            webSearch={webSearch}
            onToggleWebSearch={setWebSearch}
            contextBar={(
              <ComposerContextBar
                workspaceDir={workspaceDir}
                onWorkspaceDirChange={onWorkspaceDirChange}
                disabled={loading}
                showProjectPicker={false}
                boundProjectTitle={boundProjectTitle}
              />
            )}
            innerPrefix={referenceOpen || referenceText.trim() ? (
              <div className="composer-reference-inline">
                <label>
                  <span>参照段落（发送时带入改写/创作）</span>
                  <button
                    type="button"
                    className="ghost tiny"
                    onClick={() => { setReferenceOpen(false); setReferenceText('') }}
                  >
                    清除
                  </button>
                </label>
                <textarea
                  rows={2}
                  value={referenceText}
                  onChange={(e) => setReferenceText(e.target.value)}
                  placeholder="可选：粘贴参照段落…"
                  disabled={loading}
                />
              </div>
            ) : null}
            left={(
              <>
                <button
                  type="button"
                  className={`ghost tiny${referenceOpen ? ' active' : ''}`}
                  disabled={loading}
                  title="参照段落"
                  onClick={() => setReferenceOpen((v) => !v)}
                >
                  参照
                </button>
                <label className="ghost tiny tender-upload">
                  招标文件
                  <input
                    type="file"
                    accept=".pdf,.doc,.docx,application/pdf"
                    hidden
                    disabled={loading}
                    onChange={async (e) => {
                      const file = e.target.files?.[0]
                      e.target.value = ''
                      if (!file) return
                      try {
                        await api.uploadTenderFile(projectId, file)
                        await refreshContext()
                        showToast('已解析招标文件')
                      } catch (err) {
                        showToast(err.message)
                      }
                    }}
                  />
                </label>
                <ChatAttachmentControls
                  compact
                  disabled={loading}
                  showToast={showToast}
                  onUploadFiles={materials.addFiles}
                  onPickFolderFiles={materials.addFolderFiles}
                  onImportFolderPath={materials.addFolderPath}
                  onImportFolderZip={materials.addFiles}
                />
              </>
            )}
          />
        </aside>
      </div>

      <WorkspaceDeliveryDrawer
        open={deliveryOpen}
        onClose={() => setDeliveryOpen(false)}
        projectId={projectId}
        project={project}
        quals={quals}
        onProjectUpdate={setProject}
        showToast={showToast}
      />
    </div>
  )
}
