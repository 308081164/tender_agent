import { useCallback, useState } from 'react'
import { api } from '../api/client'

const MAX_CONTEXT_CHARS = 12000

/**
 * 文件树选中 → 读取文本内容并供发送 context 使用。
 */
export function useWorkspaceFileSelection(sessionId, showToast) {
  const [selectedPath, setSelectedPath] = useState('')
  const [loadedFile, setLoadedFile] = useState(null)
  const [fileLoading, setFileLoading] = useState(false)

  const clearFile = useCallback(() => {
    setSelectedPath('')
    setLoadedFile(null)
  }, [])

  const selectFile = useCallback(async (path) => {
    const rel = (path || '').trim()
    setSelectedPath(rel)
    if (!rel) {
      setLoadedFile(null)
      return
    }
    if (!sessionId) {
      setLoadedFile({ path: rel, charCount: null, content: '', binary: true })
      return
    }
    setFileLoading(true)
    try {
      const data = await api.readWorkspaceFile(sessionId, rel)
      if (data.binary) {
        setLoadedFile({
          path: rel,
          charCount: null,
          content: '',
          binary: true,
          sizeBytes: data.size_bytes,
        })
        showToast?.('该文件为二进制格式，已记录路径；如需编辑请说明具体操作')
      } else {
        const text = data.content || ''
        const truncated = text.length > MAX_CONTEXT_CHARS
        setLoadedFile({
          path: rel,
          charCount: text.length,
          content: truncated ? text.slice(0, MAX_CONTEXT_CHARS) : text,
          truncated,
          binary: false,
        })
      }
    } catch (e) {
      showToast?.(e.message || '读取文件失败')
      setLoadedFile({ path: rel, charCount: null, content: '', error: true })
    } finally {
      setFileLoading(false)
    }
  }, [sessionId, showToast])

  const buildFileContext = useCallback(() => {
    if (!selectedPath) return {}
    const ctx = { workspace_file: selectedPath }
    if (loadedFile?.content && !loadedFile.binary) {
      ctx.workspace_file_content = loadedFile.content
      if (loadedFile.truncated) ctx.workspace_file_truncated = true
    }
    return ctx
  }, [selectedPath, loadedFile])

  return {
    selectedPath,
    loadedFile,
    fileLoading,
    selectFile,
    clearFile,
    buildFileContext,
    setSelectedPath,
    setLoadedFile,
  }
}
