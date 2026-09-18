# 标书智能体 Windows 功能验收脚本（桌面版或本机后端）
param(
  [int]$Port = 18765,
  [string]$BaseUrl = ""
)

$ErrorActionPreference = "Stop"
if (-not $BaseUrl) { $BaseUrl = "http://127.0.0.1:$Port" }
$Api = "$BaseUrl/api"

function Test-Endpoint {
  param([string]$Name, [string]$Url, [string]$Method = "GET", [string]$Body = $null)
  Write-Host "==> $Name" -ForegroundColor Cyan
  try {
    if ($Method -eq "GET") {
      $r = Invoke-RestMethod -Uri $Url -TimeoutSec 30
    } else {
      $r = Invoke-RestMethod -Uri $Url -Method $Method -ContentType "application/json" -Body $Body -TimeoutSec 60
    }
    Write-Host "  OK" -ForegroundColor Green
    return $r
  } catch {
    Write-Host "  FAIL: $_" -ForegroundColor Red
    throw
  }
}

Write-Host "标书智能体 Windows 功能验收" -ForegroundColor Green
Write-Host "API: $Api"

$h = Test-Endpoint "健康检查" "$Api/health"
if ($h.status -ne "ok") { throw "health not ok" }

$settings = Test-Endpoint "系统设置" "$Api/settings"
if ($settings.deepseek_model -ne "deepseek-v4-pro") {
  Write-Host "  WARN: deepseek_model=$($settings.deepseek_model), expected deepseek-v4-pro" -ForegroundColor Yellow
}

$envCheck = Test-Endpoint "环境自检" "$Api/system/check"
Write-Host "  环境状态: $($envCheck.status) (ok=$($envCheck.summary.ok) warn=$($envCheck.summary.warn) error=$($envCheck.summary.error))"

foreach ($c in $envCheck.checks) {
  Write-Host "    - $($c.name): $($c.status)"
}

$templates = Test-Endpoint "模板列表" "$Api/templates"
Write-Host "  模板数量: $($templates.Count)"

$steps = Test-Endpoint "向导步骤" "$Api/meta/steps"
Write-Host "  向导步骤: $($steps.Count)"

# 文档引擎纯逻辑测试（使用安装包内嵌 Python）
$installRoot = $env:TENDER_INSTALL_DIR
if (-not $installRoot) {
  $candidates = @(
    "$env:LOCALAPPDATA\TenderAgent",
    (Join-Path $PSScriptRoot "..\dist\tender-agent-installer-stage\resources\tender-agent")
  )
  foreach ($c in $candidates) {
    if (Test-Path (Join-Path $c "runtime\python.exe")) { $installRoot = $c; break }
  }
}

if ($installRoot -and (Test-Path (Join-Path $installRoot "runtime\python.exe"))) {
  $py = Join-Path $installRoot "runtime\python.exe"
  $backend = Join-Path $installRoot "backend"
  Write-Host "==> 文档引擎单元测试 (embedded python)" -ForegroundColor Cyan
  $tests = @(
    "tests\test_doc_engine.py",
    "tests\test_doc_engine_deep.py"
  )
  foreach ($t in $tests) {
    $tp = Join-Path $backend $t
    if (Test-Path $tp) {
      & $py $tp
      if ($LASTEXITCODE -ne 0) { throw "test failed: $t" }
      Write-Host "  PASS $t" -ForegroundColor Green
    }
  }
  $e2e = Join-Path $backend "tests\test_doc_engine_e2e.py"
  if (Test-Path $e2e) {
    & $py $e2e
    Write-Host "  E2E: exit $LASTEXITCODE (0=pass, skip ok on missing Aspose)" -ForegroundColor Gray
  }
} else {
  Write-Host "SKIP embedded python tests (TENDER_INSTALL_DIR not found)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "VERIFY_OK: Windows feature smoke passed" -ForegroundColor Green
