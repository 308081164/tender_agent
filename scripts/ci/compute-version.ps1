# Compute installer version for CI builds.
# Outputs: version, artifact_suffix, is_release

param(
  [ValidateSet("desktop")]
  [string]$Product = "desktop"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$IssFile = Join-Path $Root "installer\tender_agent.iss"

if (-not (Test-Path -LiteralPath $IssFile)) {
  throw "Installer script not found: $IssFile"
}

$issContent = Get-Content -LiteralPath $IssFile -Raw
if ($issContent -notmatch '#define\s+MyAppVersion\s+"([^"]+)"') {
  throw "Could not read MyAppVersion from $IssFile"
}
$baseVersion = $Matches[1]

$ref = $env:GITHUB_REF
$runNumber = if ($env:GITHUB_RUN_NUMBER) { $env:GITHUB_RUN_NUMBER } else { "0" }
$shortSha = if ($env:GITHUB_SHA -and $env:GITHUB_SHA.Length -ge 7) {
  $env:GITHUB_SHA.Substring(0, 7)
} else {
  "local"
}

$version = $null
$isRelease = "false"

if ($ref -match '^refs/tags/desktop-v(.+)$') {
  $version = $Matches[1]
  $isRelease = "true"
} else {
  $version = "$baseVersion-dev.$runNumber"
}

$artifactSuffix = "$version-$shortSha"

Write-Host "Product: $Product"
Write-Host "Version: $version"
Write-Host "Artifact suffix: $artifactSuffix"
Write-Host "Release build: $isRelease"

if ($env:GITHUB_OUTPUT) {
  "version=$version" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
  "artifact_suffix=$artifactSuffix" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
  "is_release=$isRelease" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
}

Write-Output $version
