# Windows 桌面运行时验证：构建 staging 后执行 check-only 与嵌入式 Python 自检
param(
  [string]$Stage = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Stage) {
  $Stage = Join-Path $Root "dist\tender-agent-installer-stage"
}

function Assert-PathExists([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path)) {
    throw "$Label not found: $Path"
  }
}

Write-Host "==> Building desktop staging for verification"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "desktop\build.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$InstallDir = Join-Path $Stage "resources\tender-agent"
if (-not (Test-Path -LiteralPath $InstallDir)) {
  $InstallDir = $Stage
}

$Python = Join-Path $InstallDir "runtime\python.exe"
$Launcher = Join-Path $InstallDir "desktop\backend_launcher.py"
$Starter = Join-Path $InstallDir "desktop\start_backend.cmd"
$VerifyData = Join-Path $env:TEMP "TenderAgent-verify-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
New-Item -ItemType Directory -Path $VerifyData -Force | Out-Null

try {
  Assert-PathExists $Python "Python runtime"
  Assert-PathExists $Launcher "backend_launcher.py"
  Assert-PathExists $Starter "start_backend.cmd"
  Assert-PathExists (Join-Path $InstallDir "aspose\Aspose.License.txt") "Aspose license"
  Assert-PathExists (Join-Path $InstallDir "frontend\dist\index.html") "frontend index.html"
  Assert-PathExists (Join-Path $InstallDir "tools\postgres\bin\initdb.exe") "PostgreSQL initdb"
  Assert-PathExists (Join-Path $InstallDir "tools\minio.exe") "MinIO"

  Write-Host "==> Python embed self-test"
  $env:PYTHONHOME = Join-Path $InstallDir "runtime"
  & $Python -c "import uvicorn, fastapi, sqlalchemy, psycopg2, minio, aspose.words; print('imports ok')"
  if ($LASTEXITCODE -ne 0) { throw "Python import self-test failed" }

  Write-Host "==> backend_launcher --check-only"
  $env:TENDER_INSTALL_DIR = $InstallDir
  $env:TENDER_DATA_DIR = $VerifyData
  & $Python -u $Launcher --check-only
  if ($LASTEXITCODE -ne 0) { throw "backend_launcher --check-only failed with code $LASTEXITCODE" }

  Write-Host "==> start_backend.cmd --check-only"
  & $Starter --check-only
  if ($LASTEXITCODE -ne 0) { throw "start_backend.cmd --check-only failed with code $LASTEXITCODE" }

  $launcherLog = Join-Path $VerifyData "launcher.log"
  if (-not (Test-Path -LiteralPath $launcherLog)) {
    throw "launcher.log was not created at $launcherLog"
  }
  Write-Host "VERIFY_OK: Windows desktop runtime checks passed"
  Get-Content -LiteralPath $launcherLog -Tail 5
}
finally {
  if (Test-Path -LiteralPath $VerifyData) {
    Remove-Item -LiteralPath $VerifyData -Recurse -Force -ErrorAction SilentlyContinue
  }
}
