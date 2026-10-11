import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { api } from './api/client'
import FloatingChat from './components/FloatingChat'
import CreateProjectHubModal from './components/project/CreateProjectHubModal'
import Toast from './components/Toast'
import { useToast } from './hooks/useToast'
import { useChatSessions } from './hooks/useChat'
import { useSettings } from './hooks/useSettings'

const AppContext = createContext(null)

export function useApp() {
  return useContext(AppContext)
}

export default function App() {
  const location = useLocation()
  const hideFloatingChat = location.pathname.startsWith('/chat')
    || location.pathname.includes('/workspace')
  const [createHubOpen, setCreateHubOpen] = useState(false)
  const { toast, showToast } = useToast()
  const chat = useChatSessions(showToast)
  const settings = useSettings(showToast)

  const [templates, setTemplates] = useState([])
  const [fieldDefs, setFieldDefs] = useState([])
  const [quals, setQuals] = useState([])
  const [categories, setCategories] = useState([])
  const [projects, setProjects] = useState([])
  const [bootLoading, setBootLoading] = useState(true)
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

  const requestStartNew = () => setCreateHubOpen(true)

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
      {!hideFloatingChat ? <FloatingChat chat={chat} projectPath={location.pathname} /> : null}
      <CreateProjectHubModal
        open={createHubOpen}
        templates={templates}
        onClose={() => setCreateHubOpen(false)}
        showToast={showToast}
      />
      <Toast message={toast} />
    </AppContext.Provider>
  )
}
