import { useCallback, useState } from 'react'
import { api } from '../api/client'

const emptyForm = {
  deepseek_api_key: '',
  deepseek_base_url: '',
  deepseek_model: '',
  qwen_api_key: '',
  qwen_base_url: '',
  qwen_model: '',
  preferred_provider: 'auto',
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
      deepseek_model: s.deepseek_model || 'deepseek-chat',
      qwen_api_key: '',
      qwen_base_url: s.qwen_base_url || '',
      qwen_model: s.qwen_model || 'qwen-plus',
      preferred_provider: s.preferred_provider || 'auto',
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
        preferred_provider: settingsForm.preferred_provider,
      }
      if (settingsForm.deepseek_api_key.trim()) {
        payload.deepseek_api_key = settingsForm.deepseek_api_key.trim()
      }
      if (settingsForm.qwen_api_key.trim()) {
        payload.qwen_api_key = settingsForm.qwen_api_key.trim()
      }
      const s = await api.updateSettings(payload)
      setSettingsInfo(s)
      setSettingsForm((f) => ({ ...f, deepseek_api_key: '', qwen_api_key: '' }))
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
        : { clear_qwen_api_key: true }
      const s = await api.updateSettings(payload)
      setSettingsInfo(s)
      showToast?.(provider === 'deepseek' ? '已清除 DeepSeek Key' : '已清除通义千问 Key')
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
      if (provider === 'qwen' && settingsForm.qwen_api_key.trim()) {
        await api.updateSettings({ qwen_api_key: settingsForm.qwen_api_key.trim() })
      }
      const res = await api.testProvider(provider)
      showToast?.(res.message || (res.ok ? '测试成功' : '测试失败'))
      await loadSettings()
      setSettingsForm((f) => ({ ...f, deepseek_api_key: '', qwen_api_key: '' }))
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
