import React from 'react'

/** VS Code / Cursor 风格：切换工程目录侧栏 */
export default function DocWorkspaceSidebarToggle({ active, onClick, disabled, title }) {
  const label = title || (active ? '隐藏工程目录' : '显示工程目录')
  return (
    <button
      type="button"
      className={`doc-sidebar-toggle icon-btn${active ? ' active' : ''}`}
      onClick={onClick}
      disabled={disabled}
      title={`${label} · Ctrl+B`}
      aria-label={label}
      aria-pressed={active}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
        <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M9 4v16" stroke="currentColor" strokeWidth="1.6" />
        <path d="M5.5 8h2.5M5.5 11h2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    </button>
  )
}
