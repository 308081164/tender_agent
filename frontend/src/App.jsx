import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { api } from './api/client'
import FloatingChat from './components/FloatingChat'
import Toast from './components/Toast'
import { useToast } from './hooks/useToast'
import { useChatSessions } from './hooks/useChat'
import { useSettings } from './hooks/useSettings'

const AppContext = createContext(null)

export function useApp() {
  return useContext(AppContext)
}

export default function App() {
  const navigate = useNavigate()
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

  const startNew = () => navigate('/projects/new')

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
    startNew,
    bootLoading,
  }), [
    showToast, templates, fieldDefs, quals, categories, projects,
    settings, bootLoading, startNew,
  ])

  return (
    <AppContext.Provider value={ctx}>
      <Outlet />
      <FloatingChat chat={chat} />
      <Toast message={toast} />
    </AppContext.Provider>
  )
}
