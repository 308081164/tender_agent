import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import SelectableDocPreview from '../../components/admin/SelectableDocPreview'

const STEPS = ['智能识别', '编辑确认', '应用生成']

function makeId() {
  return `m-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export default function TemplateEngineerPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { showToast } = useApp()
  const [step, setStep] = useState(0)
  const [detecting, setDetecting] = useState(false)
  const [applying, setApplying] = useState(false)
  const [mappings, setMappings] = useState([])
  const [paragraphs, setParagraphs] = useState([])
  const [fieldDefs, setFieldDefs] = useState([])
  const [selectedText, setSelectedText] = useState('')
  const [manualKey, setManualKey] = useState('project_name')
  const [tplName, setTplName] = useState('')

  const loadFields = useCallback(async () => {
    const fields = await api.adminFields({ page: 1, pageSize: 200 })
    setFieldDefs(fields.items || fields || [])
  }, [])

  useEffect(() => {
    loadFields().catch(() => {})
    api.getTemplate(id).then((t) => setTplName(t.name || '')).catch(() => {})
  }, [id, loadFields])

  const detect = async () => {
    setDetecting(true)
    try {
      const res = await api.detectTemplatePlaceholders(id)
      const items = (res.candidates || []).map((c) => ({
        ...c,
        id: makeId(),
        approved: true,
        action: 'replace',
      }))
      setMappings(items)
      const preview = await api.previewTemplateMappings(id, items)
      setParagraphs(preview.paragraphs || [])
      setStep(1)
      showToast(`识别到 ${items.length} 个候选字段`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setDetecting(false)
    }
  }

  const refreshPreview = useCallback(async (nextMappings) => {
    try {
      const res = await api.previewTemplateMappings(id, nextMappings)
      setParagraphs(res.paragraphs || [])
    } catch (e) {
      showToast(e.message)
    }
  }, [id, showToast])

  useEffect(() => {
    if (step === 1 && mappings.length) {
      refreshPreview(mappings)
    }
  }, [mappings, step, refreshPreview])

  const updateMapping = (mid, patch) => {
    setMappings((list) => list.map((m) => (m.id === mid ? { ...m, ...patch } : m)))
  }

  const revertMapping = (mid) => {
    updateMapping(mid, { action: 'keep', approved: false })
  }

  const removeMapping = (mid) => {
    setMappings((list) => list.filter((m) => m.id !== mid))
  }

  const addManualMapping = () => {
    if (!selectedText.trim()) return showToast('请先在左侧选中文本')
    const exists = mappings.some((m) => m.original_text === selectedText && m.key === manualKey)
    if (exists) return showToast('该映射已存在')
    const field = fieldDefs.find((f) => f.key === manualKey)
    const next = [
      ...mappings,
      {
        id: makeId(),
        key: manualKey,
        field_name: field?.name || manualKey,
        original_text: selectedText,
        approved: true,
        action: 'replace',
        source: 'manual',
        confidence: 1,
        reason: '手动指定',
      },
    ]
    setMappings(next)
    setSelectedText('')
    showToast('已添加手动映射')
  }

  const apply = async () => {
    const approved = mappings.filter((m) => m.approved && m.action !== 'keep')
    if (!approved.length) return showToast('请至少保留一项替换映射')
    setApplying(true)
    try {
      await api.applyTemplatePlaceholders(id, approved)
      showToast(`已应用 ${approved.length} 处占位符`)
      navigate(`/admin/templates/${id}`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setApplying(false)
    }
  }

  return (
    <>
      <AdminDetailHeader
        title={`模板工程化：${tplName || id}`}
        backTo={`/admin/templates/${id}`}
        onSave={step === 2 ? apply : null}
        saving={applying}
        extra={<span className="muted">Aspose 引擎 · LLM 辅助识别</span>}
      />

      <div className="engineer-steps card-block">
        {STEPS.map((label, i) => (
          <button
            key={label}
            type="button"
            className={`engineer-step ${step === i ? 'active' : ''} ${step > i ? 'done' : ''}`}
            onClick={() => { if (i <= step) setStep(i) }}
          >
            <span className="step-no">{i + 1}</span>
            {label}
          </button>
        ))}
      </div>

      {step === 0 ? (
        <div className="card-block engineer-intro">
          <h3>从完整标书创建可复用模板</h3>
          <p className="muted">
            第一步将使用 AI + 规则识别项目名称、招标编号等可变信息。
            第二步可在可编辑页面手动恢复原文、或选中文本指定为占位符。
            第三步确认后由 Aspose 引擎写入 <code>{'{{key}}'}</code> 并保存。
          </p>
          <button type="button" onClick={detect} disabled={detecting}>
            {detecting ? '识别中…' : '开始智能识别'}
          </button>
        </div>
      ) : null}

      {step >= 1 ? (
        <div className="engineer-workbench">
          <div className="engineer-doc-pane card-block">
            <div className="placeholder-preview-legend">
              <h3 style={{ margin: 0 }}>文档预览（可选中设占位符）</h3>
              <div className="legend-items">
                <span><mark className="placeholder-token">{'{{key}}'}</mark> 将替换</span>
                <span><mark className="detected-token">原文</mark> 待处理</span>
              </div>
            </div>
            <SelectableDocPreview
              paragraphs={paragraphs}
              mappings={mappings}
              selectedText={selectedText}
              onSelectText={setSelectedText}
            />
          </div>

          <aside className="engineer-side-pane card-block">
            <h3>映射编辑 ({mappings.length})</h3>
            {selectedText ? (
              <div className="manual-map-box">
                <div className="muted">选中文本设为占位符：</div>
                <div className="manual-selected">{selectedText}</div>
                <select value={manualKey} onChange={(e) => setManualKey(e.target.value)}>
                  {fieldDefs.map((f) => (
                    <option key={f.key} value={f.key}>{f.name} ({f.key})</option>
                  ))}
                </select>
                <button type="button" onClick={addManualMapping}>添加映射</button>
              </div>
            ) : (
              <p className="muted">在左侧拖选文本，可手动指定字段占位符</p>
            )}

            <div className="mapping-edit-list">
              {mappings.map((m) => (
                <div key={m.id} className={`mapping-edit-item ${m.action === 'keep' ? 'reverted' : ''}`}>
                  <label className="row">
                    <input
                      type="checkbox"
                      checked={!!m.approved && m.action !== 'keep'}
                      onChange={(e) => updateMapping(m.id, { approved: e.target.checked, action: e.target.checked ? 'replace' : 'keep' })}
                    />
                    <code className="placeholder-tag">{`{{${m.key}}}`}</code>
                  </label>
                  <select
                    value={m.key}
                    onChange={(e) => {
                      const f = fieldDefs.find((x) => x.key === e.target.value)
                      updateMapping(m.id, { key: e.target.value, field_name: f?.name || e.target.value })
                    }}
                  >
                    {fieldDefs.map((f) => (
                      <option key={f.key} value={f.key}>{f.name}</option>
                    ))}
                  </select>
                  <div className="mapping-original">{m.original_text}</div>
                  <div className="mapping-edit-actions">
                    <button type="button" className="ghost tiny" onClick={() => revertMapping(m.id)}>恢复原文</button>
                    <button type="button" className="ghost tiny" onClick={() => removeMapping(m.id)}>删除</button>
                  </div>
                </div>
              ))}
            </div>

            <div className="engineer-side-actions">
              {step === 1 ? (
                <button type="button" className="primary" onClick={() => setStep(2)}>下一步：确认应用</button>
              ) : (
                <>
                  <button type="button" className="ghost" onClick={() => setStep(1)}>返回编辑</button>
                  <button type="button" className="primary" onClick={apply} disabled={applying}>
                    {applying ? '应用中…' : '应用并生成模板'}
                  </button>
                </>
              )}
            </div>
          </aside>
        </div>
      ) : null}
    </>
  )
}
