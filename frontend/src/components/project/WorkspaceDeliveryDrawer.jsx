import React, { useState } from 'react'
import { api } from '../../api/client'

export default function WorkspaceDeliveryDrawer({
  open,
  onClose,
  projectId,
  project,
  quals,
  onProjectUpdate,
  showToast,
}) {
  const [tab, setTab] = useState('quals')
  const [selectedQuals, setSelectedQuals] = useState(project?.inserted_quals || [])
  const [checklist, setChecklist] = useState(project?.checklist_result || null)
  const [busy, setBusy] = useState(false)

  if (!open) return null

  const toggleQual = (id) => {
    setSelectedQuals((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const saveQuals = async () => {
    setBusy(true)
    try {
      const p = await api.saveProgress(projectId, {
        current_step: 4,
        inserted_quals: selectedQuals,
        advance: false,
      })
      onProjectUpdate?.(p)
      showToast?.('资质已保存')
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  const runValidate = async () => {
    setBusy(true)
    try {
      const res = await api.validate(projectId)
      setChecklist(res)
      const p = await api.getProject(projectId)
      onProjectUpdate?.(p)
      showToast?.('校验完成')
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  const exportDoc = async () => {
    setBusy(true)
    try {
      const blob = await api.exportDoc(projectId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${project?.title || '标书'}.docx`
      a.click()
      URL.revokeObjectURL(url)
      showToast?.('导出成功')
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="workspace-delivery-drawer">
      <div className="workspace-delivery-head">
        <strong>交付</strong>
        <button type="button" className="ghost" onClick={onClose}>关闭</button>
      </div>
      <div className="filter-tabs">
        <button type="button" className={tab === 'quals' ? 'active filter-tab' : 'filter-tab'} onClick={() => setTab('quals')}>资质</button>
        <button type="button" className={tab === 'validate' ? 'active filter-tab' : 'filter-tab'} onClick={() => setTab('validate')}>校验</button>
        <button type="button" className={tab === 'export' ? 'active filter-tab' : 'filter-tab'} onClick={() => setTab('export')}>导出</button>
      </div>
      <div className="workspace-delivery-body">
        {tab === 'quals' ? (
          <>
            <div className="qual-pick-list">
              {(quals || []).map((q) => (
                <label key={q.id} className="check-row">
                  <input type="checkbox" checked={selectedQuals.includes(q.id)} onChange={() => toggleQual(q.id)} />
                  {q.category} / {q.name}
                </label>
              ))}
            </div>
            <button type="button" onClick={saveQuals} disabled={busy}>保存资质</button>
          </>
        ) : null}
        {tab === 'validate' ? (
          <>
            <button type="button" onClick={runValidate} disabled={busy}>运行条目校验</button>
            {checklist ? (
              <pre className="checklist-preview">{JSON.stringify(checklist, null, 2)}</pre>
            ) : null}
          </>
        ) : null}
        {tab === 'export' ? (
          <button type="button" onClick={exportDoc} disabled={busy}>导出 Word</button>
        ) : null}
      </div>
    </div>
  )
}
