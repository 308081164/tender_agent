# Copy Aspose assets to an ASCII-only path for Windows CI/build scripts.
# Avoids PowerShell encoding issues with Chinese directory names under docs/.

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Target = Join-Path $Root "vendor\aspose-words"

function Find-AsposeSource {
  param([string]$ProjectRoot)

  $docsRoot = Join-Path $ProjectRoot "docs"
  if (-not (Test-Path -LiteralPath $docsRoot)) {
    throw "docs/ directory not found"
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

  throw "Aspose license + Windows wheel not found under docs/"
}

Write-Host "Preparing Aspose assets at $Target"
$source = Find-AsposeSource -ProjectRoot $Root
New-Item -ItemType Directory -Path $Target -Force | Out-Null

$wheelName = Split-Path $source.Wheel -Leaf
Copy-Item -LiteralPath $source.License (Join-Path $Target "Aspose.License.txt") -Force
Copy-Item -LiteralPath $source.Wheel (Join-Path $Target $wheelName) -Force

Write-Host "Copied:"
Write-Host "  License: $($source.License)"
Write-Host "  Wheel:   $($source.Wheel)"
