# 标书智能体 Windows 桌面安装包 staging 构建
# 输出: dist/tender-agent-installer-stage/ (Electron + Python + PostgreSQL + MinIO)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $Root

$Stage = Join-Path $Root "dist\tender-agent-installer-stage"
$ElectronBuild = Join-Path $Root "dist\electron-build"
$ElectronDir = Join-Path $Root "desktop\electron"
$PgVersion = "16.6-1"
$PgZipName = "postgresql-$PgVersion-windows-x64-binaries.zip"
$PgUrl = "https://get.enterprisedb.com/postgresql/$PgZipName"
$MinioUrl = "https://dl.min.io/server/minio/release/windows-amd64/minio.exe"
$PythonVersion = "3.11.9"
$EmbedZipName = "python-$PythonVersion-embed-amd64.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/$EmbedZipName"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"

function Resolve-AsposeAssets {
  param([string]$ProjectRoot)

  $vendorDir = Join-Path $ProjectRoot "vendor\aspose-words"
  $vendorLicense = Join-Path $vendorDir "Aspose.License.txt"
  $vendorWheel = Get-ChildItem -Path $vendorDir -Filter "aspose_words-*-win_amd64.whl" -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($vendorWheel -and (Test-Path -LiteralPath $vendorLicense)) {
    return @{
      Dir = $vendorDir
      Wheel = $vendorWheel.FullName
      License = $vendorLicense
    }
  }

  $docsRoot = Join-Path $ProjectRoot "docs"
  if (-not (Test-Path -LiteralPath $docsRoot)) {
    throw "Aspose assets not found: docs/ directory missing"
  }

  $licenses = Get-ChildItem -Path $docsRoot -Recurse -Filter "Aspose.License.txt" -File -ErrorAction SilentlyContinue
  foreach ($license in $licenses) {
    $dir = $license.DirectoryName
    $wheel = Get-ChildItem -Path $dir -Filter "aspose_words-*-win_amd64.whl" -File -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($wheel) {
      return @{
        Dir = $dir
        Wheel = $wheel.FullName
        License = $license.FullName
      }
    }
  }

  throw "Aspose license + Windows wheel not found under docs/. Ensure Aspose.License.txt and aspose_words-*-win_amd64.whl are committed."
}

function Resolve-BuildPython {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
  )
  foreach ($path in $candidates) {
    if (Test-Path $path) { return $path }
  }
  foreach ($ver in @("3.11", "3.12", "3.13")) {
    try {
      $py = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
      if ($py -and (Test-Path $py)) { return $py.Trim() }
    } catch { }
  }
  $fallback = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
  if ($fallback -and $fallback -notmatch "msys|mingw|ucrt64") {
    return $fallback
  }
  throw "Windows Python 3.11+ not found. Install from python.org."
}

function Get-RuntimePython {
  param([string]$RuntimeRoot)
  $candidates = @(
    (Join-Path $RuntimeRoot "python.exe"),
    (Join-Path $RuntimeRoot "Scripts\python.exe"),
    (Join-Path $RuntimeRoot "bin\python.exe")
  )
  foreach ($path in $candidates) {
    if (Test-Path $path) { return $path }
  }
  throw "runtime python.exe missing under $RuntimeRoot"
}

function Get-VenvPython {
  param([string]$RuntimeRoot)
  return Get-RuntimePython -RuntimeRoot $RuntimeRoot
}

function Get-VenvTool {
  param([string]$RuntimeRoot, [string]$Name)
  $scripts = Join-Path $RuntimeRoot ("Scripts\" + $Name)
  if (Test-Path $scripts) { return $scripts }
  $bin = Join-Path $RuntimeRoot ("bin\" + $Name)
  if (Test-Path $bin) { return $bin }
  return $null
}

function Invoke-PipInstall {
  param(
    [string]$PipExe,
    [string]$PythonExe,
    [Parameter(Mandatory = $true)][string[]]$InstallArgs,
    [string]$Label = "pip install"
  )
  $mirrors = @(
    @{ Index = $null; TrustedHost = $null; Name = "PyPI (default)" },
    @{ Index = "https://pypi.tuna.tsinghua.edu.cn/simple"; TrustedHost = "pypi.tuna.tsinghua.edu.cn"; Name = "Tsinghua mirror" },
    @{ Index = "https://mirrors.aliyun.com/pypi/simple/"; TrustedHost = "mirrors.aliyun.com"; Name = "Aliyun mirror" }
  )
  $lastError = $null
  foreach ($mirror in $mirrors) {
    $pipArgs = @("install", "--default-timeout", "300")
    if ($mirror.Index) {
      $pipArgs += @("--index-url", $mirror.Index, "--trusted-host", $mirror.TrustedHost)
    }
    $pipArgs += $InstallArgs
    Write-Host "  $Label via $($mirror.Name)..."
    if ($PipExe) {
      & $PipExe @pipArgs
    } else {
      & $PythonExe -m pip @pipArgs
    }
    if ($LASTEXITCODE -eq 0) { return }
    $lastError = "exit code $LASTEXITCODE"
    Write-Host "  $Label failed on $($mirror.Name), trying next source..." -ForegroundColor Yellow
  }
  throw "$Label failed after retries ($lastError)"
}

function Stop-StageLockingProcesses {
  param([string]$StagePath)
  $needle = "tender-agent-installer-stage"
  foreach ($name in @("python.exe", "pip.exe", "uvicorn.exe", "TenderAgent.exe", "postgres.exe", "minio.exe")) {
    Get-CimInstance Win32_Process -Filter "Name='$name'" -ErrorAction SilentlyContinue | ForEach-Object {
      $cmd = $_.CommandLine
      $exe = $_.ExecutablePath
      if (($cmd -and $cmd -like "*$needle*") -or ($exe -and $exe -like "*$needle*")) {
        Write-Host "  stopping $($_.ProcessId): $name"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
      }
    }
  }
  Start-Sleep -Seconds 1
}

function Remove-DirectorySafe {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Stop-StageLockingProcesses $Path
  for ($i = 1; $i -le 6; $i++) {
    try {
      Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
      return
    } catch {
      Write-Host "  cleanup retry $i/6: $($_.Exception.Message)"
      Stop-StageLockingProcesses $Path
      Start-Sleep -Seconds 2
    }
  }
  $bakName = (Split-Path $Path -Leaf) + ".old-" + (Get-Date -Format "yyyyMMddHHmmss")
  Rename-Item -LiteralPath $Path -NewName $bakName -ErrorAction Stop
}

function Download-File {
  param([string]$Url, [string]$Destination)
  if (Test-Path -LiteralPath $Destination) {
    Write-Host "  already exists: $Destination"
    return
  }
  $parent = Split-Path -Parent $Destination
  if (-not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }
  Write-Host "  downloading $Url"
  Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

$BuildPython = Resolve-BuildPython
Write-Host "==> Using build Python: $BuildPython"

Write-Host "==> Building frontend"
Set-Location (Join-Path $Root "frontend")
if (-not (Test-Path "node_modules")) {
  npm install
}
npm run build
Set-Location $Root

Write-Host "==> Preparing staging directory"
Remove-DirectorySafe $Stage
New-Item -ItemType Directory -Path $Stage | Out-Null

Write-Host "==> Creating portable Python embed runtime"
$Runtime = Join-Path $Stage "runtime"
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$EmbedZipPath = Join-Path $env:TEMP $EmbedZipName
Download-File -Url $EmbedUrl -Destination $EmbedZipPath
Expand-Archive -Path $EmbedZipPath -DestinationPath $Runtime -Force

$SitePackages = Join-Path $Runtime "Lib\site-packages"
New-Item -ItemType Directory -Path $SitePackages -Force | Out-Null
$PthPath = Join-Path $Runtime "python311._pth"
Set-Content -Path $PthPath -Value @(
  "python311.zip",
  ".",
  "Lib\site-packages",
  "import site"
) -Encoding ASCII

$GetPipPath = Join-Path $env:TEMP "get-pip.py"
Download-File -Url $GetPipUrl -Destination $GetPipPath
$RuntimePython = Join-Path $Runtime "python.exe"
& $RuntimePython $GetPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed for embed runtime" }

Invoke-PipInstall -PythonExe $RuntimePython -Label "upgrade pip" -InstallArgs @("--upgrade", "pip", "-q")

$ReqFile = Join-Path $Root "backend\requirements.txt"
Invoke-PipInstall -PythonExe $RuntimePython -Label "install requirements" -InstallArgs @("--no-cache-dir", "-r", $ReqFile)

$AsposeAssets = Resolve-AsposeAssets -ProjectRoot $Root
$AsposeDir = $AsposeAssets.Dir
$AsposeWheel = $AsposeAssets.Wheel
Write-Host "  Aspose dir: $AsposeDir"
Write-Host "  Aspose wheel: $AsposeWheel"
if (-not (Test-Path -LiteralPath $AsposeWheel)) {
  throw "Aspose Windows wheel not found: $AsposeWheel"
}
Invoke-PipInstall -PythonExe $RuntimePython -Label "install aspose.words" -InstallArgs @("--no-cache-dir", $AsposeWheel)

Write-Host "==> Verifying portable Python runtime"
& $RuntimePython -c "import uvicorn, fastapi, sqlalchemy, psycopg2, minio, aspose.words; print('runtime self-test ok')"
if ($LASTEXITCODE -ne 0) { throw "Portable runtime self-test failed" }

Write-Host "==> Downloading PostgreSQL portable binaries"
$ToolsDir = Join-Path $Stage "tools"
$PgZipPath = Join-Path $env:TEMP $PgZipName
Download-File -Url $PgUrl -Destination $PgZipPath
$PgExtract = Join-Path $env:TEMP "pgsql-$PgVersion"
if (Test-Path $PgExtract) { Remove-Item -Recurse -Force $PgExtract }
Expand-Archive -Path $PgZipPath -DestinationPath $env:TEMP -Force
$PgSource = Join-Path $env:TEMP "pgsql"
if (-not (Test-Path $PgSource)) { throw "PostgreSQL extract missing pgsql folder" }
$PgDest = Join-Path $ToolsDir "postgres"
New-Item -ItemType Directory -Path $PgDest -Force | Out-Null
# Only ship server runtime (bin/lib/share). Skip pgAdmin 4 / StackBuilder / doc to avoid
# Windows MAX_PATH failures during Inno Setup compression.
foreach ($pgDir in @("bin", "lib", "share")) {
  $src = Join-Path $PgSource $pgDir
  if (-not (Test-Path -LiteralPath $src)) {
    throw "PostgreSQL extract missing required directory: $pgDir"
  }
  Copy-Item -LiteralPath $src -Destination (Join-Path $PgDest $pgDir) -Recurse -Force
}
Write-Host "  PostgreSQL runtime copied (bin/lib/share only)"
foreach ($required in @("bin\initdb.exe", "bin\pg_ctl.exe", "bin\psql.exe", "bin\postgres.exe")) {
  $path = Join-Path $PgDest $required
  if (-not (Test-Path -LiteralPath $path)) {
    throw "PostgreSQL runtime incomplete, missing $required"
  }
}

Write-Host "==> Downloading MinIO"
$MinioDest = Join-Path $ToolsDir "minio.exe"
Download-File -Url $MinioUrl -Destination $MinioDest

Write-Host "==> Copying Aspose license"
$AsposeDest = Join-Path $Stage "aspose"
New-Item -ItemType Directory -Path $AsposeDest -Force | Out-Null
Copy-Item -LiteralPath $AsposeAssets.License (Join-Path $AsposeDest "Aspose.License.txt") -Force

Write-Host "==> Copying backend"
$BackendDest = Join-Path $Stage "backend"
New-Item -ItemType Directory -Path $BackendDest | Out-Null
$ExcludeDirs = @("__pycache__", ".pytest_cache", ".venv", "venv", "tests")
Get-ChildItem (Join-Path $Root "backend") | ForEach-Object {
  if ($ExcludeDirs -contains $_.Name) { return }
  Copy-Item $_.FullName -Destination $BackendDest -Recurse -Force
}

Write-Host "==> Copying frontend/dist"
$FrontendDist = Join-Path $Stage "frontend\dist"
New-Item -ItemType Directory -Path $FrontendDist -Force | Out-Null
Copy-Item -Recurse (Join-Path $Root "frontend\dist\*") $FrontendDist -Force

Write-Host "==> Copying sample_data and customer_data"
Copy-Item -Recurse (Join-Path $Root "sample_data") (Join-Path $Stage "sample_data") -Force
if (Test-Path (Join-Path $Root "customer_data")) {
  Copy-Item -Recurse (Join-Path $Root "customer_data") (Join-Path $Stage "customer_data") -Force
}

Write-Host "==> Copying desktop Python scripts"
$DesktopDest = Join-Path $Stage "desktop"
New-Item -ItemType Directory -Path $DesktopDest -Force | Out-Null
Copy-Item (Join-Path $Root "desktop\backend_launcher.py") (Join-Path $DesktopDest "backend_launcher.py") -Force

Write-Host "==> Syncing brand icons"
$BrandIco = Join-Path $Root "assets\brand\icon.ico"
$BrandPng = Join-Path $Root "assets\brand\icon.png"
foreach ($required in @($BrandIco, $BrandPng)) {
  if (-not (Test-Path -LiteralPath $required)) {
    throw "Brand icon missing: $required"
  }
}
$ElectronBuildRes = Join-Path $ElectronDir "build"
New-Item -ItemType Directory -Force -Path $ElectronBuildRes | Out-Null
Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $ElectronBuildRes "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $ElectronBuildRes "icon.png") -Force
Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $ElectronDir "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $ElectronDir "icon.png") -Force

$IconTempDir = Join-Path $env:TEMP "tender-agent-build-icons"
New-Item -ItemType Directory -Force -Path $IconTempDir | Out-Null
$IconTempIco = Join-Path $IconTempDir "icon.ico"
Copy-Item -LiteralPath $BrandIco -Destination $IconTempIco -Force

Write-Host "==> Building Electron shell"
Remove-DirectorySafe $ElectronBuild
Set-Location $ElectronDir
if (-not (Test-Path "node_modules")) {
  npm install
}
npm run dist
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
Set-Location $Root

$ElectronUnpacked = Join-Path $ElectronBuild "win-unpacked"
$UnpackedExe = Join-Path $ElectronUnpacked "TenderAgent.exe"
if (-not (Test-Path -LiteralPath $UnpackedExe)) {
  throw "Electron build did not produce TenderAgent.exe"
}

Write-Host "==> Embedding brand icon into TenderAgent.exe"
$Rcedit = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "electron-builder\Cache\winCodeSign") -Recurse -Filter "rcedit-x64.exe" -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty FullName
if ($Rcedit) {
  $ExeTemp = Join-Path $IconTempDir "TenderAgent.exe"
  Copy-Item -LiteralPath $UnpackedExe -Destination $ExeTemp -Force
  & $Rcedit $ExeTemp --set-icon $IconTempIco
  if ($LASTEXITCODE -eq 0) {
    Copy-Item -LiteralPath $ExeTemp -Destination $UnpackedExe -Force
  }
}

Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $ElectronUnpacked "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $ElectronUnpacked "icon.png") -Force
$UnpackedResources = Join-Path $ElectronUnpacked "resources"
Copy-Item -LiteralPath $BrandIco -Destination (Join-Path $UnpackedResources "icon.ico") -Force
Copy-Item -LiteralPath $BrandPng -Destination (Join-Path $UnpackedResources "icon.png") -Force

Write-Host "==> Merging Electron output into staging"
Get-ChildItem -LiteralPath $ElectronUnpacked | ForEach-Object {
  $dest = Join-Path $Stage $_.Name
  if (Test-Path -LiteralPath $dest) {
    Remove-Item -LiteralPath $dest -Recurse -Force
  }
  Copy-Item -LiteralPath $_.FullName -Destination $Stage -Recurse -Force
}

foreach ($name in @("runtime", "backend", "frontend", "sample_data", "customer_data", "aspose", "desktop", "tools")) {
  $dup = Join-Path $Stage $name
  if (Test-Path -LiteralPath $dup) {
    Remove-Item -LiteralPath $dup -Recurse -Force
  }
}

if (-not (Test-Path (Join-Path $Stage "TenderAgent.exe"))) {
  throw "TenderAgent.exe missing after Electron merge"
}
if (-not (Test-Path (Join-Path $Stage "resources\tender-agent\runtime\python.exe"))) {
  throw "resources/tender-agent runtime missing"
}

Write-Host ""
Write-Host "Staging complete: $Stage"
