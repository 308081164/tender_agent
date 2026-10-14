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
        配置 DeepSeek / 通义千问 / Kimi K3 API Key。留空保存不会覆盖已有 Key；未配置时 AI 生成将回退到本地模板引擎。
      </p>
      <p className="lead muted" style={{ fontSize: 13, marginTop: -8 }}>
        <strong>路由策略：</strong>纯文本任务（对话、模板映射、分类摘要等）在已配置 DeepSeek 时<strong>优先 DeepSeek</strong>；
        图片/PDF 多模态、资质文件夹扫描<strong>不使用 DeepSeek</strong>，走通义千问 VL 或 Kimi K3（二者至少配置一项）。
      </p>
      {settingsInfo && !settingsInfo.multimodal_ready ? (
        <div className="card-block" style={{ marginBottom: 16, borderColor: 'var(--warn, #c9a227)' }}>
          <strong>多模态未就绪</strong>
          <p className="muted" style={{ margin: '8px 0 0', fontSize: 13 }}>
            {settingsInfo.multimodal_warning || '请配置通义千问 VL 或 Kimi K3 的 API Key，否则无法使用资质文件夹扫描与图片理解。'}
          </p>
        </div>
      ) : null}

      <div className="field" style={{ marginBottom: 18, maxWidth: 360 }}>
        <label>优先使用的模型（主要影响纯文本回退顺序）</label>
        <select
          value={settingsForm.preferred_provider}
          onChange={(e) => setSettingsForm({ ...settingsForm, preferred_provider: e.target.value })}
        >
          <option value="auto">自动（文本：DeepSeek → 千问 → Kimi K3）</option>
          <option value="deepseek">仅 DeepSeek（文本）</option>
          <option value="qwen">仅通义千问（文本）</option>
          <option value="kimi">仅 Kimi K3（文本）</option>
        </select>
      </div>

      <div className="chapter">
        <div className="chapter-head">
          <h4>联网搜索</h4>
          <span className="badge">
            {(settingsForm.web_search_provider || 'duckduckgo') === 'duckduckgo'
              ? 'DuckDuckGo · 无需密钥'
              : settingsInfo?.web_search_api_key_set
                ? `已配置 ${settingsInfo.web_search_api_key_masked}`
                : '未配置密钥'}
          </span>
        </div>
        <p className="lead" style={{ marginBottom: 10 }}>
          对话里说「联网查一下」或打开输入框的「联网」，会检索公开网页并附上来源。默认 DuckDuckGo，不需要另买 API Key。
        </p>
        <div className="form-grid">
          <div className="field">
            <label>搜索来源</label>
            <select
              value={settingsForm.web_search_provider || 'duckduckgo'}
              onChange={(e) => setSettingsForm({ ...settingsForm, web_search_provider: e.target.value })}
            >
              <option value="duckduckgo">DuckDuckGo（默认，无需密钥）</option>
              <option value="tavily">Tavily（需要 API Key）</option>
              <option value="bing">Bing Web Search（需要 API Key）</option>
              <option value="serpapi">SerpAPI（需要 API Key）</option>
            </select>
          </div>
          <div className="field">
            <label>可选 API Key</label>
            <input
              type="password"
              autoComplete="off"
              placeholder={settingsInfo?.web_search_api_key_set ? '已配置，留空则保持不变' : '仅 Tavily / Bing / SerpAPI 需要'}
              value={settingsForm.web_search_api_key}
              onChange={(e) => setSettingsForm({ ...settingsForm, web_search_api_key: e.target.value })}
              disabled={(settingsForm.web_search_provider || 'duckduckgo') === 'duckduckgo'}
            />
          </div>
        </div>
        {(settingsForm.web_search_provider || 'duckduckgo') !== 'duckduckgo'
          && !settingsForm.web_search_api_key.trim()
          && !settingsInfo?.web_search_api_key_set ? (
          <div className="card-block" style={{ marginTop: 12, borderColor: 'var(--warn, #c9a227)' }}>
            <strong>密钥为空</strong>
            <p className="muted" style={{ margin: '8px 0 0', fontSize: 13 }}>
              {settingsInfo?.web_search_empty_state
                || '已选择付费搜索，但尚未填写 API Key。未保存密钥前不会调用该服务，也不会假装已经搜过网。请填写密钥，或改回 DuckDuckGo（无需密钥）。'}
            </p>
          </div>
        ) : null}
        <div className="actions">
          <button
            className="secondary"
            onClick={() => clearKey('web_search')}
            disabled={loading || !settingsInfo?.web_search_api_key_set}
          >
            清除搜索 Key
          </button>
        </div>
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

      <div className={`chapter${settingsInfo?.qwen_vl_ready ? ' chapter-configured' : ''}`}>
        <div className="chapter-head">
          <h4>通义千问（文本 + VL 多模态）</h4>
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
            <label>文本模型</label>
            <input
              value={settingsForm.qwen_model}
              onChange={(e) => setSettingsForm({ ...settingsForm, qwen_model: e.target.value })}
              placeholder="qwen-plus"
            />
          </div>
          <div className="field">
            <label>VL 多模态模型</label>
            <input
              value={settingsForm.qwen_vl_model}
              onChange={(e) => setSettingsForm({ ...settingsForm, qwen_vl_model: e.target.value })}
              placeholder="qwen-vl-plus"
            />
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              资质文件夹扫描、图片/PDF 理解使用 VL 模型（与上方 API Key 相同）
            </div>
          </div>
        </div>
        <div className="actions">
          <button className="ghost" onClick={() => testKey('qwen')} disabled={loading}>测试文本</button>
          <button className="ghost" onClick={() => testKey('qwen_vl')} disabled={loading}>测试 VL</button>
          <button
            className="secondary"
            onClick={() => clearKey('qwen')}
            disabled={loading || !settingsInfo?.qwen_api_key_set}
          >
            清除 Key
          </button>
        </div>
      </div>

      <div className={`chapter${settingsInfo?.kimi_k3_ready ? ' chapter-configured' : ''}`}>
        <div className="chapter-head">
          <h4>Kimi K3（月之暗面）</h4>
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
            <label>文本模型</label>
            <select
              value={['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k', 'kimi-k2-0905-preview'].includes(settingsForm.kimi_model)
                ? settingsForm.kimi_model
                : '__custom__'}
              onChange={(e) => {
                const v = e.target.value
                setSettingsForm({ ...settingsForm, kimi_model: v === '__custom__' ? '' : v })
              }}
            >
              <option value="moonshot-v1-8k">moonshot-v1-8k</option>
              <option value="moonshot-v1-32k">moonshot-v1-32k</option>
              <option value="moonshot-v1-128k">moonshot-v1-128k</option>
              <option value="kimi-k2-0905-preview">kimi-k2-0905-preview</option>
              <option value="__custom__">自定义…</option>
            </select>
            {!['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k', 'kimi-k2-0905-preview'].includes(settingsForm.kimi_model) ? (
              <input
                style={{ marginTop: 8 }}
                value={settingsForm.kimi_model}
                onChange={(e) => setSettingsForm({ ...settingsForm, kimi_model: e.target.value })}
                placeholder="Moonshot 文本 model id"
              />
            ) : null}
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              纯文本自动链 fallback，不参与图片理解
            </div>
          </div>
          <div className="field">
            <label>Kimi K3（多模态）</label>
            <select
              value={['kimi-k3', 'kimi-k2.6', 'moonshot-v1-8k-vision-preview'].includes(settingsForm.kimi_k3_model)
                ? settingsForm.kimi_k3_model
                : '__custom__'}
              onChange={(e) => {
                const v = e.target.value
                setSettingsForm({ ...settingsForm, kimi_k3_model: v === '__custom__' ? '' : v })
              }}
            >
              <option value="kimi-k3">Kimi K3（kimi-k3）</option>
              <option value="kimi-k2.6">kimi-k2.6</option>
              <option value="moonshot-v1-8k-vision-preview">moonshot-v1-8k-vision-preview</option>
              <option value="__custom__">自定义…</option>
            </select>
            {!['kimi-k3', 'kimi-k2.6', 'moonshot-v1-8k-vision-preview'].includes(settingsForm.kimi_k3_model) ? (
              <input
                style={{ marginTop: 8 }}
                value={settingsForm.kimi_k3_model}
                onChange={(e) => setSettingsForm({ ...settingsForm, kimi_k3_model: e.target.value })}
                placeholder="官方多模态 model id"
              />
            ) : null}
          </div>
        </div>
        <div className="actions">
          <button className="ghost" onClick={() => testKey('kimi')} disabled={loading}>测试文本</button>
          <button className="ghost" onClick={() => testKey('kimi_k3')} disabled={loading}>测试 K3</button>
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
                  {c.id === 'ai' && c.detail && typeof c.detail === 'object' && c.detail.message ? (
                    <span className="muted"> — {c.detail.message}</span>
                  ) : null}
                  {c.id === 'onlyoffice' && c.detail && typeof c.detail === 'object' && c.detail.message ? (
                    <span className="muted"> — {c.detail.message}</span>
                  ) : null}
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
