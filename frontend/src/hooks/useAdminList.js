import { useCallback, useEffect, useMemo, useState } from 'react'

const DEFAULT_PAGE_SIZE = 20

export function useAdminList(fetchFn, { pageSize = DEFAULT_PAGE_SIZE, extraDeps = [], initialFilters = {} } = {}) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState(initialFilters)
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchFn({ page, pageSize, q: search.trim(), ...filters })
      if (Array.isArray(res)) {
        setItems(res)
        setTotal(res.length)
      } else {
        setItems(res.items || [])
        setTotal(res.total || 0)
      }
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, filters, fetchFn, ...extraDeps])

  useEffect(() => {
    reload()
  }, [reload])

  useEffect(() => {
    setPage(1)
  }, [search, filters])

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / pageSize)),
    [total, pageSize]
  )

  return {
    items,
    total,
    page,
    setPage,
    pageSize,
    search,
    setSearch,
    filters,
    setFilters,
    loading,
    reload,
    totalPages,
  }
}

export function normalizeListResponse(res) {
  if (Array.isArray(res)) return { items: res, total: res.length }
  return { items: res.items || [], total: res.total || 0 }
}
