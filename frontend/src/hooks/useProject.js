import { useCallback, useState } from 'react'
import { api } from '../api/client'
import { STEPS } from '../constants'

export function useProject(showToast) {
  const [project, setProject] = useState(null)
  const [fields, setFields] = useState({})
  const [selectedTpl, setSelectedTpl] = useState(null)
  const [selectedQuals, setSelectedQuals] = useState([])
  const [checklist, setChecklist] = useState(null)
  const [snapshots, setSnapshots] = useState([])
  const [lastSavedAt, setLastSavedAt] = useState('')
  const [loading, setLoading] = useState(false)

  const applyProject = useCallback(async (p, opts = {}) => {
    setProject(p)
    setFields(p.fields || {})
    setSelectedTpl(p.template_id)
    setSelectedQuals(p.inserted_quals || [])
    setChecklist(p.checklist_result || null)
    if (opts.refreshSnapshots !== false) {
      setSnapshots(await api.snapshots(p.id))
    }
    if (p.updated_at) setLastSavedAt(p.updated_at)
    return p
  }, [])

  const loadProject = useCallback(async (id) => {
    const full = await api.getProject(id)
    await applyProject(full)
    return full
  }, [applyProject])

  const saveCurrentStep = useCallback(async ({
    activeStep,
    templates = [],
    advance = false,
    silent = false,
  } = {}) => {
    if (!project) return null
    setLoading(true)
    try {
      const step = activeStep
      const payload = {
        current_step: step,
        advance: Boolean(advance),
        create_snapshot: true,
      }
      if (step === 1) {
        if (!selectedTpl && advance) {
          showToast?.('请先选择模板或历史标书')
          return null
        }
        if (selectedTpl) {
          const tpl = templates.find((t) => t.id === selectedTpl)
          payload.template_id = selectedTpl
          payload.source_type = tpl?.is_history ? 'history' : 'template'
          payload.title = tpl?.name || project.title
        }
      }
      if (step >= 2) {
        payload.fields = fields
      }
      if (step === 3) {
        payload.chapters = project.chapters || {}
        payload.fields = fields
      }
      if (step === 4) {
        payload.inserted_quals = selectedQuals
        payload.fields = fields
        payload.chapters = project.chapters || {}
      }
      if (step === 5) {
        payload.checklist_result = checklist || project.checklist_result || {}
        payload.inserted_quals = selectedQuals
        payload.fields = fields
        payload.chapters = project.chapters || {}
      }
      if (step === 6) {
        payload.fields = fields
        payload.chapters = project.chapters || {}
        payload.inserted_quals = selectedQuals
        payload.checklist_result = checklist || project.checklist_result || {}
      }

      const p = await api.saveProgress(project.id, payload)
      await applyProject(p)
      if (!silent) {
        showToast?.(
          advance
            ? `已保存并进入：${STEPS.find((s) => s.step === Math.min(p.current_step, 6))?.name || '下一步'}`
            : '本步进度已保存'
        )
      }
      return p
    } catch (e) {
      showToast?.(e.message)
      return null
    } finally {
      setLoading(false)
    }
  }, [project, selectedTpl, fields, selectedQuals, checklist, applyProject, showToast])

  const doRollback = useCallback(async (snapshotId) => {
    if (!project) return
    setLoading(true)
    try {
      const p = await api.rollback(project.id, snapshotId)
      await applyProject(p)
      showToast?.('已回退到选定快照')
      return p
    } catch (e) {
      showToast?.(e.message)
      return null
    } finally {
      setLoading(false)
    }
  }, [project, applyProject, showToast])

  return {
    project,
    setProject,
    fields,
    setFields,
    selectedTpl,
    setSelectedTpl,
    selectedQuals,
    setSelectedQuals,
    checklist,
    setChecklist,
    snapshots,
    lastSavedAt,
    loading,
    setLoading,
    applyProject,
    loadProject,
    saveCurrentStep,
    doRollback,
  }
}
