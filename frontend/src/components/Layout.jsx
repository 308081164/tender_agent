import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import StepNav from './StepNav'

export default function Layout({
  children,
  project = null,
  activeStep = 1,
  onGoStep,
  settingsInfo = null,
  loading = false,
  onStartNew,
}) {
  const navigate = useNavigate()
  const inWizard = Boolean(project)

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link to="/" className="brand-link">
          <h1 className="brand">标书智能体</h1>
        </Link>
        <div className="brand-sub">铁路行业投标文件智能编写</div>
        {inWizard ? (
          <StepNav
            project={project}
            activeStep={activeStep}
            onGoStep={onGoStep}
          />
        ) : (
          <div className="empty">创建或打开标书后显示六步向导。</div>
        )}
        <div className="actions" style={{ marginTop: 24 }}>
          <button className="secondary" onClick={() => navigate('/')}>项目列表</button>
          <button onClick={onStartNew} disabled={loading}>新建标书</button>
          <button className="ghost" onClick={() => navigate('/settings')} disabled={loading}>系统设置</button>
          <button className="ghost" onClick={() => navigate('/admin')} disabled={loading}>数据管理</button>
        </div>
        {settingsInfo && (
          <div style={{ marginTop: 16, fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
            AI：{settingsInfo.preferred_provider || 'auto'}
            <br />
            DeepSeek：{settingsInfo.deepseek_api_key_set ? '已配置' : '未配置'}
            <br />
            通义千问：{settingsInfo.qwen_api_key_set ? '已配置' : '未配置'}
          </div>
        )}
      </aside>

      <main className="main">{children}</main>
    </div>
  )
}
