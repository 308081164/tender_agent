import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

export function useProjectContext(projectId, { enabled = true } = {}) {
  const [context, setContext] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    if (!projectId || !enabled) return null
    setLoading(true)
    setError('')
    try {
      const data = await api.getProjectContext(projectId)
      setContext(data)
      return data
    } catch (e) {
      setError(e.message)
      return null
    } finally {
      setLoading(false)
    }
  }, [projectId, enabled])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { context, loading, error, refresh }
}
