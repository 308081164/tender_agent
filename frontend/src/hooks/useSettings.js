import { useCallback, useState } from 'react'
import { api } from '../api/client'

const emptyForm = {
  deepseek_api_key: '',
  deepseek_base_url: '',
  deepseek_model: '',
  qwen_api_key: '',
  qwen_base_url: '',
  qwen_model: '',
  qwen_vl_model: '',
  kimi_api_key: '',
  kimi_base_url: '',
  kimi_model: '',
  kimi_k3_model: '',
  preferred_provider: 'auto',
  web_search_provider: 'deepseek',
  web_search_api_key: '',
}

export function useSettings(showToast) {
  const [settingsInfo, setSettingsInfo] = useState(null)
  const [settingsForm, setSettingsForm] = useState(emptyForm)
  const [loading, setLoading] = useState(false)

  const loadSettings = useCallback(async () => {
    const s = await api.getSettings()
    setSettingsInfo(s)
    setSettingsForm({
      deepseek_api_key: '',
      deepseek_base_url: s.deepseek_base_url || '',
      deepseek_model: s.deepseek_model || 'deepseek-flash',
      qwen_api_key: '',
      qwen_base_url: s.qwen_base_url || '',
      qwen_model: s.qwen_model || 'qwen-plus',
      qwen_vl_model: s.qwen_vl_model || 'qwen-vl-plus',
      kimi_api_key: '',
      kimi_base_url: s.kimi_base_url || 'https://api.moonshot.cn/v1',
      kimi_model: s.kimi_model || 'moonshot-v1-8k',
      kimi_k3_model: s.kimi_k3_model || 'kimi-k3',
      preferred_provider: s.preferred_provider || 'auto',
      web_search_provider: s.web_search_provider || 'duckduckgo',
      web_search_api_key: '',
    })
    return s
  }, [])

  const saveSettings = useCallback(async () => {
    setLoading(true)
    try {
      const payload = {
        deepseek_base_url: settingsForm.deepseek_base_url,
        deepseek_model: settingsForm.deepseek_model,
        qwen_base_url: settingsForm.qwen_base_url,
        qwen_model: settingsForm.qwen_model,
        qwen_vl_model: settingsForm.qwen_vl_model,
        kimi_base_url: settingsForm.kimi_base_url,
        kimi_model: settingsForm.kimi_model,
        kimi_k3_model: settingsForm.kimi_k3_model,
        preferred_provider: settingsForm.preferred_provider,
        web_search_provider: settingsForm.web_search_provider || 'deepseek',
      }
      if (settingsForm.web_search_api_key.trim()) {
        payload.web_search_api_key = settingsForm.web_search_api_key.trim()
      }
      if (settingsForm.deepseek_api_key.trim()) {
        payload.deepseek_api_key = settingsForm.deepseek_api_key.trim()
      }
      if (settingsForm.qwen_api_key.trim()) {
        payload.qwen_api_key = settingsForm.qwen_api_key.trim()
      }
      if (settingsForm.kimi_api_key.trim()) {
        payload.kimi_api_key = settingsForm.kimi_api_key.trim()
      }
      const s = await api.updateSettings(payload)
      setSettingsInfo(s)
      setSettingsForm((f) => ({
        ...f,
        deepseek_api_key: '',
        qwen_api_key: '',
        kimi_api_key: '',
        web_search_api_key: '',
        web_search_provider: s.web_search_provider || f.web_search_provider || 'duckduckgo',
      }))
      showToast?.('系统设置已保存')
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setLoading(false)
    }
  }, [settingsForm, showToast])

  const clearKey = useCallback(async (provider) => {
    setLoading(true)
    try {
      const payload = provider === 'deepseek'
        ? { clear_deepseek_api_key: true }
        : provider === 'qwen'
          ? { clear_qwen_api_key: true }
          : provider === 'web_search'
            ? { clear_web_search_api_key: true }
            : { clear_kimi_api_key: true }
      const s = await api.updateSettings(payload)
      setSettingsInfo(s)
      const cleared = provider === 'deepseek'
        ? '已清除 DeepSeek Key'
        : provider === 'qwen'
          ? '已清除通义千问 Key'
          : provider === 'web_search'
            ? '已清除联网搜索 Key'
            : '已清除 Kimi K3 Key'
      showToast?.(cleared)
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setLoading(false)
    }
  }, [showToast])

  const testKey = useCallback(async (provider) => {
    setLoading(true)
    try {
      if (provider === 'deepseek' && settingsForm.deepseek_api_key.trim()) {
        await api.updateSettings({ deepseek_api_key: settingsForm.deepseek_api_key.trim() })
      }
      if ((provider === 'qwen' || provider === 'qwen_vl') && settingsForm.qwen_api_key.trim()) {
        await api.updateSettings({ qwen_api_key: settingsForm.qwen_api_key.trim() })
      }
      if ((provider === 'kimi' || provider === 'kimi_k3') && settingsForm.kimi_api_key.trim()) {
        await api.updateSettings({ kimi_api_key: settingsForm.kimi_api_key.trim() })
      }
      const res = await api.testProvider(provider)
      showToast?.(res.message || (res.ok ? '测试成功' : '测试失败'))
      await loadSettings()
      setSettingsForm((f) => ({ ...f, deepseek_api_key: '', qwen_api_key: '', kimi_api_key: '' }))
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setLoading(false)
    }
  }, [settingsForm, loadSettings, showToast])

  return {
    settingsInfo,
    setSettingsInfo,
    settingsForm,
    setSettingsForm,
    loading,
    loadSettings,
    saveSettings,
    clearKey,
    testKey,
  }
}
