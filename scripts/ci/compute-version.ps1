# Compute installer version for CI builds.
# Outputs: version, artifact_suffix, is_release, display_version
#
# Version scheme:
#   main push  -> 1.0.<run_number>           e.g. 1.0.11
#   pull_request -> 1.0.<run_number>-pr.<n>  e.g. 1.0.11-pr7
#   tag desktop-v* -> tag version (release)

param(
  [ValidateSet("desktop")]
  [string]$Product = "desktop"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VersionFile = Join-Path $Root "VERSION"

if (Test-Path -LiteralPath $VersionFile) {
  $baseVersion = (Get-Content -LiteralPath $VersionFile -Raw).Trim()
} else {
  $baseVersion = "1.0"
}

$ref = $env:GITHUB_REF
$eventName = $env:GITHUB_EVENT_NAME
$runNumber = if ($env:GITHUB_RUN_NUMBER) { [int]$env:GITHUB_RUN_NUMBER } else { 0 }
$prNumber = if ($env:GITHUB_PR_NUMBER) { $env:GITHUB_PR_NUMBER.Trim() } else { "" }
$shortSha = if ($env:GITHUB_SHA -and $env:GITHUB_SHA.Length -ge 7) {
  $env:GITHUB_SHA.Substring(0, 7)
} else {
  "local"
}

$version = $null
$displayVersion = $null
$isRelease = "false"

if ($ref -match '^refs/tags/desktop-v(.+)$') {
  $version = $Matches[1]
  $displayVersion = $version
  $isRelease = "true"
} elseif ($eventName -eq "pull_request" -and $prNumber) {
  $version = "$baseVersion.$runNumber-pr$prNumber"
  $displayVersion = "$baseVersion.$runNumber (PR #$prNumber)"
} elseif ($runNumber -gt 0) {
  $version = "$baseVersion.$runNumber"
  $displayVersion = $version
} else {
  $version = "$baseVersion.0-local"
  $displayVersion = $version
}

$artifactSuffix = "$version-$shortSha"

Write-Host "Product: $Product"
Write-Host "Version: $version"
Write-Host "Display version: $displayVersion"
Write-Host "Artifact suffix: $artifactSuffix"
Write-Host "Release build: $isRelease"

if ($env:GITHUB_OUTPUT) {
  "version=$version" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
  "display_version=$displayVersion" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
  "artifact_suffix=$artifactSuffix" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
  "is_release=$isRelease" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
  "build_number=$runNumber" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
}

Write-Output $version
