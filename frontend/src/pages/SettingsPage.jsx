import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'

const STATUS_LABEL = { ok: '正常', warn: '警告', error: '异常', info: '可选' }

export default function SettingsPage() {
  const navigate = useNavigate()
  const { settings, showToast, bootLoading } = useApp()
  const {
    settingsInfo, settingsForm, setSettingsForm,
    loading, loadSettings, saveSettings, clearKey, testKey,
  } = settings
  const [envCheck, setEnvCheck] = useState(null)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    loadSettings().catch((e) => showToast(e.message))
  }, [])

  const runEnvCheck = async () => {
    setChecking(true)
    try {
      const res = await api.systemCheck()
      setEnvCheck(res)
      showToast(`环境自检完成：${res.status}`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setChecking(false)
    }
  }

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
              placeholder="deepseek-v4-pro"
            />
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              推荐 <code>deepseek-v4-pro</code>（V4 Pro GA）；轻量场景可用 <code>deepseek-v4-flash</code>
            </div>
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

      <div className="chapter">
        <div className="chapter-head">
          <h4>运行环境自检</h4>
          <button type="button" className="ghost" onClick={runEnvCheck} disabled={checking}>
            {checking ? '检测中…' : '立即检测'}
          </button>
        </div>
        <p className="lead" style={{ marginBottom: 10 }}>
          检测 Aspose 文档引擎、OCR、文档引擎 v2、AI API、OnlyOffice 等组件是否就绪。
        </p>
        {envCheck ? (
          <div className="card-block" style={{ fontSize: 13 }}>
            <p>总体状态：<strong>{envCheck.status}</strong>
              {' · '}正常 {envCheck.summary?.ok || 0}
              {' · '}警告 {envCheck.summary?.warn || 0}
              {' · '}异常 {envCheck.summary?.error || 0}
            </p>
            <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
              {(envCheck.checks || []).map((c) => (
                <li key={c.id} style={{ marginBottom: 6 }}>
                  <strong>{c.name}</strong> — {STATUS_LABEL[c.status] || c.status}
                  {c.detail && typeof c.detail === 'string' ? `: ${c.detail}` : null}
                  {c.id === 'ocr' && c.detail?.tesseract_available === false ? (
                    <span className="muted">（将使用文件名/分类兜底匹配）</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="muted">尚未执行检测，点击「立即检测」。</div>
        )}
      </div>

      <div className="actions">
        <button className="secondary" onClick={() => navigate('/')}>返回</button>
        <button onClick={saveSettings} disabled={loading || bootLoading}>保存设置</button>
      </div>
    </div>
  )
}
