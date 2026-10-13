import React from 'react'
import { Link } from 'react-router-dom'
import { CardShell } from './CardShell'

export default function OnboardingGapsCard({ card }) {
  const {
    disclaimer,
    gaps = [],
    verify_recommended = [],
    import_summary,
  } = card.payload || {}

  const suggestions = import_summary?.suggestions || []

  return (
    <CardShell card={card} title={card.title || '核对清单'}>
      {disclaimer ? (
        <div className="onboarding-disclaimer" role="alert">
          {disclaimer.replace(/\*\*/g, '')}
        </div>
      ) : null}

      {import_summary ? (
        <p className="chat-card-hint">
          已处理文件夹：{import_summary.folder || '—'}；新增资质 {import_summary.qual_count ?? 0} 条，
          更新档案 {import_summary.company_applied ?? 0} 项。
        </p>
      ) : null}

      {suggestions.length > 0 ? (
        <div className="onboarding-section">
          <strong>敏感字段建议（未自动覆盖）</strong>
          <ul className="onboarding-gap-list">
            {suggestions.map((s) => (
              <li key={s.key}>
                {s.label}：系统已有值，识别建议「{s.suggested}」— 请
                <Link to={`/admin/company?focus=${encodeURIComponent(s.key)}`}>人工确认</Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {gaps.length > 0 ? (
        <div className="onboarding-section">
          <strong>未填 / 空白项（{gaps.length}）</strong>
          <ul className="onboarding-gap-list">
            {gaps.slice(0, 24).map((g) => (
              <li key={`${g.kind}-${g.key}`} className="gap-empty">
                <span>{g.label}</span>
                <Link to={g.url || '/admin/company'} className="onboarding-gap-link">
                  去填写
                </Link>
              </li>
            ))}
          </ul>
          {gaps.length > 24 ? (
            <p className="chat-card-hint">另有 {gaps.length - 24} 项未列出，请打开企业管理页查看。</p>
          ) : null}
        </div>
      ) : (
        <p className="chat-card-text">核心企业档案项已填写。仍请打开管理页做一次全面核对。</p>
      )}

      {verify_recommended.length > 0 ? (
        <div className="onboarding-section">
          <strong>建议核实</strong>
          <ul className="onboarding-gap-list">
            {verify_recommended.map((g) => (
              <li key={g.key} className="gap-verify">
                <span>{g.label}</span>
                <Link to={g.url} className="onboarding-gap-link">去核实</Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="onboarding-admin-links">
        <Link to="/admin/company" className="chat-action-card primary">企业档案</Link>
        <Link to="/admin/qualifications" className="chat-action-card">资质库</Link>
        <Link to="/admin/fields" className="chat-action-card">字段管理</Link>
      </div>
    </CardShell>
  )
}
