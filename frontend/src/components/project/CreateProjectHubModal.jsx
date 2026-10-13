import React, { useEffect, useMemo, useState } from 'react'
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

export default function CreateProjectHubModal({ open, templates, onClose, showToast }) {
  const navigate = useNavigate()
  const [selectedId, setSelectedId] = useState(null)
  const [workspaceDir, setWorkspaceDir] = useState('')
  const [busy, setBusy] = useState(false)

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

  const sortedTemplates = useMemo(() => {
    const recent = new Set(recentIds)
    return [...templates].sort((a, b) => {
      const ar = recent.has(a.id) ? 1 : 0
      const br = recent.has(b.id) ? 1 : 0
      return br - ar
    })
  }, [templates, recentIds])

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
        <p className="muted">选择模板后从「选择起点」开始；完成信息录入后进入创作工作台（左文档、右 Agent）。</p>
        <Step1TemplatePicker templates={sortedTemplates} selectedId={selectedId} onSelect={setSelectedId} />
        <div className="create-hub-workspace" style={{ marginTop: 12 }}>
          <div className="row-actions" style={{ alignItems: 'center', gap: 8 }}>
            <button type="button" className="secondary" onClick={pickWorkspaceDir} disabled={busy}>
              选择工程目录（推荐）
            </button>
            <span className="muted tiny">产出默认写入「过程资料 / 产出」子文件夹</span>
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
