import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import SelectableDocPreview from '../../components/admin/SelectableDocPreview'
import FormatInfoSummary from '../../components/admin/FormatInfoSummary'
import MappingResourcePicker from '../../components/admin/MappingResourcePicker'
import CreateFieldInlineModal from '../../components/admin/CreateFieldInlineModal'
import PdfPreview from '../../components/PdfPreview'

const STEPS = ['智能识别', '编辑确认', '应用生成']

const STATUS_LABELS = {
  matched: '已匹配',
  low_confidence: '低置信',
  unresolved: '待建字段',
  runtime: '临场填写',
}

function makeId() {
  return `m-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function flattenCatalog(resourceCatalog) {
  const fields = (resourceCatalog?.fields || []).map((f) => ({ ...f, bind_type: 'field' }))
  const quals = (resourceCatalog?.qualifications || []).map((q) => ({ ...q, bind_type: 'qual' }))
  const runtime = (resourceCatalog?.runtime || []).map((r) => ({ ...r, bind_type: 'runtime' }))
  return [...fields, ...quals, ...runtime]
}

function placeholderLabel(m) {
  if (m.bind_type === 'qual') return `【材料:${m.field_name || m.key}】`
  if (m.bind_type === 'runtime') return `{{${m.key || 'runtime_custom'}}}`
  return `{{${m.key}}}`
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
  const [resourceCatalog, setResourceCatalog] = useState({ fields: [], qualifications: [], runtime: [] })
  const [mappingStats, setMappingStats] = useState(null)
  const [selectedText, setSelectedText] = useState('')
  const [manualPick, setManualPick] = useState({ key: 'project_name', bind_type: 'field' })
  const [tplName, setTplName] = useState('')
  const [formatInfo, setFormatInfo] = useState(null)
  const [previewMode, setPreviewMode] = useState('mapping')
  const [pdfMeta, setPdfMeta] = useState({ pdf_available: false, pdf_engine: '' })
  const [pdfFailed, setPdfFailed] = useState(false)
  const [mappedPdfUrl, setMappedPdfUrl] = useState('')
  const [mappedPdfLoading, setMappedPdfLoading] = useState(false)
  const [createFieldFor, setCreateFieldFor] = useState(null)

  const catalogItems = useMemo(() => flattenCatalog(resourceCatalog), [resourceCatalog])

  const loadFields = useCallback(async () => {
    const fields = await api.adminFields({ page: 1, pageSize: 200 })
    setFieldDefs(fields.items || fields || [])
  }, [])

  const loadCatalog = useCallback(async () => {
    try {
      const res = await api.searchMappingResources('')
      if (res.items?.length) {
        setResourceCatalog({
          fields: res.items.filter((x) => x.bind_type === 'field'),
          qualifications: res.items.filter((x) => x.bind_type === 'qual'),
          runtime: res.items.filter((x) => x.bind_type === 'runtime'),
        })
      }
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    loadFields().catch(() => {})
    loadCatalog().catch(() => {})
    api.getTemplate(id).then((t) => setTplName(t.name || '')).catch(() => {})
    api.adminTemplatePreview(id)
      .then((pv) => {
        setFormatInfo(pv.format_info || null)
        setPdfMeta({ pdf_available: !!pv.pdf_available, pdf_engine: pv.pdf_engine || '' })
        if (!pv.pdf_available) setPreviewMode('mapping')
      })
      .catch(() => {})
  }, [id, loadFields, loadCatalog])

  const detect = async () => {
    setDetecting(true)
    try {
      const res = await api.detectTemplatePlaceholders(id)
      const items = (res.candidates || []).map((c) => ({
        ...c,
        id: makeId(),
        approved: c.match_status !== 'unresolved' || !!c.key,
        action: 'replace',
        bind_type: c.bind_type || 'field',
      }))
      setMappings(items)
      if (res.resource_catalog) setResourceCatalog(res.resource_catalog)
      setMappingStats(res.mapping_stats || null)
      const preview = await api.previewTemplateMappings(id, items)
      setParagraphs(preview.paragraphs || [])
      if (preview.format_info) setFormatInfo(preview.format_info)
      setStep(1)
      const stats = res.mapping_stats
      const hint = stats
        ? `已匹配 ${stats.matched}，低置信 ${stats.low_confidence}，待建字段 ${stats.unresolved}，临场 ${stats.runtime}`
        : `识别到 ${items.length} 个候选`
      showToast(hint)
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
      if (res.format_info) setFormatInfo(res.format_info)
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
    const key = manualPick.key
    const exists = mappings.some((m) => m.original_text === selectedText && m.key === key)
    if (exists) return showToast('该映射已存在')
    const next = [
      ...mappings,
      {
        id: makeId(),
        key,
        field_name: manualPick.field_name || key,
        original_text: selectedText,
        approved: true,
        action: 'replace',
        source: 'manual',
        confidence: 1,
        reason: '手动指定',
        bind_type: manualPick.bind_type || 'field',
        qualification_id: manualPick.qualification_id,
        match_status: manualPick.bind_type === 'runtime' ? 'runtime' : 'matched',
      },
    ]
    setMappings(next)
    setSelectedText('')
    showToast('已添加手动映射')
  }

  const handleFieldCreated = async (created, mappingId) => {
    await loadFields()
    await loadCatalog()
    if (mappingId) {
      updateMapping(mappingId, {
        key: created.key,
        field_name: created.name,
        bind_type: 'field',
        match_status: 'matched',
        needs_field_creation: false,
        suggested_field: undefined,
      })
    }
    showToast(`已创建字段「${created.name}」并绑定`)
  }

  const apply = async () => {
    const approved = mappings.filter((m) => m.approved && m.action !== 'keep')
    if (!approved.length) return showToast('请至少保留一项替换映射')
    const unresolved = approved.filter((m) => m.match_status === 'unresolved' && m.needs_field_creation)
    if (unresolved.length) {
      return showToast(`仍有 ${unresolved.length} 项待建字段，请先创建或重新映射`)
    }
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

  const approvedMappings = useMemo(
    () => mappings.filter((m) => m.approved && m.action !== 'keep'),
    [mappings],
  )

  useEffect(() => {
    if (previewMode !== 'pdf' || !approvedMappings.length) {
      if (mappedPdfUrl) URL.revokeObjectURL(mappedPdfUrl)
      setMappedPdfUrl('')
      return undefined
    }
    let cancelled = false
    setMappedPdfLoading(true)
    api.previewTemplateMappingsPdf(id, approvedMappings)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        if (mappedPdfUrl) URL.revokeObjectURL(mappedPdfUrl)
        setMappedPdfUrl(url)
      })
      .catch((e) => {
        if (!cancelled) showToast(e.message || '占位符 PDF 生成失败')
      })
      .finally(() => {
        if (!cancelled) setMappedPdfLoading(false)
      })
    return () => { cancelled = true }
  }, [previewMode, id, approvedMappings, showToast])

  const pdfSrc = previewMode === 'pdf' && !pdfFailed
    ? (mappedPdfUrl || (approvedMappings.length === 0 && pdfMeta.pdf_available
      ? api.adminTemplatePreviewPdfUrl(id)
      : null))
    : null

  return (
    <>
      <AdminDetailHeader
        title={`模板工程化：${tplName || id}`}
        backTo={`/admin/templates/${id}`}
        onSave={step === 2 ? apply : null}
        saving={applying}
        extra={<span className="muted">Aspose 引擎 · LLM 辅助识别与映射决策</span>}
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
          <h3>模板工程化工作台</h3>
          <p className="muted">
            系统将结合「字段定义」「企业档案」「资质库」「FAQ」等资源，由 AI 决策每处原文应映射的字段或材料；
            无法匹配时将标记为待建字段或临场填写。确认后写入占位符并保存为可复用模板。
          </p>
          <FormatInfoSummary formatInfo={formatInfo} />
          <button type="button" onClick={detect} disabled={detecting}>
            {detecting ? '识别与映射决策中…' : '开始智能识别'}
          </button>
        </div>
      ) : null}

      {step >= 1 ? (
        <div className="engineer-workbench">
          <div className="engineer-doc-pane card-block">
            <div className="placeholder-preview-legend">
              <h3 style={{ margin: 0 }}>文档预览</h3>
              <div className="admin-preview-tabs engineer-preview-tabs">
                <button
                  type="button"
                  className={`filter-tab ${previewMode === 'mapping' ? 'active' : ''}`}
                  onClick={() => setPreviewMode('mapping')}
                >
                  映射预览
                </button>
                <button
                  type="button"
                  className={`filter-tab ${previewMode === 'pdf' ? 'active' : ''}`}
                  disabled={pdfFailed || (!approvedMappings.length && !pdfMeta.pdf_available)}
                  onClick={() => setPreviewMode('pdf')}
                >
                  占位符 PDF 预览
                </button>
                {previewMode === 'mapping' ? (
                  <div className="legend-items">
                    <span><mark className="placeholder-token">{'{{key}}'}</mark> 将替换</span>
                    <span><mark className="detected-token">原文</mark> 待处理</span>
                  </div>
                ) : (
                  <span className="muted admin-preview-hint">
                    {pdfMeta.pdf_engine === 'aspose' ? 'Aspose 引擎' : pdfMeta.pdf_engine === 'libreoffice' ? 'LibreOffice' : ''}
                  </span>
                )}
              </div>
            </div>
            {previewMode === 'pdf' && mappedPdfLoading ? (
              <div className="admin-loading">正在生成占位符 PDF 预览…</div>
            ) : previewMode === 'pdf' && pdfSrc ? (
              <PdfPreview
                src={pdfSrc}
                title={tplName || '模板预览'}
                onLoadError={() => {
                  setPdfFailed(true)
                  setPreviewMode('mapping')
                  showToast('PDF 预览不可用，已切换映射预览')
                }}
              />
            ) : (
              <SelectableDocPreview
                paragraphs={paragraphs}
                mappings={mappings}
                selectedText={selectedText}
                onSelectText={setSelectedText}
              />
            )}
          </div>

          <aside className="engineer-side-pane card-block">
            <FormatInfoSummary formatInfo={formatInfo} compact />
            <h3>映射编辑 ({mappings.length})</h3>
            {mappingStats ? (
              <div className="mapping-stats-bar">
                <span className="stat matched">已匹配 {mappingStats.matched}</span>
                <span className="stat low">低置信 {mappingStats.low_confidence}</span>
                <span className="stat unresolved">待建 {mappingStats.unresolved}</span>
                <span className="stat runtime">临场 {mappingStats.runtime}</span>
              </div>
            ) : null}

            {selectedText ? (
              <div className="manual-map-box">
                <div className="muted">选中文本设为占位符：</div>
                <div className="manual-selected">{selectedText}</div>
                <MappingResourcePicker
                  value={manualPick.key}
                  bindType={manualPick.bind_type}
                  qualificationId={manualPick.qualification_id}
                  catalogItems={catalogItems}
                  onChange={(pick) => setManualPick(pick)}
                />
                <button type="button" onClick={addManualMapping}>添加映射</button>
              </div>
            ) : (
              <p className="muted">在左侧拖选文本，可手动指定字段或材料</p>
            )}

            <div className="mapping-edit-list">
              {mappings.map((m) => (
                <div
                  key={m.id}
                  className={`mapping-edit-item status-${m.match_status || 'matched'} ${m.action === 'keep' ? 'reverted' : ''}`}
                >
                  <label className="row mapping-edit-head">
                    <input
                      type="checkbox"
                      checked={!!m.approved && m.action !== 'keep'}
                      onChange={(e) => updateMapping(m.id, { approved: e.target.checked, action: e.target.checked ? 'replace' : 'keep' })}
                    />
                    <code className="placeholder-tag">{placeholderLabel(m)}</code>
                    {m.match_status ? (
                      <span className={`match-badge ${m.match_status}`}>{STATUS_LABELS[m.match_status] || m.match_status}</span>
                    ) : null}
                  </label>
                  <MappingResourcePicker
                    value={m.key}
                    bindType={m.bind_type}
                    qualificationId={m.qualification_id}
                    catalogItems={catalogItems}
                    onChange={(pick) => updateMapping(m.id, pick)}
                  />
                  <div className="mapping-original">{m.original_text}</div>
                  {m.reason ? <div className="mapping-reason muted">{m.reason}</div> : null}
                  {m.match_status === 'unresolved' && m.needs_field_creation ? (
                    <button
                      type="button"
                      className="tiny create-field-btn"
                      onClick={() => setCreateFieldFor({ mappingId: m.id, suggested: m.suggested_field })}
                    >
                      现场创建字段
                    </button>
                  ) : null}
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

      <CreateFieldInlineModal
        open={!!createFieldFor}
        suggested={createFieldFor?.suggested}
        onClose={() => setCreateFieldFor(null)}
        onCreated={(created) => handleFieldCreated(created, createFieldFor?.mappingId)}
      />
    </>
  )
}
