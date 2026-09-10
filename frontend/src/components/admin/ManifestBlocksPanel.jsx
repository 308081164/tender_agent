import React, { useEffect, useState } from 'react'
import { api } from '../../api/client'

export default function ManifestBlocksPanel({ templateId, showToast }) {
  const [manifest, setManifest] = useState(null)
  const [saving, setSaving] = useState(false)

  const reload = async () => {
    const res = await api.getTemplateManifest(templateId)
    setManifest(res.manifest)
  }

  useEffect(() => {
    if (!templateId) return
    reload().catch((e) => showToast?.(e.message))
  }, [templateId])

  if (!manifest) return null
  const imageBlocks = (manifest.blocks || []).filter((b) => b.type === 'image_slot')
  const suggestions = manifest.image_slot_suggestions || []

  const saveBind = async (blockId, bind) => {
    setSaving(true)
    try {
      const res = await api.updateTemplateImageBinding(templateId, blockId, bind)
      setManifest(res.manifest)
      showToast?.('图片槽绑定已保存')
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (!imageBlocks.length) {
    return (
      <div className="card-block" style={{ marginBottom: 16 }}>
        <h3>Manifest 图片槽</h3>
        <p className="muted">当前模板未检测到图片槽。可点击「重新分析 Manifest」更新。</p>
        <button type="button" className="ghost" onClick={() => api.analyzeTemplateManifest(templateId).then(reload)}>
          重新分析 Manifest
        </button>
      </div>
    )
  }

  return (
    <div className="card-block" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>图片槽绑定配置</h3>
        <button type="button" className="ghost" onClick={() => api.analyzeTemplateManifest(templateId).then(reload)}>
          重新分析
        </button>
      </div>
      {imageBlocks.map((block) => {
        const sug = suggestions.find((s) => s.block_id === block.id)
        const bind = block.bind || {}
        const suggested = sug?.suggested_bind || {}
        return (
          <div key={block.id} className="field" style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
            <div className="muted" style={{ marginBottom: 6 }}>{block.id} · {block.anchor?.location || '—'}</div>
            <div className="form-grid">
              <div className="field">
                <label>资质名称</label>
                <input id={`${block.id}-name`} defaultValue={bind.qual_name || suggested.qual_name || ''} />
              </div>
              <div className="field">
                <label>资质分类</label>
                <input id={`${block.id}-cat`} defaultValue={bind.qual_category || suggested.qual_category || ''} />
              </div>
              <div className="field">
                <label>章节提示</label>
                <input id={`${block.id}-hint`} defaultValue={bind.section_hint || suggested.section_hint || ''} />
              </div>
            </div>
            <button type="button" className="secondary" style={{ marginTop: 8 }} disabled={saving}
              onClick={() => saveBind(block.id, {
                qual_name: document.getElementById(`${block.id}-name`).value,
                qual_category: document.getElementById(`${block.id}-cat`).value,
                section_hint: document.getElementById(`${block.id}-hint`).value,
              })}>
              保存绑定
            </button>
          </div>
        )
      })}
    </div>
  )
}
