import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'

function itemLabel(item) {
  const mod = item.module ? ` · ${item.module}` : ''
  return `${item.name} (${item.key})${mod}`
}

function itemValue(item) {
  if (item.bind_type === 'qual') return `qual:${item.id}`
  if (item.bind_type === 'runtime') return `runtime:${item.key}`
  return `field:${item.key}`
}

function parseValue(val) {
  if (!val) return null
  const [type, rest] = val.split(':', 2)
  if (type === 'qual') return { bind_type: 'qual', qualification_id: Number(rest), key: `qual_${rest}` }
  if (type === 'runtime') return { bind_type: 'runtime', key: rest }
  return { bind_type: 'field', key: rest }
}

export default function MappingResourcePicker({
  value,
  bindType = 'field',
  qualificationId,
  catalogItems = [],
  onChange,
  placeholder = '搜索字段/材料…',
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [remoteItems, setRemoteItems] = useState(null)
  const [loading, setLoading] = useState(false)
  const wrapRef = useRef(null)

  const selectedVal = useMemo(() => {
    if (bindType === 'qual' && qualificationId) return `qual:${qualificationId}`
    if (bindType === 'runtime') return `runtime:${value || 'runtime_custom'}`
    return `field:${value || ''}`
  }, [bindType, qualificationId, value])

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  useEffect(() => {
    if (!open || !query.trim()) {
      setRemoteItems(null)
      return undefined
    }
    const timer = setTimeout(() => {
      setLoading(true)
      api.searchMappingResources(query.trim())
        .then((res) => setRemoteItems(res.items || []))
        .catch(() => setRemoteItems([]))
        .finally(() => setLoading(false))
    }, 220)
    return () => clearTimeout(timer)
  }, [query, open])

  const baseItems = catalogItems.length ? catalogItems : []
  const displayItems = useMemo(() => {
    const q = query.trim().toLowerCase()
    const pool = remoteItems ?? baseItems
    if (!q || remoteItems) return pool.slice(0, 50)
    return pool.filter((item) => {
      const text = `${item.name} ${item.key} ${item.module || ''} ${item.search_text || ''}`.toLowerCase()
      return text.includes(q)
    }).slice(0, 50)
  }, [baseItems, query, remoteItems])

  const selectedItem = useMemo(() => {
    const pool = [...baseItems, ...(remoteItems || [])]
    return pool.find((item) => itemValue(item) === selectedVal) || null
  }, [baseItems, remoteItems, selectedVal])

  const pick = (item) => {
    onChange?.({
      key: item.key,
      field_name: item.name,
      bind_type: item.bind_type || 'field',
      qualification_id: item.bind_type === 'qual' ? item.id : undefined,
      match_status: item.bind_type === 'runtime' ? 'runtime' : 'matched',
      needs_field_creation: false,
    })
    setOpen(false)
    setQuery('')
  }

  const handleInputChange = (e) => {
    setQuery(e.target.value)
    setOpen(true)
  }

  const handleSelectChange = (e) => {
    const parsed = parseValue(e.target.value)
    if (!parsed) return
    const item = displayItems.find((x) => itemValue(x) === e.target.value)
    if (item) pick(item)
    else onChange?.({
      key: parsed.key,
      bind_type: parsed.bind_type,
      qualification_id: parsed.qualification_id,
      field_name: parsed.key,
      match_status: parsed.bind_type === 'runtime' ? 'runtime' : 'matched',
    })
  }

  return (
    <div className="mapping-resource-picker" ref={wrapRef}>
      <div className="mapping-picker-input-wrap">
        <input
          type="search"
          className="mapping-picker-search"
          value={open ? query : (selectedItem ? itemLabel(selectedItem) : value || '')}
          placeholder={placeholder}
          onChange={handleInputChange}
          onFocus={() => setOpen(true)}
        />
        {loading ? <span className="mapping-picker-loading">…</span> : null}
      </div>
      {open ? (
        <div className="mapping-picker-dropdown">
          {displayItems.length ? displayItems.map((item) => (
            <button
              key={`${item.bind_type}-${item.id || item.key}`}
              type="button"
              className={`mapping-picker-option ${itemValue(item) === selectedVal ? 'active' : ''}`}
              onClick={() => pick(item)}
            >
              <span className={`bind-tag bind-${item.bind_type || 'field'}`}>
                {item.bind_type === 'qual' ? '材料' : item.bind_type === 'runtime' ? '临场' : '字段'}
              </span>
              <span className="mapping-picker-label">{itemLabel(item)}</span>
            </button>
          )) : (
            <div className="mapping-picker-empty muted">未找到匹配项，可尝试其他关键词或现场创建字段</div>
          )}
        </div>
      ) : null}
      <select
        className="mapping-picker-fallback"
        value={selectedVal}
        onChange={handleSelectChange}
        aria-label="映射目标"
      >
        {displayItems.map((item) => (
          <option key={`${item.bind_type}-${item.id || item.key}`} value={itemValue(item)}>
            {itemLabel(item)}
          </option>
        ))}
      </select>
    </div>
  )
}
