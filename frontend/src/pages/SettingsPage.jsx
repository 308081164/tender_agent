import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'

export default function SettingsPage() {
  const navigate = useNavigate()
  const { settings, showToast, bootLoading } = useApp()
  const {
    settingsInfo, settingsForm, setSettingsForm,
    loading, loadSettings, saveSettings, clearKey, testKey,
  } = settings

  useEffect(() => {
    loadSettings().catch((e) => showToast(e.message))
  }, [])

  return (
    <div className="panel">
      <h2>系统设置</h2>
      <p className="lead">
        配置 DeepSeek / 通义千问 API Key。留空保存不会覆盖已有 Key；未配置时 AI 生成将回退到本地模板引擎。
      </p>

      <div className="field" style={{ marginBottom: 18, maxWidth: 360 }}>
        <label>优先使用的模型</label>
        <select
          value={settingsForm.preferred_provider}
          onChange={(e) => setSettingsForm({ ...settingsForm, preferred_provider: e.target.value })}
        >
          <option value="auto">自动（先 DeepSeek，失败再用千问）</option>
          <option value="deepseek">仅 DeepSeek</option>
          <option value="qwen">仅通义千问</option>
        </select>
      </div>

      <div className="chapter">
        <div className="chapter-head">
          <h4>DeepSeek</h4>
          <span className="badge">
            {settingsInfo?.deepseek_api_key_set
              ? `已配置 ${settingsInfo.deepseek_api_key_masked}`
              : '未配置'}
          </span>
        </div>
        <div className="form-grid">
          <div className="field full">
            <label>API Key（输入新值以更新）</label>
            <input
              type="password"
              autoComplete="off"
              placeholder={settingsInfo?.deepseek_api_key_set ? '已配置，留空则保持不变' : 'sk-...'}
              value={settingsForm.deepseek_api_key}
              onChange={(e) => setSettingsForm({ ...settingsForm, deepseek_api_key: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Base URL</label>
            <input
              value={settingsForm.deepseek_base_url}
              onChange={(e) => setSettingsForm({ ...settingsForm, deepseek_base_url: e.target.value })}
            />
          </div>
          <div className="field">
            <label>模型</label>
            <input
              value={settingsForm.deepseek_model}
              onChange={(e) => setSettingsForm({ ...settingsForm, deepseek_model: e.target.value })}
              placeholder="deepseek-chat"
            />
          </div>
        </div>
        <div className="actions">
          <button className="ghost" onClick={() => testKey('deepseek')} disabled={loading}>测试连接</button>
          <button
            className="secondary"
            onClick={() => clearKey('deepseek')}
            disabled={loading || !settingsInfo?.deepseek_api_key_set}
          >
            清除 Key
          </button>
        </div>
      </div>

      <div className="chapter">
        <div className="chapter-head">
          <h4>通义千问</h4>
          <span className="badge">
            {settingsInfo?.qwen_api_key_set
              ? `已配置 ${settingsInfo.qwen_api_key_masked}`
              : '未配置'}
          </span>
        </div>
        <div className="form-grid">
          <div className="field full">
            <label>API Key（输入新值以更新）</label>
            <input
              type="password"
              autoComplete="off"
              placeholder={settingsInfo?.qwen_api_key_set ? '已配置，留空则保持不变' : 'sk-...'}
              value={settingsForm.qwen_api_key}
              onChange={(e) => setSettingsForm({ ...settingsForm, qwen_api_key: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Base URL</label>
            <input
              value={settingsForm.qwen_base_url}
              onChange={(e) => setSettingsForm({ ...settingsForm, qwen_base_url: e.target.value })}
            />
          </div>
          <div className="field">
            <label>模型</label>
            <input
              value={settingsForm.qwen_model}
              onChange={(e) => setSettingsForm({ ...settingsForm, qwen_model: e.target.value })}
              placeholder="qwen-plus"
            />
          </div>
        </div>
        <div className="actions">
          <button className="ghost" onClick={() => testKey('qwen')} disabled={loading}>测试连接</button>
          <button
            className="secondary"
            onClick={() => clearKey('qwen')}
            disabled={loading || !settingsInfo?.qwen_api_key_set}
          >
            清除 Key
          </button>
        </div>
      </div>

      <div className="actions">
        <button className="secondary" onClick={() => navigate('/')}>返回</button>
        <button onClick={saveSettings} disabled={loading || bootLoading}>保存设置</button>
      </div>
    </div>
  )
}
