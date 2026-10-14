import React, { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import BackChevron from '../components/chat/BackChevron'
import ChatMessageBubble from '../components/chat/ChatMessageBubble'
import ProjectContextBar from '../components/project/ProjectContextBar'
import FieldChecklistPanel from '../components/project/FieldChecklistPanel'
import ProjectDocumentPane from '../components/project/ProjectDocumentPane'
import WorkspaceDeliveryDrawer from '../components/project/WorkspaceDeliveryDrawer'
import ChatComposer from '../components/chat/ChatComposer'
import ChatAttachmentControls from '../components/chat/ChatAttachmentControls'
import ComposerContextBar from '../components/chat/ComposerContextBar'
import { useProjectContext } from '../hooks/useProjectContext'

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

  const send = async (text) => {
    const q = (text ?? input).trim()
    if (!q || loading || !sessionId) return
    setInput('')
    setLoading(true)
    const optimisticId = `tmp-${Date.now()}`
    const assistantId = `tmp-bot-${Date.now()}`
    setMessages((m) => [
      ...m,
      { id: optimisticId, role: 'user', content: q },
      { id: assistantId, role: 'assistant', content: '' },
    ])
    try {
      const ctx = { project_id: projectId, guided_intake: guidedIntake }
      if (webSearch) ctx.web_search = true
      if (referenceText.trim()) ctx.reference_snippets = [referenceText.trim()]
      if (lastImageAttachmentKey) ctx.attachment_object_key = lastImageAttachmentKey
      const res = await api.sendChatMessageStream(sessionId, q, ctx, (tok) => {
        setMessages((m) => m.map((x) => (
          x.id === assistantId ? { ...x, content: (x.content || '') + tok } : x
        )))
      })
      setMessages((m) => [
        ...m.filter((x) => x.id !== optimisticId && x.id !== assistantId),
        res.user_message,
        res.assistant_message,
      ])
      if (res.session) setWorkspace(res.session.workspace || {})
      if (res.metadata?.project_context) await refreshContext()
      if (res.metadata?.export_result || res.metadata?.export_flow === 'done') {
        const p = await api.getProject(projectId)
        setProject(p)
      }
      bumpPreview()
    } catch (e) {
      showToast(e.message)
    } finally {
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

  const uploadProjectFiles = async (files) => {
    const list = Array.from(files || []).filter(Boolean)
    if (!list.length || loading) return
    setLoading(true)
    try {
      for (const file of list) {
        const res = await api.uploadProjectAttachment(projectId, file)
        if (/\.(png|jpe?g|gif|webp)$/i.test(file.name) && res.attachment?.object_key) {
          setLastImageAttachmentKey(res.attachment.object_key)
        }
        if (res.suggested_field_patch?.length) {
          const safe = res.suggested_field_patch.filter((x) => x.auto_apply)
          if (safe.length) {
            await api.applyAttachmentPatch(projectId, res.attachment.id, safe.map((x) => x.key))
          }
        }
      }
      showToast(list.length === 1 ? `已上传：${list[0].name}` : `已上传 ${list.length} 个文件`)
      bumpPreview()
      await refreshContext()
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
    }
  }

  const importFolderPath = async (folderPath, folderLabel) => {
    if (!folderPath || loading || !sessionId) return
    setLoading(true)
    try {
      await api.importChatFolder(sessionId, folderPath, folderLabel)
      showToast('文件夹已导入会话，可在对话中继续处理')
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
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
          </div>
          <div className="chat-messages-area compact" ref={messagesRef}>
            {messages.length === 0 && !loading ? (
              <div className="chat-empty compact">
                <p className="muted chat-empty-hint">
                  可修改字段、上传材料解析、对话中说「请帮我导出标书」完成审查与导出。
                </p>
                <div className="chat-prompt-chips">
                  {workspacePrompts.map((p) => (
                    <button key={p} type="button" className="chip" onClick={() => send(p)}>{p}</button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, i) => (
                <ChatMessageBubble
                  key={m.id || i}
                  message={m}
                  onCardAction={handleCardAction}
                  actingCardId={actingCardId}
                />
              ))
            )}
            {loading ? <div className="chat-msg bot">思考中…</div> : null}
          </div>
          <ChatComposer
            compact
            value={input}
            onChange={setInput}
            onSend={() => send()}
            loading={loading}
            loadingHint={loading ? '思考中…' : null}
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
                <ChatAttachmentControls
                  compact
                  disabled={loading}
                  showToast={showToast}
                  onUploadFiles={uploadProjectFiles}
                  onImportFolderPath={importFolderPath}
                  onImportFolderZip={(file) => uploadProjectFiles([file])}
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
