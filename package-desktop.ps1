# 标书智能体 Windows 离线安装包一键打包
# 输出: dist/TenderAgentSetup.exe, dist/tender-agent-installer-stage/
#
# 用法:
#   .\package-desktop.ps1
#   .\package-desktop.ps1 -StageOnly
#   .\package-desktop.ps1 -AppVersion "1.0.1"

param(
  [switch]$StageOnly,
  [string]$AppVersion = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Stage = Join-Path $Root "dist\tender-agent-installer-stage"
$SetupExe = Join-Path $Root "dist\TenderAgentSetup.exe"
$IssFile = Join-Path $Root "installer\tender_agent.iss"

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-InnoSetupCompiler {
  $candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
  )
  foreach ($path in $candidates) {
    if (Test-Path $path) { return $path }
  }
  $cmd = Get-Command iscc -ErrorAction SilentlyContinue
  if ($cmd -and (Test-Path $cmd.Source)) { return $cmd.Source }
  return $null
}

function Test-CommandExists([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Format-FileSize([long]$Bytes) {
  if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
  if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
  if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
  return "$Bytes B"
}

Write-Host "标书智能体离线安装包构建" -ForegroundColor Green
Write-Host "Root: $Root" -ForegroundColor Gray

Write-Step "Checking prerequisites"
$missing = @()
if (-not (Test-CommandExists "node")) { $missing += "Node.js" }
if (-not (Test-CommandExists "npm")) { $missing += "npm" }

$hasPython = $false
foreach ($ver in @("3.11", "3.12", "3.13")) {
  try {
    & py "-$ver" -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) { $hasPython = $true; break }
  } catch { }
}
if (-not $hasPython) {
  $pyCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pyCmd -and $pyCmd.Source -notmatch "msys|mingw|ucrt64") {
    $hasPython = $true
  }
}
if (-not $hasPython) {
  $missing += "Python 3.11+ from python.org"
}

if ($missing.Count -gt 0) {
  Write-Host "Missing dependencies:" -ForegroundColor Red
  foreach ($item in $missing) { Write-Host " - $item" -ForegroundColor Yellow }
  exit 1
}

if (-not $StageOnly) {
  $iscc = Resolve-InnoSetupCompiler
  if (-not $iscc) {
    Write-Host "Inno Setup 6 (ISCC.exe) not found." -ForegroundColor Red
    Write-Host "Install: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    exit 1
  }
}

Write-Step "Building staging"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "desktop\build.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path (Join-Path $Stage "TenderAgent.exe"))) {
  Write-Host "TenderAgent.exe not found in staging." -ForegroundColor Red
  exit 1
}

if ($StageOnly) {
  Write-Host "Staging ready: $Stage\TenderAgent.exe"
  exit 0
}

Write-Step "Compiling installer (Inno Setup)"
$isccArgs = @()
if ($AppVersion) {
  $isccArgs += "/DMyAppVersion=$AppVersion"
}
$isccArgs += $IssFile
& $iscc @isccArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path $SetupExe)) {
  Write-Host "Setup exe not found: $SetupExe" -ForegroundColor Red
  exit 1
}

$setupInfo = Get-Item $SetupExe
Write-Host ""
Write-Host "Pack complete!" -ForegroundColor Green
Write-Host "Installer: $($setupInfo.FullName)" -ForegroundColor Gray
Write-Host "Size: $(Format-FileSize $setupInfo.Length)"
