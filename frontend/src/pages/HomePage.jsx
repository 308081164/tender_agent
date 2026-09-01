import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import PreviewModal from '../components/PreviewModal'
import { formatTime } from '../utils/format'
import { STEPS } from '../constants'

export default function HomePage() {
  const navigate = useNavigate()
  const { projects, refreshProjects, showToast, bootLoading } = useApp()
  const [homeFilter, setHomeFilter] = useState('all')
  const [previewTarget, setPreviewTarget] = useState(null)

  useEffect(() => {
    refreshProjects().catch((e) => showToast(e.message))
  }, [])

  const filteredProjects = useMemo(() => {
    if (homeFilter === 'draft') return projects.filter((p) => p.status !== 'exported')
    if (homeFilter === 'exported') return projects.filter((p) => p.status === 'exported')
    return projects
  }, [projects, homeFilter])

  const openProject = (p) => {
    const step = Math.min(p.current_step || 1, 6)
    navigate(`/projects/${p.id}/step/${step}`)
  }

  const startNew = () => navigate('/projects/new')

  const stats = {
    all: projects.length,
    draft: projects.filter((p) => p.status !== 'exported').length,
    exported: projects.filter((p) => p.status === 'exported').length,
  }

  return (
    <>
      <div className="panel home-hero">
        <div className="home-head">
          <div>
            <h2>工作台</h2>
            <p className="lead">继续处理进行中的标书，或从模板快速开始一份新标书。</p>
          </div>
          <div className="actions" style={{ marginTop: 0 }}>
            <button className="secondary" onClick={() => navigate('/chat')} disabled={bootLoading}>
              文档 Agent
            </button>
            <button onClick={startNew} disabled={bootLoading}>新建标书</button>
          </div>
        </div>

        <div className="home-stats">
          <div className="stat-chip">
            <div><span className="stat-num">{stats.all}</span><br /><span className="stat-label">全部项目</span></div>
            <span className="stat-icon">▦</span>
          </div>
          <div className="stat-chip">
            <div><span className="stat-num">{stats.draft}</span><br /><span className="stat-label">进行中</span></div>
            <span className="stat-icon">→</span>
          </div>
          <div className="stat-chip">
            <div><span className="stat-num">{stats.exported}</span><br /><span className="stat-label">已导出</span></div>
            <span className="stat-icon">✓</span>
          </div>
        </div>

        <div className="filter-tabs">
          {[
            { key: 'all', label: '全部' },
            { key: 'draft', label: '进行中' },
            { key: 'exported', label: '已导出' },
          ].map((tab) => (
            <button
              key={tab.key}
              className={`filter-tab ${homeFilter === tab.key ? 'active' : ''}`}
              onClick={() => setHomeFilter(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {filteredProjects.length === 0 ? (
          <div className="empty-history">
            <h3>暂无标书项目</h3>
            <p>创建第一份标书后，将在此展示项目名称、招标人、进度与状态。</p>
            <button onClick={startNew} disabled={bootLoading}>开始新建</button>
          </div>
        ) : (
          <div className="panel project-table-card">
            <table className="project-table">
              <thead>
                <tr>
                  <th>项目</th>
                  <th>当前步骤</th>
                  <th>状态</th>
                  <th>更新时间</th>
                  <th style={{ width: 140 }}></th>
                  </tr>
              </thead>
              <tbody>
                {filteredProjects.map((p) => {
                  const s = p.summary || {}
                  const exported = p.status === 'exported'
                  const stepName = s.step_name
                    || STEPS.find((x) => x.step === Math.min(p.current_step || 1, 6))?.name
                    || `步骤 ${p.current_step}/6`
                  return (
                    <tr key={p.id} onClick={() => openProject(p)}>
                      <td className="project-title-cell">
                        <strong>{s.project_name || p.title || `标书 #${p.id}`}</strong>
                        <small>{s.brief || '尚未填写关键信息'}</small>
                      </td>
                      <td>{stepName}</td>
                      <td>
                        <span className={`status-pill ${exported ? 'exported' : 'draft'}`}>
                          {s.status_label || (exported ? '已导出' : '进行中')}
                        </span>
                      </td>
                      <td className="muted">{formatTime(p.updated_at || p.created_at)}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className="history-card-actions">
                          {exported && (
                            <button type="button" className="ghost tiny" onClick={() => setPreviewTarget(p)}>
                              预览
                            </button>
                          )}
                          <button type="button" className="ghost tiny" onClick={() => openProject(p)}>
                            继续
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {previewTarget && (
        <PreviewModal
          projectId={previewTarget.id}
          onClose={() => setPreviewTarget(null)}
          showToast={showToast}
        />
      )}
    </>
  )
}
