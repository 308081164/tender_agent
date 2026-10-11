import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Step1TemplatePicker from '../Step1TemplatePicker'
import { api } from '../../api/client'

const RECENT_KEY = 'tender_recent_templates'

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
  const [busy, setBusy] = useState(false)

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
    if (!open) setSelectedId(null)
  }, [open])

  if (!open) return null

  const start = async () => {
    if (!selectedId || busy) return
    setBusy(true)
    try {
      const p = await api.createProject({ title: '新建标书', template_id: selectedId })
      await api.confirmStep1(p.id, { template_id: selectedId, title: p.title })
      markRecent(selectedId)
      await api.ensureProjectSession(p.id)
      onClose()
      navigate(`/projects/${p.id}/workspace`)
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
        <p className="muted">选择模板后进入创作工作台（左预览、右 Agent）。</p>
        <Step1TemplatePicker templates={sortedTemplates} selectedId={selectedId} onSelect={setSelectedId} />
        <div className="row-actions" style={{ marginTop: 16 }}>
          <button type="button" className="ghost" onClick={onClose} disabled={busy}>取消</button>
          <button type="button" onClick={start} disabled={busy || !selectedId}>
            {busy ? '创建中…' : '进入创作工作台'}
          </button>
        </div>
      </div>
    </div>
  )
}
