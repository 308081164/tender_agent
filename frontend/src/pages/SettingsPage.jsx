import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import LogViewerModal from '../components/LogViewerModal'

const STATUS_LABEL = { ok: '正常', warn: '警告', error: '异常', info: '可选' }
const OVERALL_STATUS_LABEL = { green: '正常', yellow: '警告', red: '异常' }

function EnvStatusBadge({ status }) {
  const css =
    status === 'green' ? 'ok'
      : status === 'yellow' ? 'warn'
        : status === 'red' ? 'error'
          : status
  const label = STATUS_LABEL[status] || OVERALL_STATUS_LABEL[status] || status
  return <span className={`check-status-badge status-${css}`}>{label}</span>
}

export default function SettingsPage() {
  const navigate = useNavigate()
  const { settings, showToast, bootLoading } = useApp()
  const {
    settingsInfo, settingsForm, setSettingsForm,
    loading, loadSettings, saveSettings, clearKey, testKey,
  } = settings
  const [envCheck, setEnvCheck] = useState(null)
  const [checking, setChecking] = useState(false)
  const [logModalOpen, setLogModalOpen] = useState(false)

  useEffect(() => {
    loadSettings().catch((e) => showToast(e.message))
  }, [])

  const runEnvCheck = async () => {
    setChecking(true)
    try {
      const res = await api.systemCheck()
      setEnvCheck(res)
      const label = OVERALL_STATUS_LABEL[res.status] || res.status
      showToast(`环境自检完成：${label}`)
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
        配置 DeepSeek / 通义千问 / Kimi（月之暗面）API Key。留空保存不会覆盖已有 Key；未配置时 AI 生成将回退到本地模板引擎。
      </p>

      <div className="field" style={{ marginBottom: 18, maxWidth: 360 }}>
        <label>优先使用的模型</label>
        <select
          value={settingsForm.preferred_provider}
          onChange={(e) => setSettingsForm({ ...settingsForm, preferred_provider: e.target.value })}
        >
          <option value="auto">自动（DeepSeek → 千问 → Kimi）</option>
          <option value="deepseek">仅 DeepSeek</option>
          <option value="qwen">仅通义千问</option>
          <option value="kimi">仅 Kimi</option>
        </select>
      </div>

      <div className={`chapter${settingsInfo?.deepseek_api_key_set ? ' chapter-configured' : ''}`}>
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

      <div className={`chapter${settingsInfo?.qwen_api_key_set ? ' chapter-configured' : ''}`}>
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

      <div className={`chapter${settingsInfo?.kimi_api_key_set ? ' chapter-configured' : ''}`}>
        <div className="chapter-head">
          <h4>Kimi（月之暗面）</h4>
          <span className="badge">
            {settingsInfo?.kimi_api_key_set
              ? `已配置 ${settingsInfo.kimi_api_key_masked}`
              : '未配置'}
          </span>
        </div>
        <div className="form-grid">
          <div className="field full">
            <label>API Key（输入新值以更新）</label>
            <input
              type="password"
              autoComplete="off"
              placeholder={settingsInfo?.kimi_api_key_set ? '已配置，留空则保持不变' : 'sk-...'}
              value={settingsForm.kimi_api_key}
              onChange={(e) => setSettingsForm({ ...settingsForm, kimi_api_key: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Base URL</label>
            <input
              value={settingsForm.kimi_base_url}
              onChange={(e) => setSettingsForm({ ...settingsForm, kimi_base_url: e.target.value })}
            />
          </div>
          <div className="field">
            <label>模型</label>
            <input
              value={settingsForm.kimi_model}
              onChange={(e) => setSettingsForm({ ...settingsForm, kimi_model: e.target.value })}
              placeholder="moonshot-v1-8k"
            />
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              常用 <code>moonshot-v1-8k</code>、<code>moonshot-v1-32k</code>；长文档可用 <code>moonshot-v1-128k</code>
            </div>
          </div>
        </div>
        <div className="actions">
          <button className="ghost" onClick={() => testKey('kimi')} disabled={loading}>测试连接</button>
          <button
            className="secondary"
            onClick={() => clearKey('kimi')}
            disabled={loading || !settingsInfo?.kimi_api_key_set}
          >
            清除 Key
          </button>
        </div>
      </div>

      <div className="chapter">
        <div className="chapter-head">
          <h4>运行环境自检</h4>
          <div className="chapter-head-actions">
            <button type="button" className="ghost" onClick={() => setLogModalOpen(true)}>
              查看日志
            </button>
            <button type="button" className="ghost" onClick={runEnvCheck} disabled={checking}>
              {checking ? '检测中…' : '立即检测'}
            </button>
          </div>
        </div>
        <p className="lead" style={{ marginBottom: 10 }}>
          检测 Aspose 文档引擎、OCR、文档引擎 v2、AI API、OnlyOffice 等组件是否就绪。
        </p>
        {envCheck ? (
          <div className="card-block" style={{ fontSize: 13 }}>
            <p className="env-check-summary">
              总体状态：
              <EnvStatusBadge status={envCheck.status} />
              {' · '}正常 {envCheck.summary?.ok || 0}
              {' · '}警告 {envCheck.summary?.warn || 0}
              {' · '}异常 {envCheck.summary?.error || 0}
            </p>
            <ul className="env-check-list">
              {(envCheck.checks || []).map((c) => (
                <li key={c.id}>
                  <strong>{c.name}</strong>
                  {' '}
                  <EnvStatusBadge status={c.status} />
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

      <LogViewerModal
        open={logModalOpen}
        onClose={() => setLogModalOpen(false)}
        showToast={showToast}
      />
    </div>
  )
}
