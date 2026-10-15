import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Step1TemplatePicker from '../Step1TemplatePicker'
import { api } from '../../api/client'

const RECENT_KEY = 'tender_recent_templates'
const RECENT_WORKSPACE_KEY = 'tender_recent_workspace_dirs'

function markRecent(templateId) {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    const next = [templateId, ...raw.filter((id) => id !== templateId)].slice(0, 8)
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    /* ignore */
  }
}

export default function CreateProjectHubModal({ open, templates, onClose, showToast, onUploaded }) {
  const navigate = useNavigate()
  const [selectedId, setSelectedId] = useState(null)
  const [workspaceDir, setWorkspaceDir] = useState('')
  const [busy, setBusy] = useState(false)
  const [localTemplates, setLocalTemplates] = useState(templates)
  const fileRef = useRef(null)

  const recentWorkspaces = useMemo(() => {
    try {
      return JSON.parse(localStorage.getItem(RECENT_WORKSPACE_KEY) || '[]')
    } catch {
      return []
    }
  }, [open])

  const recentIds = useMemo(() => {
    try {
      return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    } catch {
      return []
    }
  }, [open])

  useEffect(() => {
    setLocalTemplates(templates)
  }, [templates])

  const sortedTemplates = useMemo(() => {
    const recent = new Set(recentIds)
    return [...localTemplates].sort((a, b) => {
      const ar = recent.has(a.id) ? 1 : 0
      const br = recent.has(b.id) ? 1 : 0
      return br - ar
    })
  }, [localTemplates, recentIds])

  const onUpload = async (file) => {
    if (!file || busy) return
    setBusy(true)
    try {
      const tpl = await api.uploadReusableTemplate(file)
      setLocalTemplates((list) => [tpl, ...list.filter((item) => item.id !== tpl.id)])
      setSelectedId(tpl.id)
      await onUploaded?.()
      showToast?.(`「${tpl.name || file.name}」已保存，这次和以后的标书都可以选用`)
    } catch (e) {
      showToast?.(e.message || '上传失败')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  useEffect(() => {
    if (!open) {
      setSelectedId(null)
      setWorkspaceDir('')
    }
  }, [open])

  const pickWorkspaceDir = async () => {
    const desktop = window.tenderAgentDesktop
    if (desktop?.pickProjectWorkspaceDir) {
      try {
        const res = await desktop.pickProjectWorkspaceDir()
        if (!res?.canceled && res.path) setWorkspaceDir(res.path)
      } catch (e) {
        showToast?.(e.message || '无法选择目录')
      }
    } else {
      showToast?.('Web 版可在创建后于项目设置中填写工程目录路径')
    }
  }

  const markRecentWorkspace = (dir) => {
    if (!dir) return
    try {
      const raw = JSON.parse(localStorage.getItem(RECENT_WORKSPACE_KEY) || '[]')
      const next = [dir, ...raw.filter((d) => d !== dir)].slice(0, 6)
      localStorage.setItem(RECENT_WORKSPACE_KEY, JSON.stringify(next))
    } catch {
      /* ignore */
    }
  }

  if (!open) return null

  const start = async () => {
    if (!selectedId || busy) return
    setBusy(true)
    try {
      const p = await api.createProject({
        title: '新建标书',
        template_id: selectedId,
        ...(workspaceDir.trim() ? { workspace_dir: workspaceDir.trim() } : {}),
      })
      if (workspaceDir.trim()) markRecentWorkspace(workspaceDir.trim())
      markRecent(selectedId)
      onClose()
      navigate(`/projects/${p.id}/step/1`)
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className="modal panel create-hub-modal" role="dialog" onClick={(e) => e.stopPropagation()}>
        <h3>新建标书</h3>
        <p className="muted">选择已有模板，或现在上传一份。上传的文件会存成可复用模板，下一份标书也能选到。完成信息录入后留在 Agent 对话里编写、审查和导出。</p>
        <input
          ref={fileRef}
          type="file"
          accept=".docx"
          className="hidden"
          onChange={(e) => onUpload(e.target.files?.[0])}
        />
        <div className="row-actions" style={{ marginBottom: 8 }}>
          <button type="button" className="secondary" onClick={() => fileRef.current?.click()} disabled={busy}>
            {busy ? '上传中…' : '上传 Word 模板'}
          </button>
        </div>
        <Step1TemplatePicker templates={sortedTemplates} selectedId={selectedId} onSelect={setSelectedId} />
        <div className="create-hub-workspace" style={{ marginTop: 12 }}>
          <div className="row-actions" style={{ alignItems: 'center', gap: 8 }}>
            <button type="button" className="secondary" onClick={pickWorkspaceDir} disabled={busy}>
              选择工作目录（推荐）
            </button>
            <span className="muted tiny">未选择时使用服务端默认目录；选定后 Agent 以该文件夹为工程根目录</span>
          </div>
          {workspaceDir ? (
            <p className="tiny muted" style={{ marginTop: 6, wordBreak: 'break-all' }}>{workspaceDir}</p>
          ) : null}
          {recentWorkspaces.length > 0 ? (
            <div className="chat-prompt-chips" style={{ marginTop: 8 }}>
              {recentWorkspaces.map((d) => (
                <button key={d} type="button" className="chip" onClick={() => setWorkspaceDir(d)}>
                  最近：{d.split(/[/\\]/).slice(-1)[0] || d}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="row-actions" style={{ marginTop: 16 }}>
          <button type="button" className="ghost" onClick={onClose} disabled={busy}>取消</button>
          <button type="button" onClick={start} disabled={busy || !selectedId}>
            {busy ? '创建中…' : '开始新建标书'}
          </button>
        </div>
      </div>
    </div>
  )
}
