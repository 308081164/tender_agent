import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import HistoryCard from '../components/HistoryCard'
import PreviewModal from '../components/PreviewModal'

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

  return (
    <>
      <div className="panel home-hero">
        <div className="home-head">
          <div>
            <h2>历史标书</h2>
            <p className="lead">查看并继续未完成的标书，或打开已导出项目进行复用完善。</p>
          </div>
          <div className="actions" style={{ marginTop: 0 }}>
            <button onClick={startNew} disabled={bootLoading}>新建标书</button>
            <button className="secondary" onClick={() => navigate('/chat')} disabled={bootLoading}>智能助手</button>
            <button className="secondary" onClick={() => navigate('/settings')} disabled={bootLoading}>
              系统设置
            </button>
          </div>
        </div>

        <div className="home-stats">
          <div className="stat-chip">
            <span className="stat-num">{projects.length}</span>
            <span className="stat-label">全部</span>
          </div>
          <div className="stat-chip">
            <span className="stat-num">{projects.filter((p) => p.status !== 'exported').length}</span>
            <span className="stat-label">进行中</span>
          </div>
          <div className="stat-chip">
            <span className="stat-num">{projects.filter((p) => p.status === 'exported').length}</span>
            <span className="stat-label">已导出</span>
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

        <div className="history-grid">
          {filteredProjects.length === 0 && (
            <div className="empty-history">
              <h3>暂无历史标书</h3>
              <p>创建第一份标书后，将在此展示项目名称、招标人、进度与摘要。</p>
              <button onClick={startNew} disabled={bootLoading}>开始新建</button>
            </div>
          )}
          {filteredProjects.map((p) => (
            <HistoryCard
              key={p.id}
              project={p}
              onOpen={openProject}
              onPreview={(proj) => setPreviewTarget(proj)}
            />
          ))}
        </div>
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
