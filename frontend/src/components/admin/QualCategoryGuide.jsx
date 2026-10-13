import React from 'react'
import { QUAL_CATEGORY_OPTIONS } from '../../constants/qualCategories'
import AdminEmptyState from './AdminEmptyState'

export default function QualCategoryGuide({ activeCategory, onAddInCategory, onAdd }) {
  const filtered = activeCategory
    ? QUAL_CATEGORY_OPTIONS.filter((o) => o.value === activeCategory)
    : QUAL_CATEGORY_OPTIONS

  const title = activeCategory
    ? `「${activeCategory}」下暂无资质`
    : '暂无资质'
  const hint = activeCategory
    ? '可在此分类下新增，或通过 Agent 导入文件夹后自动归类。'
    : '资质按七大类管理；可从任一类开始入库，或通过 Agent 扫描企业资质文件夹批量导入。'

  return (
    <div className="qual-category-guide">
      <AdminEmptyState
        title={title}
        hint={hint}
        action={(
          <button type="button" onClick={() => onAdd(activeCategory || '')}>
            新增资质
          </button>
        )}
      />
      <div className="qual-category-grid">
        {filtered.map(({ value, description }) => (
          <article key={value} className="qual-category-card card-block">
            <h4>{value}</h4>
            <p className="muted">{description}</p>
            <button type="button" className="secondary tiny" onClick={() => onAddInCategory(value)}>
              在该分类下新增
            </button>
          </article>
        ))}
      </div>
    </div>
  )
}
