import React, { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import BackChevron from '../components/chat/BackChevron'
import ChatMessageBubble from '../components/chat/ChatMessageBubble'
import ProjectContextBar from '../components/project/ProjectContextBar'
import FieldChecklistPanel from '../components/project/FieldChecklistPanel'
import ProjectDocumentPane from '../components/project/ProjectDocumentPane'
import WorkspaceDeliveryDrawer from '../components/project/WorkspaceDeliveryDrawer'
import { useProjectContext } from '../hooks/useProjectContext'

export default function ProjectWorkspacePage() {
  const { id } = useParams()
  const projectId = Number(id)
  const { showToast, quals } = useApp()
  const { context, refresh: refreshContext } = useProjectContext(projectId)
  const [project, setProject] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [workspace, setWorkspace] = useState({})
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [actingCardId, setActingCardId] = useState(null)
  const [checklistOpen, setChecklistOpen] = useState(true)
  const [deliveryOpen, setDeliveryOpen] = useState(false)
  const [previewToken, setPreviewToken] = useState(Date.now())
  const [features, setFeatures] = useState({ onlyoffice: { enabled: false } })
  const [guidedIntake, setGuidedIntake] = useState(true)
  const [referenceText, setReferenceText] = useState('')
  const fileRef = useRef(null)
  const messagesRef = useRef(null)

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
    const el = messagesRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const bumpPreview = () => setPreviewToken(Date.now())

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
      if (referenceText.trim()) ctx.reference_snippets = [referenceText.trim()]
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

  const uploadAttachment = async (file) => {
    if (!file || loading) return
    setLoading(true)
    try {
      const res = await api.uploadProjectAttachment(projectId, file)
      showToast(`已上传：${file.name}`)
      if (res.suggested_field_patch?.length) {
        const safe = res.suggested_field_patch.filter((x) => x.auto_apply)
        if (safe.length) {
          await api.applyAttachmentPatch(projectId, res.attachment.id, safe.map((x) => x.key))
          bumpPreview()
          await refreshContext()
        }
      }
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="chat-workspace-page project-workspace-page">
      <header className="chat-workspace-topbar">
        <Link to={`/projects/${projectId}/step/2`} className="chat-back-btn">
          <BackChevron /><span>向导</span>
        </Link>
        <strong>{project?.title || '创作工作台'}</strong>
        <div className="chat-workspace-top-actions">
          <button type="button" className="ghost" onClick={() => setDeliveryOpen(true)}>交付</button>
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
            onlyOfficeEnabled={!!features.onlyoffice?.enabled}
            refreshToken={previewToken}
            showToast={showToast}
            onPreviewError={(msg) => showToast(msg || '预览失败')}
            onFieldsSaved={refreshContext}
            onAgentFollowup={(msg) => setMessages((m) => [...m, msg])}
          />
        </section>

        <aside className="chat-workspace-panel">
          <div className="chat-panel-head">
            <h3>项目 Agent</h3>
            <label className="check-row tiny">
              <input type="checkbox" checked={guidedIntake} onChange={(e) => setGuidedIntake(e.target.checked)} />
              引导补全
            </label>
          </div>
          <div className="chat-messages-area compact" ref={messagesRef}>
            {messages.map((m, i) => (
              <ChatMessageBubble
                key={m.id || i}
                message={m}
                onCardAction={handleCardAction}
                actingCardId={actingCardId}
              />
            ))}
            {loading ? <div className="chat-msg bot">思考中…</div> : null}
          </div>
          <div className="reference-snippet-box">
            <textarea
              rows={2}
              value={referenceText}
              onChange={(e) => setReferenceText(e.target.value)}
              placeholder="可选：粘贴参照段落，发送时将带入改写/创作"
            />
          </div>
          <footer className="chat-composer compact">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".docx,.pdf,.txt,.png,.jpg,.jpeg"
              onChange={(e) => uploadAttachment(e.target.files?.[0])}
            />
            <button type="button" className="ghost" onClick={() => fileRef.current?.click()} disabled={loading} title="上传材料">📎</button>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
              placeholder="修改字段、提问、按参照改写…"
              disabled={loading}
            />
            <button type="button" onClick={() => send()} disabled={loading || !input.trim()}>发送</button>
          </footer>
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
