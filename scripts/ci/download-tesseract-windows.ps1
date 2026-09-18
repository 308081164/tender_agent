# 下载并解压 Windows 便携版 Tesseract OCR（供桌面安装包捆绑，含 chi_sim）
param(
  [Parameter(Mandatory = $true)]
  [string]$DestinationDir
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

$SetupUrl = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
$SetupPath = Join-Path $env:TEMP "tesseract-setup.exe"
$TessdataBestBase = "https://github.com/tesseract-ocr/tessdata_best/raw/main"

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

function Ensure-TessLangFile {
  param(
    [string]$TessdataDir,
    [string]$Lang
  )
  $dest = Join-Path $TessdataDir "$Lang.traineddata"
  if (Test-Path -LiteralPath $dest) {
    Write-Host "  tessdata already has $Lang"
    return
  }
  $url = "$TessdataBestBase/$Lang.traineddata"
  Write-Host "  downloading $Lang.traineddata"
  Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
  if (-not (Test-Path -LiteralPath $dest)) {
    throw "Failed to download $Lang.traineddata"
  }
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

$exe = Get-ChildItem -Path $ExtractRoot -Recurse -Filter "tesseract.exe" -File | Select-Object -First 1
if (-not $exe) { throw "tesseract.exe not found after extract" }

$srcDir = $exe.DirectoryName
if (Test-Path $DestinationDir) { Remove-Item -Recurse -Force $DestinationDir }
New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
Copy-Item -Path (Join-Path $srcDir "*") -Destination $DestinationDir -Recurse -Force

$tessdataDir = Join-Path $DestinationDir "tessdata"
if (-not (Test-Path -LiteralPath $tessdataDir)) {
  New-Item -ItemType Directory -Force -Path $tessdataDir | Out-Null
}

Ensure-TessLangFile -TessdataDir $tessdataDir -Lang "eng"
Ensure-TessLangFile -TessdataDir $tessdataDir -Lang "chi_sim"

if (-not (Test-Path (Join-Path $DestinationDir "tesseract.exe"))) {
  throw "Bundle incomplete: tesseract.exe missing in $DestinationDir"
}
if (-not (Test-Path (Join-Path $tessdataDir "chi_sim.traineddata"))) {
  throw "Bundle incomplete: chi_sim.traineddata missing"
}
Write-Host "Tesseract bundled to $DestinationDir (eng + chi_sim)"
