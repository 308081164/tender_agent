import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from './api/client'
import FloatingChat from './components/FloatingChat'
import Toast from './components/Toast'
import AdminConfirmDialog from './components/admin/AdminConfirmDialog'
import { useToast } from './hooks/useToast'
import { useChatSessions } from './hooks/useChat'
import { useSettings } from './hooks/useSettings'

const AppContext = createContext(null)

export function useApp() {
  return useContext(AppContext)
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const hideFloatingChat = location.pathname.startsWith('/chat')
  const { toast, showToast } = useToast()
  const chat = useChatSessions(showToast)
  const settings = useSettings(showToast)

  const [templates, setTemplates] = useState([])
  const [fieldDefs, setFieldDefs] = useState([])
  const [quals, setQuals] = useState([])
  const [categories, setCategories] = useState([])
  const [projects, setProjects] = useState([])
  const [bootLoading, setBootLoading] = useState(true)
  const [confirmNewOpen, setConfirmNewOpen] = useState(false)
  const [creatingProject, setCreatingProject] = useState(false)

  const refreshProjects = async () => {
    const list = await api.projects()
    setProjects(list)
    return list
  }

  const refreshBaseData = async () => {
    const [tpls, defs, qs, cats] = await Promise.all([
      api.templates(),
      api.fields(),
      api.qualifications(),
      api.qualCategories(),
    ])
    setTemplates(tpls)
    setFieldDefs(defs)
    setQuals(qs)
    setCategories(cats)
  }

  useEffect(() => {
    ;(async () => {
      try {
        await api.health()
        const [tpls, defs, qs, cats] = await Promise.all([
          api.templates(),
          api.fields(),
          api.qualifications(),
          api.qualCategories(),
        ])
        setTemplates(tpls)
        setFieldDefs(defs)
        setQuals(qs)
        setCategories(cats)
        await refreshProjects()
        try {
          await settings.loadSettings()
        } catch {
          /* ignore */
        }
      } catch (e) {
        showToast(`初始化失败：${e.message}`)
      } finally {
        setBootLoading(false)
      }
    })()
  }, [])

  const requestStartNew = () => setConfirmNewOpen(true)

  const confirmStartNew = async () => {
    setCreatingProject(true)
    try {
      const p = await api.createProject({ title: '新建标书' })
      await refreshProjects()
      showToast('已创建新标书项目')
      setConfirmNewOpen(false)
      navigate(`/projects/${p.id}/step/1`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setCreatingProject(false)
    }
  }

  const ctx = useMemo(() => ({
    showToast,
    templates,
    fieldDefs,
    quals,
    categories,
    projects,
    refreshProjects,
    refreshBaseData,
    settingsInfo: settings.settingsInfo,
    settings,
    startNew: requestStartNew,
    bootLoading,
  }), [
    showToast, templates, fieldDefs, quals, categories, projects,
    settings, bootLoading,
  ])

  return (
    <AppContext.Provider value={ctx}>
      <Outlet />
      {!hideFloatingChat ? <FloatingChat chat={chat} /> : null}
      <Toast message={toast} />
      <AdminConfirmDialog
        open={confirmNewOpen}
        title="新建标书"
        message="确认创建一份新的标书项目？创建后将进入六步向导。"
        confirmLabel={creatingProject ? '创建中…' : '确认创建'}
        onCancel={() => { if (!creatingProject) setConfirmNewOpen(false) }}
        onConfirm={confirmStartNew}
      />
    </AppContext.Provider>
  )
}
