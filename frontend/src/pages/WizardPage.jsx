import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import { STEPS } from '../constants'
import { useProject } from '../hooks/useProject'
import { highlightText } from '../utils/highlight'
import { formatTime } from '../utils/format'
import SnapshotPanel from '../components/SnapshotPanel'
import PreviewModal from '../components/PreviewModal'
import Step1TemplatePicker from '../components/Step1TemplatePicker'

export default function WizardPage() {
  const { id, step: stepParam } = useParams()
  const navigate = useNavigate()
  const {
    showToast, templates, fieldDefs, quals, categories,
    refreshProjects, setWizardLayout,
  } = useApp()

  const projectState = useProject(showToast)
  const {
    project, fields, setFields, selectedTpl, setSelectedTpl,
    selectedQuals, setSelectedQuals, checklist, setChecklist,
    snapshots, lastSavedAt, loading, setLoading,
    loadProject, saveCurrentStep, doRollback, applyProject,
  } = projectState

  const [categoryFilter, setCategoryFilter] = useState('')
  const [showSnapshots, setShowSnapshots] = useState(false)
  const [exports, setExports] = useState([])
  const [previewOpen, setPreviewOpen] = useState(false)

  const viewStep = Math.min(Math.max(parseInt(stepParam, 10) || 1, 1), 6)
  const currentStep = project?.current_step || 1
  const activeStep = Math.min(viewStep, 6)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const p = await loadProject(id)
        if (cancelled) return
        const maxStep = Math.min(p.current_step || 1, 6)
        if (viewStep > maxStep) {
          navigate(`/projects/${id}/step/${maxStep}`, { replace: true })
        }
      } catch (e) {
        showToast(e.message)
        navigate('/')
      }
    })()
    return () => { cancelled = true }
  }, [id])

  const goStep = (step) => {
    if (!project) return
    if (step > (project.current_step || 1)) {
      showToast('请先完成并保存前面的步骤')
      return
    }
    navigate(`/projects/${id}/step/${step}`)
  }

  useEffect(() => {
    setWizardLayout({
      project,
      activeStep,
      onGoStep: goStep,
      snapshots,
      onRollback: handleRollback,
      loading,
    })
    return () => setWizardLayout({
      project: null, activeStep: 1, onGoStep: null,
      snapshots: [], onRollback: null, loading: false,
    })
  }, [project, activeStep, snapshots, loading])

  useEffect(() => {
    if (project?.status === 'exported' || activeStep === 6) {
      api.listExports(id).then(setExports).catch(() => setExports([]))
    }
  }, [id, project?.status, activeStep, lastSavedAt])

  const handleRollback = async (snapshotId) => {
    const p = await doRollback(snapshotId)
    if (p) {
      navigate(`/projects/${id}/step/${Math.min(p.current_step || 1, 6)}`)
      await refreshProjects()
    }
  }

  const saveStep = async (opts = {}) => {
    const p = await saveCurrentStep({
      activeStep,
      templates,
      ...opts,
    })
    if (p) {
      await refreshProjects()
      if (opts.advance) {
        navigate(`/projects/${id}/step/${Math.min(p.current_step || activeStep + 1, 6)}`)
      }
    }
    return p
  }

  const confirmStep1 = async () => {
    const p = await saveStep({ advance: true })
    if (p) {
      const next = { ...(p.fields || {}) }
      for (const f of fieldDefs) {
        if (f.default_value && !next[f.key]) next[f.key] = f.default_value
      }
      setFields(next)
    }
  }

  const confirmFields = async () => {
    const missing = fieldDefs.filter((f) => f.required && !fields[f.key])
    if (missing.length) return showToast(`请填写必填项：${missing.map((m) => m.name).join('、')}`)
    await saveStep({ advance: true })
  }

  const doGenerate = async () => {
    setLoading(true)
    try {
      await api.saveProgress(project.id, { fields, current_step: 3, create_snapshot: true })
      const p = await api.generate(project.id)
      await applyProject(p)
      showToast('AI 内容已生成并已自动保存')
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
    }
  }

  const regen = async (key) => {
    setLoading(true)
    try {
      const p = await api.regenerate(project.id, key)
      await applyProject(p)
      showToast(`已重生成并保存：${key}`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
    }
  }

  const confirmAi = async () => {
    if (!Object.keys(project.chapters || {}).length) return showToast('请先生成 AI 内容')
    await saveStep({ advance: true })
  }

  const confirmQuals = async () => {
    await saveStep({ advance: true })
  }

  const doValidate = async () => {
    setLoading(true)
    try {
      await api.saveProgress(project.id, {
        fields,
        chapters: project.chapters || {},
        inserted_quals: selectedQuals,
        current_step: 5,
        create_snapshot: true,
      })
      const result = await api.validate(project.id)
      setChecklist(result)
      const p = await api.getProject(project.id)
      await applyProject(p)
      showToast(result.can_export ? '校验通过并已保存' : '校验结果已保存，请先处理红色项')
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
    }
  }

  const enterExport = async () => {
    if (!checklist?.can_export) return showToast('校验未通过，暂不可导出')
    await saveStep({ advance: true })
  }

  const doExport = async () => {
    setLoading(true)
    try {
      await api.saveProgress(project.id, {
        fields,
        chapters: project.chapters || {},
        inserted_quals: selectedQuals,
        checklist_result: checklist || project.checklist_result || {},
        current_step: 6,
        create_snapshot: true,
      })
      const blob = await api.exportDoc(project.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${fields.project_name || project.title || '标书'}.docx`
      a.click()
      URL.revokeObjectURL(url)
      const p = await api.getProject(project.id)
      await applyProject(p)
      const list = await api.listExports(project.id)
      setExports(list)
      showToast('Word 已导出，进度已保存')
      await refreshProjects()
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
    }
  }

  const filteredQuals = useMemo(
    () => (categoryFilter ? quals.filter((q) => q.category === categoryFilter) : quals),
    [quals, categoryFilter]
  )

  const recommendedQuals = useMemo(() => {
    const type = fields.project_type || ''
    return quals.filter((q) => {
      if (type.includes('铁路') && (q.name.includes('铁路') || q.category.includes('企业资质'))) return true
      if (q.category.includes('企业资质') || q.category.includes('人员') || q.category.includes('业绩')) return true
      return false
    }).slice(0, 6)
  }, [quals, fields.project_type])

  if (!project) {
    return <div className="panel"><div className="empty">加载标书中…</div></div>
  }

  const step = activeStep

  return (
    <>
      <div className="panel">
        <div className="wizard-topbar">
          <div>
            <div className="wizard-kicker">当前步骤 {step}/6 · {STEPS.find((s) => s.step === step)?.name}</div>
            <div className="wizard-save-hint">
              {lastSavedAt ? `最近保存：${formatTime(lastSavedAt)}` : '尚未保存本步'}
            </div>
          </div>
          <div className="actions" style={{ marginTop: 0 }}>
            <button className="ghost" onClick={() => setShowSnapshots((v) => !v)}>
              {showSnapshots ? '收起快照' : '步骤快照'}
            </button>
            <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
          </div>
        </div>

        {showSnapshots && (
          <div className="wizard-snapshots">
            <SnapshotPanel snapshots={snapshots} onRollback={handleRollback} />
          </div>
        )}

        {step === 1 && (
          <>
            <h2>选择起点</h2>
            <p className="lead">优先选择「工程化模板」；历史标书将按原字段快照做智能替换。招标文件不会出现在此列表。</p>
            <Step1TemplatePicker
              templates={templates}
              selectedId={selectedTpl}
              onSelect={setSelectedTpl}
            />
            <div className="actions">
              <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
              <button onClick={confirmStep1} disabled={loading || !selectedTpl}>保存并进入信息录入</button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h2>信息录入</h2>
            <p className="lead">企业默认值已预填。标注「请核实」的字段来自脱敏数据，导出前务必改正。</p>
            <div className="form-grid">
              {fieldDefs.map((f) => (
                <div className={`field ${f.field_type === '多行文本' ? 'full' : ''}`} key={f.key}>
                  <label>
                    {f.name}{f.required ? ' *' : ''}
                    {f.desensitized ? <span className="tag-warn"> 请核实</span> : null}
                  </label>
                  {(f.field_type === '下拉选项' || f.field_type === '下拉') ? (
                    <select
                      value={fields[f.key] || ''}
                      onChange={(e) => setFields({ ...fields, [f.key]: e.target.value })}
                    >
                      <option value="">请选择</option>
                      {(f.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : f.field_type === '多行文本' ? (
                    <textarea
                      value={fields[f.key] || ''}
                      onChange={(e) => setFields({ ...fields, [f.key]: e.target.value })}
                    />
                  ) : (
                    <input
                      value={fields[f.key] || ''}
                      onChange={(e) => setFields({ ...fields, [f.key]: e.target.value })}
                      placeholder={f.default_value || ''}
                      className={f.desensitized ? 'desensitized' : undefined}
                    />
                  )}
                </div>
              ))}
            </div>
            <div className="actions">
              <button className="secondary" onClick={() => goStep(1)}>返回上一步</button>
              <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
              <button onClick={confirmFields} disabled={loading}>保存并进入 AI 生成</button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h2>AI 内容生成与审核</h2>
            <p className="lead">逐章节生成标书文本，关键信息高亮便于复核。生成后会自动保存，也可手动保存本步。</p>
            <div className="actions" style={{ marginTop: 0, marginBottom: 16 }}>
              <button onClick={doGenerate} disabled={loading}>一键生成全部章节</button>
              <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
            </div>
            {Object.keys(project.chapters || {}).length === 0 ? (
              <div className="empty">尚未生成内容，请点击上方按钮。</div>
            ) : (
              Object.entries(project.chapters).map(([key, val]) => (
                <div className="chapter" key={key}>
                  <div className="chapter-head">
                    <h4>{key}</h4>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span className="badge">{val.source === 'ai' ? 'AI' : '模板引擎'}</span>
                      <button className="ghost" onClick={() => regen(key)} disabled={loading}>重生成</button>
                    </div>
                  </div>
                  <div>{highlightText(val.content, fields)}</div>
                </div>
              ))
            )}
            <div className="actions">
              <button className="secondary" onClick={() => goStep(2)}>返回修改信息</button>
              <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
              <button onClick={confirmAi} disabled={loading || !Object.keys(project.chapters || {}).length}>
                保存并进入资质插入
              </button>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <h2>资质材料点选插入</h2>
            <p className="lead">从推荐或列表点选资质，可先保存再继续校验。</p>
            {recommendedQuals.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <strong>根据当前上下文推荐：</strong>
                <div className="qual-list" style={{ marginTop: 8, maxHeight: 'none' }}>
                  {recommendedQuals.map((q) => (
                    <label className="qual-item" key={`rec-${q.id}`}>
                      <input
                        type="checkbox"
                        checked={selectedQuals.includes(q.id)}
                        onChange={(e) => {
                          setSelectedQuals((ids) =>
                            e.target.checked ? [...ids, q.id] : ids.filter((x) => x !== q.id)
                          )
                        }}
                      />
                      <div>
                        <div>{q.name}</div>
                        <div className="meta">{q.category} · {q.issuer || '—'}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="field" style={{ marginBottom: 12, maxWidth: 280 }}>
              <label>按类别筛选</label>
              <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                <option value="">全部类别</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="qual-list">
              {filteredQuals.map((q) => (
                <label className="qual-item" key={q.id}>
                  <input
                    type="checkbox"
                    checked={selectedQuals.includes(q.id)}
                    onChange={(e) => {
                      setSelectedQuals((ids) =>
                        e.target.checked ? [...ids, q.id] : ids.filter((x) => x !== q.id)
                      )
                    }}
                  />
                  <div>
                    <div>{q.name}</div>
                    <div className="meta">
                      {q.category} · {q.section_hint ? `${q.section_hint} · ` : ''}
                      {q.is_long_term ? '长期有效' : (q.valid_to || '—')}
                      {q.expired ? ' · 已过期' : ''}
                      {q.expiring ? ' · 临期' : ''}
                    </div>
                  </div>
                </label>
              ))}
            </div>
            <div className="actions">
              <button className="secondary" onClick={() => goStep(3)}>返回上一步</button>
              <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
              <button onClick={confirmQuals} disabled={loading}>保存并进入校验</button>
            </div>
          </>
        )}

        {step === 5 && (
          <>
            <h2>条目完整性校验</h2>
            <p className="lead">红灯阻断导出，黄灯警告，绿灯通过。校验结果会自动保存。</p>
            <div className="actions" style={{ marginTop: 0, marginBottom: 16 }}>
              <button onClick={doValidate} disabled={loading}>执行校验并保存</button>
              <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
            </div>
            {!checklist ? (
              <div className="empty">尚未执行校验。</div>
            ) : (
              <>
                <p>
                  汇总：
                  <span className="level-red"> 红 {checklist.summary?.red || 0}</span>
                  <span className="level-yellow"> 黄 {checklist.summary?.yellow || 0}</span>
                  <span className="level-green"> 绿 {checklist.summary?.green || 0}</span>
                  {checklist.can_export ? ' · 可导出' : ' · 暂不可导出'}
                </p>
                <table className="check-table">
                  <thead>
                    <tr>
                      <th>级别</th>
                      <th>分区</th>
                      <th>条目</th>
                      <th>状态</th>
                      <th>备注</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(checklist.items || []).map((item) => (
                      <tr key={item.id}>
                        <td className={`level-${item.level}`}>{item.level}</td>
                        <td>{item.section}</td>
                        <td>{item.name}</td>
                        <td>{item.found ? '已覆盖' : '缺失'}</td>
                        <td>{item.remark}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="actions">
                  <button className="secondary" onClick={() => goStep(4)}>返回上一步</button>
                  <button onClick={enterExport} disabled={!checklist.can_export || loading}>
                    保存并进入导出
                  </button>
                </div>
              </>
            )}
          </>
        )}

        {step === 6 && (
          <>
            <h2>导出 Word</h2>
            <p className="lead">按模板占位符替换生成 .docx，关键字段黄底高亮，可在 Word / WPS 中打开。</p>
            <ul>
              <li>项目：{fields.project_name || project.title}</li>
              <li>模板 ID：{project.template_id}</li>
              <li>已插入资质：{(project.inserted_quals || []).length} 项</li>
              <li>校验状态：{checklist?.status || project.checklist_result?.status || '未校验'}</li>
              <li>导出记录：{exports.length} 次</li>
            </ul>
            {exports.length > 0 && (
              <div className="export-list">
                {exports.map((e) => (
                  <div className="export-row" key={e.id}>
                    <div>
                      <strong>{e.filename}</strong>
                      <div style={{ color: 'var(--muted)', fontSize: 12 }}>{formatTime(e.created_at)}</div>
                    </div>
                    <div className="actions" style={{ marginTop: 0 }}>
                      <button className="ghost" onClick={() => setPreviewOpen(true)}>预览</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="actions">
              <button className="secondary" onClick={() => goStep(5)}>返回校验</button>
              <button className="secondary" onClick={() => saveStep()} disabled={loading}>保存本步</button>
              <button className="ghost" onClick={doValidate} disabled={loading}>重新校验</button>
              {exports.length > 0 && (
                <button className="ghost" onClick={() => setPreviewOpen(true)}>预览已导出</button>
              )}
              <button onClick={doExport} disabled={loading}>下载 Word 标书</button>
            </div>
          </>
        )}
      </div>

      {previewOpen && (
        <PreviewModal
          projectId={project.id}
          exportId={exports[0]?.id}
          onClose={() => setPreviewOpen(false)}
          showToast={showToast}
        />
      )}
    </>
  )
}
