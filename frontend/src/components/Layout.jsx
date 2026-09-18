import React from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

export default function Layout({
  children,
  settingsInfo = null,
  loading = false,
  onStartNew,
}) {
  const navigate = useNavigate()

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand-link">
          <div className="brand-row">
            <span className="brand-logo">T</span>
            <h1 className="brand">标书智能体</h1>
          </div>
        </NavLink>
        <div className="brand-sub">铁路行业投标文件智能编写</div>

        <nav>
          <div className="side-section">工作</div>
          <NavLink to="/" end className={({ isActive }) => `side-item${isActive ? ' active' : ''}`}>
            <span className="side-icon">⌂</span>工作台
          </NavLink>
          <button type="button" className="side-item" onClick={onStartNew} disabled={loading}>
            <span className="side-icon">＋</span>新建标书
          </button>
          <NavLink to="/chat" className={({ isActive }) => `side-item${isActive ? ' active' : ''}`}>
            <span className="side-icon">✦</span>文档 Agent
          </NavLink>

          <div className="side-section">管理</div>
          <NavLink to="/admin" className={({ isActive }) => `side-item${isActive ? ' active' : ''}`}>
            <span className="side-icon">▦</span>数据管理
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => `side-item${isActive ? ' active' : ''}`}>
            <span className="side-icon">⚙</span>系统设置
          </NavLink>
        </nav>

        {settingsInfo && (
          <div className="sidebar-foot">
            AI 模型：{settingsInfo.preferred_provider || 'auto'}
            <br />
            DeepSeek{' '}
            <span className={settingsInfo.deepseek_api_key_set ? 'ok-dot' : 'off-dot'}>●</span>{' '}
            {settingsInfo.deepseek_api_key_set ? '已配置' : '未配置'}
            <br />
            通义千问{' '}
            <span className={settingsInfo.qwen_api_key_set ? 'ok-dot' : 'off-dot'}>●</span>{' '}
            {settingsInfo.qwen_api_key_set ? '已配置' : '未配置'}
          </div>
        )}
      </aside>

      <main className="main">{children}</main>
    </div>
  )
}
