export const RECENT_WORKSPACE_KEY = 'tender_recent_workspace_dirs'

export function readRecentWorkspaceDirs(limit = 8) {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_WORKSPACE_KEY) || '[]')
    return Array.isArray(raw) ? raw.filter(Boolean).slice(0, limit) : []
  } catch {
    return []
  }
}

export function pushRecentWorkspaceDir(dir) {
  const path = (dir || '').trim()
  if (!path) return
  try {
    const prev = readRecentWorkspaceDirs(20)
    const next = [path, ...prev.filter((d) => d !== path)].slice(0, 12)
    localStorage.setItem(RECENT_WORKSPACE_KEY, JSON.stringify(next))
  } catch {
    /* ignore */
  }
}

export function formatWorkspaceDirLabel(dir) {
  const d = (dir || '').trim()
  if (!d) return '默认目录'
  const parts = d.split(/[/\\]/).filter(Boolean)
  if (parts.length <= 2) return d
  return `…/${parts.slice(-2).join('/')}`
}
