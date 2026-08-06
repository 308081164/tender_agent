import React, { useEffect, useMemo, useState } from 'react'
import Pagination from './Pagination'

const PAGE_SIZE = 6

function isHistory(t) {
  return t.kind === 'history' || t.is_history
}

function subtitle(t) {
  if (isHistory(t)) return '历史标书 · 智能替换起点'
  if (t.kind === 'skeleton') return '骨架模板 · 联调占位'
  return `工程化模板 · ${t.template_code || 'common'}`
}

export default function Step1TemplatePicker({ templates, selectedId, onSelect }) {
  const engineering = useMemo(() => templates.filter((t) => !isHistory(t)), [templates])
  const history = useMemo(() => templates.filter((t) => isHistory(t)), [templates])

  const [tab, setTab] = useState('template')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    if (!selectedId) return
    const sel = templates.find((t) => t.id === selectedId)
    if (sel) setTab(isHistory(sel) ? 'history' : 'template')
  }, [selectedId, templates])

  useEffect(() => {
    setPage(1)
  }, [tab, search])

  const pool = tab === 'history' ? history : engineering

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return pool
    return pool.filter((t) =>
      [t.name, t.description, t.template_code]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    )
  }, [pool, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  return (
    <>
      <div className="step1-toolbar">
        <div className="filter-tabs">
          <button
            type="button"
            className={`filter-tab ${tab === 'template' ? 'active' : ''}`}
            onClick={() => setTab('template')}
          >
            工程化模板 ({engineering.length})
          </button>
          <button
            type="button"
            className={`filter-tab ${tab === 'history' ? 'active' : ''}`}
            onClick={() => setTab('history')}
          >
            历史标书 ({history.length})
          </button>
        </div>
        <div className="step1-search">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={tab === 'history' ? '搜索历史标书名称…' : '搜索模板名称或编号…'}
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="empty">
          没有匹配的{tab === 'history' ? '历史标书' : '模板'}，请调整搜索词或切换分类。
        </div>
      ) : (
        <>
          <div className="grid-2 step1-grid">
            {pageItems.map((t) => (
              <div
                key={t.id}
                className={`card-select ${selectedId === t.id ? 'selected' : ''}`}
                onClick={() => onSelect(t.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelect(t.id)
                  }
                }}
              >
                <div className="card-select-badge">
                  {isHistory(t) ? '历史' : t.kind === 'skeleton' ? '骨架' : '模板'}
                </div>
                <h3>{t.name}</h3>
                <p>{subtitle(t)}</p>
                {t.description ? <p className="card-select-desc">{t.description}</p> : null}
              </div>
            ))}
          </div>
          <Pagination
            page={safePage}
            totalPages={totalPages}
            total={filtered.length}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </>
      )}
    </>
  )
}
