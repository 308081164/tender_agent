import React, { useCallback, useState } from 'react'
import { useApp } from '../../App'
import { api } from '../../api/client'

export default function PlaceholderDetectPanel({ templateId, onApplied, onCandidatesChange, onOpenEngineer }) {
  const { showToast } = useApp()
  const [detecting, setDetecting] = useState(false)
  const [applying, setApplying] = useState(false)
  const [candidates, setCandidates] = useState([])
  const [existing, setExisting] = useState([])
  const [selection, setSelection] = useState({})

  const detect = useCallback(async () => {
    setDetecting(true)
    try {
      const res = await api.detectTemplatePlaceholders(templateId)
      setCandidates(res.candidates || [])
      setExisting(res.existing_placeholders || [])
      const init = {}
      ;(res.candidates || []).forEach((c, i) => {
        init[i] = true
      })
      setSelection(init)
      onCandidatesChange?.(res.candidates || [])
      showToast(`识别到 ${(res.candidates || []).length} 个候选占位符`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setDetecting(false)
    }
  }, [templateId, showToast])

  const toggle = (idx) => {
    setSelection((s) => ({ ...s, [idx]: !s[idx] }))
  }

  const apply = async () => {
    const mappings = candidates
      .map((c, i) => ({ ...c, approved: !!selection[i] }))
      .filter((c) => c.approved)
    if (!mappings.length) return showToast('请至少选择一项映射')
    setApplying(true)
    try {
      const res = await api.applyTemplatePlaceholders(templateId, mappings)
      showToast(`已应用 ${res.applied_count} 处占位符替换`)
      onApplied?.(res)
    } catch (e) {
      showToast(e.message)
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="placeholder-detect-panel card-block">
      <div className="placeholder-detect-head">
        <div>
          <h3 style={{ margin: 0 }}>智能识别占位符</h3>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            基于大语言模型分析完整标书，自动识别项目名称、招标编号等可替换信息，并工程化为 <code>{'{{key}}'}</code> 占位符。
          </p>
        </div>
        <div className="placeholder-detect-actions-row">
          <button type="button" onClick={detect} disabled={detecting}>
            {detecting ? '识别中…' : '快速识别'}
          </button>
          {onOpenEngineer ? (
            <button type="button" className="primary" onClick={onOpenEngineer}>
              进入工程化工作台
            </button>
          ) : null}
        </div>
      </div>

      {existing.length > 0 ? (
        <div className="placeholder-existing">
          <span className="muted">已有占位符：</span>
          {existing.map((p) => (
            <code key={p} className="placeholder-tag">{`{{${p}}}`}</code>
          ))}
        </div>
      ) : null}

      {candidates.length > 0 ? (
        <>
          <div className="placeholder-candidate-list">
            {candidates.map((c, i) => (
              <label key={`${c.key}-${c.original_text}-${i}`} className="placeholder-candidate-item">
                <input
                  type="checkbox"
                  checked={!!selection[i]}
                  onChange={() => toggle(i)}
                />
                <div className="placeholder-candidate-body">
                  <div className="placeholder-candidate-meta">
                    <code className="placeholder-tag">{`{{${c.key}}}`}</code>
                    <span>{c.field_name || c.key}</span>
                    <span className="confidence">{Math.round((c.confidence || 0) * 100)}%</span>
                    <span className="source-badge">{c.source === 'ai' ? 'AI' : '规则'}</span>
                  </div>
                  <div className="placeholder-candidate-text">{c.original_text}</div>
                  {c.reason ? <div className="muted">{c.reason}</div> : null}
                </div>
              </label>
            ))}
          </div>
          <div className="placeholder-detect-actions">
            <button type="button" className="primary" onClick={apply} disabled={applying}>
              {applying ? '应用中…' : '应用选中项并生成模板'}
            </button>
          </div>
        </>
      ) : null}
    </div>
  )
}
