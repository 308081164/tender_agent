import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useApp } from '../App'

export default function NewProjectPage() {
  const navigate = useNavigate()
  const { showToast, refreshProjects } = useApp()
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const p = await api.createProject({ title: '新建标书' })
        if (cancelled) return
        await refreshProjects()
        showToast('已创建新标书项目')
        navigate(`/projects/${p.id}/step/1`, { replace: true })
      } catch (e) {
        if (!cancelled) {
          setError(e.message)
          showToast(e.message)
        }
      }
    })()
    return () => { cancelled = true }
  }, [])

  return (
    <div className="panel">
      <h2>新建标书</h2>
      <p className="lead">{error || '正在创建项目并进入向导…'}</p>
      {error && (
        <div className="actions">
          <button className="secondary" onClick={() => navigate('/')}>返回首页</button>
          <button onClick={() => window.location.reload()}>重试</button>
        </div>
      )}
    </div>
  )
}
