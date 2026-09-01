param(
  [Parameter(Mandatory = $true)]
  [string]$InstallerPath,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [int]$Port = 18766,
  [int]$TimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
$InstallDir = Join-Path $env:RUNNER_TEMP "TenderAgentInstalled"
# PostgreSQL initdb must be tested on the same user-owned NTFS location used in
# production. GitHub Runner's D:\a\_temp has inherited ACLs that deny initdb's
# permission normalization and is not representative of a normal installation.
$DataDir = Join-Path $env:LOCALAPPDATA "TenderAgent\data"
$ArtifactDir = Join-Path $env:RUNNER_TEMP "TenderAgentSmoke\artifacts"
$AppExe = Join-Path $InstallDir "TenderAgent.exe"
$HealthUrl = "http://127.0.0.1:$Port/api/health"
$RootUrl = "http://127.0.0.1:$Port/"
$AppProcess = $null

function Write-SmokeLog([string]$Message) {
  Write-Host "[$(Get-Date -Format 'HH:mm:ss')] [desktop-smoke] $Message"
}

function Copy-Diagnostics {
  New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
  foreach ($name in @(
    "electron.log",
    "launcher.log",
    "postgres.log",
    "minio.log",
    "backend.log",
    "server.json",
    "postgres.json",
    "minio.json"
  )) {
    $source = Join-Path $DataDir $name
    if (Test-Path -LiteralPath $source) {
      Copy-Item -LiteralPath $source -Destination $ArtifactDir -Force
    }
  }
  $versionPath = Join-Path $InstallDir "resources\tender-agent\version.json"
  if (Test-Path -LiteralPath $versionPath) {
    Copy-Item -LiteralPath $versionPath -Destination $ArtifactDir -Force
  }
}

function Show-Diagnostics {
  foreach ($name in @(
    "electron.log",
    "launcher.log",
    "postgres.log",
    "minio.log",
    "backend.log"
  )) {
    $path = Join-Path $DataDir $name
    if (Test-Path -LiteralPath $path) {
      Write-Host ""
      Write-Host "===== $name ====="
      Get-Content -LiteralPath $path -Encoding UTF8
    }
  }
}

function Stop-ExactProcess([int]$ProcessId) {
  if ($ProcessId -le 0) { return }
  $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($proc) {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    try { Wait-Process -Id $ProcessId -Timeout 10 -ErrorAction SilentlyContinue } catch {}
  }
}

function Stop-StateProcess([string]$StateFile) {
  if (-not (Test-Path -LiteralPath $StateFile)) { return }
  try {
    $state = Get-Content -Raw -LiteralPath $StateFile | ConvertFrom-Json
    if ($state.pid) { Stop-ExactProcess -ProcessId ([int]$state.pid) }
  } catch {
    Write-SmokeLog "Could not stop process from $StateFile`: $($_.Exception.Message)"
  }
}

try {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $InstallDir
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Split-Path -Parent $DataDir)
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Split-Path -Parent $ArtifactDir)
  New-Item -ItemType Directory -Force -Path $DataDir, $ArtifactDir | Out-Null

  Write-SmokeLog "Installing $InstallerPath into $InstallDir"
  $installerLog = Join-Path $ArtifactDir "installer.log"
  $installArgs = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/SP-",
    "/DIR=$InstallDir",
    "/LOG=$installerLog"
  )
  $installer = Start-Process -FilePath $InstallerPath -ArgumentList $installArgs -Wait -PassThru
  if ($installer.ExitCode -ne 0) {
    throw "Installer exited with code $($installer.ExitCode)"
  }
  if (-not (Test-Path -LiteralPath $AppExe)) {
    Write-SmokeLog "Installed files found under requested directory:"
    Get-ChildItem -LiteralPath $InstallDir -Recurse -ErrorAction SilentlyContinue |
      Select-Object -First 50 -ExpandProperty FullName
    throw "Installed application not found: $AppExe"
  }

  $versionPath = Join-Path $InstallDir "resources\tender-agent\version.json"
  if (-not (Test-Path -LiteralPath $versionPath)) {
    throw "Installed version manifest not found: $versionPath"
  }
  $manifest = Get-Content -Raw -LiteralPath $versionPath | ConvertFrom-Json
  if ($manifest.version -ne $ExpectedVersion) {
    throw "Installed version mismatch: expected $ExpectedVersion, got $($manifest.version)"
  }
  Write-SmokeLog "Installed version $($manifest.version), commit $($manifest.commit)"

  $env:TENDER_DATA_DIR = $DataDir
  $env:ELECTRON_ENABLE_LOGGING = "1"
  Write-SmokeLog "Launching installed application: $AppExe"
  $AppProcess = Start-Process -FilePath $AppExe -PassThru

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $lastPhase = ""
  while ((Get-Date) -lt $deadline) {
    $AppProcess.Refresh()
    if ($AppProcess.HasExited) {
      throw "TenderAgent.exe exited before becoming healthy (code $($AppProcess.ExitCode))"
    }

    $electronLog = Join-Path $DataDir "electron.log"
    if (Test-Path -LiteralPath $electronLog) {
      $electronText = Get-Content -Raw -LiteralPath $electronLog -Encoding UTF8
      if ($electronText -match "backend exited code=") {
        throw "Backend process exited before becoming healthy"
      }
    }

    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 3
      if ($response.StatusCode -eq 200) {
        Write-SmokeLog "Health check passed: $($response.Content)"
        break
      }
    } catch {}

    $launcherLog = Join-Path $DataDir "launcher.log"
    if (Test-Path -LiteralPath $launcherLog) {
      $phase = Get-Content -LiteralPath $launcherLog -Encoding UTF8 |
        Select-Object -Last 1
      if ($phase -and $phase -ne $lastPhase) {
        Write-SmokeLog "Launcher: $phase"
        $lastPhase = $phase
      }
    }
    Start-Sleep -Seconds 2
  }

  $health = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 5
  if ($health.StatusCode -ne 200) {
    throw "Health endpoint returned HTTP $($health.StatusCode)"
  }
  $root = Invoke-WebRequest -UseBasicParsing -Uri $RootUrl -TimeoutSec 10
  if ($root.StatusCode -ne 200 -or $root.Content -notmatch "<!doctype html|<html") {
    throw "Desktop root page is not valid HTML"
  }

  $serverState = Join-Path $DataDir "server.json"
  if (-not (Test-Path -LiteralPath $serverState)) {
    throw "Backend state file was not created: $serverState"
  }
  $state = Get-Content -Raw -LiteralPath $serverState | ConvertFrom-Json
  if (-not $state.pid -or -not (Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue)) {
    throw "Backend process recorded in server.json is not running"
  }

  Copy-Diagnostics
  Write-SmokeLog "PASS: installed desktop application is healthy and serving its UI"
} catch {
  Write-SmokeLog "FAIL: $($_.Exception.Message)"
  Show-Diagnostics
  Copy-Diagnostics
  throw
} finally {
  if ($AppProcess) { Stop-ExactProcess -ProcessId $AppProcess.Id }
  Stop-StateProcess -StateFile (Join-Path $DataDir "server.json")
  Stop-StateProcess -StateFile (Join-Path $DataDir "launcher.pid")
  Stop-StateProcess -StateFile (Join-Path $DataDir "minio.json")
  $postmasterPid = Join-Path $DataDir "pgdata\postmaster.pid"
  if (Test-Path -LiteralPath $postmasterPid) {
    $pidLine = Get-Content -LiteralPath $postmasterPid -TotalCount 1
    if ($pidLine -match "^\d+$") { Stop-ExactProcess -ProcessId ([int]$pidLine) }
  }
}
