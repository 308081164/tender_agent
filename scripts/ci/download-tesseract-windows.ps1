# 下载并解压 Windows 便携版 Tesseract OCR（供桌面安装包捆绑）
param(
  [Parameter(Mandatory = $true)]
  [string]$DestinationDir
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

# UB Mannheim 官方 Windows 构建（安装包，用 7z 解压为便携目录）
$SetupUrl = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
$SetupPath = Join-Path $env:TEMP "tesseract-setup.exe"

function Get-7Zip {
  $candidates = @(
    (Join-Path ${env:ProgramFiles} "7-Zip\7z.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "7-Zip\7z.exe")
  )
  foreach ($p in $candidates) {
    if (Test-Path $p) { return $p }
  }
  $cmd = Get-Command 7z -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

Write-Host "Downloading Tesseract from $SetupUrl"
Invoke-WebRequest -Uri $SetupUrl -OutFile $SetupPath -UseBasicParsing

$seven = Get-7Zip
if (-not $seven) {
  throw "7-Zip required to extract Tesseract installer. Install from https://www.7-zip.org/"
}

$ExtractRoot = Join-Path $env:TEMP "tesseract-extract"
if (Test-Path $ExtractRoot) { Remove-Item -Recurse -Force $ExtractRoot }
New-Item -ItemType Directory -Force -Path $ExtractRoot | Out-Null

& $seven x $SetupPath "-o$ExtractRoot" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw "7z extract failed" }

# 安装包解压后通常在 $ExtractRoot 下含 tesseract.exe 与 tessdata
$exe = Get-ChildItem -Path $ExtractRoot -Recurse -Filter "tesseract.exe" -File | Select-Object -First 1
if (-not $exe) { throw "tesseract.exe not found after extract" }

$srcDir = $exe.DirectoryName
if (Test-Path $DestinationDir) { Remove-Item -Recurse -Force $DestinationDir }
New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
Copy-Item -Path (Join-Path $srcDir "*") -Destination $DestinationDir -Recurse -Force

$tessdataSrc = Join-Path $srcDir "tessdata"
if (Test-Path $tessdataSrc) {
  Copy-Item -Path $tessdataSrc -Destination (Join-Path $DestinationDir "tessdata") -Recurse -Force
}

if (-not (Test-Path (Join-Path $DestinationDir "tesseract.exe"))) {
  throw "Bundle incomplete: tesseract.exe missing in $DestinationDir"
}
Write-Host "Tesseract bundled to $DestinationDir"
