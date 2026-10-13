# 下载 Windows 版 ONLYOFFICE Docs Community，并整理成桌面安装包可启动的 sidecar。
# 不把二进制提交进 git。构建机需要 7-Zip 与约 3 GB 临时磁盘。
param(
  [Parameter(Mandatory = $true)]
  [string]$DestinationDir
)

$ErrorActionPreference = "Stop"

# 官方 Windows 安装包没有版本化 URL，这里跟踪当前 Community 安装程序。
# docker-compose 里的 Linux 镜像仍固定为 8.2.2；两者不是同一个文件。
$DocumentServerUrl = "https://download.onlyoffice.com/install/documentserver/windows/onlyoffice-documentserver.exe"
$ErlangUrl = "https://github.com/erlang/otp/releases/download/OTP-26.2.5/otp_win64_26.2.5.zip"
$RabbitUrl = "https://github.com/rabbitmq/rabbitmq-server/releases/download/v3.13.7/rabbitmq-server-windows-3.13.7.zip"
$ErlangVersion = "26.2.5"
$RabbitVersion = "3.13.7"

function Get-7Zip {
  $candidates = @(
    (Join-Path ${env:ProgramFiles} "7-Zip\7z.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "7-Zip\7z.exe")
  )
  foreach ($path in $candidates) {
    if (Test-Path -LiteralPath $path) { return $path }
  }
  $cmd = Get-Command 7z -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Download-File([string]$Url, [string]$Destination) {
  if ((Test-Path -LiteralPath $Destination) -and ((Get-Item -LiteralPath $Destination).Length -gt 1MB)) {
    Write-Host "  already exists: $Destination"
    return
  }
  $parent = Split-Path -Parent $Destination
  if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }
  Write-Host "  downloading $Url"
  $headers = @{ "User-Agent" = "TenderAgent-Desktop-Build/1.0" }
  Invoke-WebRequest -Uri $Url -OutFile $Destination -Headers $headers -UseBasicParsing
}

function Find-First([string]$Root, [string]$Filter, [string]$PathLike) {
  Get-ChildItem -Path $Root -Recurse -Filter $Filter -File -ErrorAction SilentlyContinue |
    Where-Object { -not $PathLike -or $_.FullName -like $PathLike } |
    Select-Object -First 1
}

function Copy-Tree([string]$Source, [string]$Dest) {
  if (Test-Path -LiteralPath $Dest) {
    Remove-Item -LiteralPath $Dest -Recurse -Force
  }
  New-Item -ItemType Directory -Path (Split-Path -Parent $Dest) -Force | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Dest -Recurse -Force
}

function Relative-To([string]$Root, [string]$Path) {
  $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
  $pathFull = [System.IO.Path]::GetFullPath($Path)
  if (-not $pathFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Path is outside bundle root: $Path"
  }
  return $pathFull.Substring($rootFull.Length).TrimStart('\').Replace('\', '/')
}

$seven = Get-7Zip
if (-not $seven) {
  throw "7-Zip is required to extract the OnlyOffice installer. Install it from https://www.7-zip.org/"
}

New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
$work = Join-Path $env:TEMP "tender-onlyoffice-bundle"
New-Item -ItemType Directory -Force -Path $work | Out-Null

$exePath = Join-Path $work "onlyoffice-documentserver.exe"
Download-File -Url $DocumentServerUrl -Destination $exePath
$hash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
Write-Host "  documentserver sha256: $hash"

$extract = Join-Path $work "documentserver-extract"
if (Test-Path -LiteralPath $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extract | Out-Null
Write-Host "  extracting Document Server installer"
& $seven x $exePath "-o$extract" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw "7z could not extract onlyoffice-documentserver.exe" }

$nginx = Find-First $extract "nginx.exe" "*nginx*"
if (-not $nginx) { $nginx = Find-First $extract "nginx.exe" $null }
$docJs = Find-First $extract "server.js" "*DocService*"
$converterJs = Find-First $extract "convertermaster.js" "*FileConverter*"
$schema = Find-First $extract "createdb.sql" "*postgresql*"
$defaultJson = Get-ChildItem -Path $extract -Recurse -Filter "default.json" -File -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch "node_modules" } |
  Select-Object -First 1
$node = Find-First $extract "node.exe" $null

if (-not $nginx -or -not $docJs -or -not $converterJs -or -not $schema -or -not $defaultJson -or -not $node) {
  Write-Host "Extracted tree (first 40 files):"
  Get-ChildItem -Path $extract -Recurse -File -ErrorAction SilentlyContinue |
    Select-Object -First 40 -ExpandProperty FullName
  throw "OnlyOffice installer layout is missing nginx, DocService, FileConverter, schema, config, or node.exe. Refusing to ship an incomplete editor."
}

# Install root is the directory that contains both nginx\ and server\ (or the nginx parent's parent).
$docRoot = $nginx.Directory.Parent.FullName
$serverMarker = Join-Path $docRoot "server"
if (-not (Test-Path -LiteralPath $serverMarker)) {
  $docRoot = $docJs.Directory.Parent.Parent.Parent.FullName
}
$docDest = Join-Path $DestinationDir "documentserver"
Write-Host "  copying Document Server from $docRoot"
Copy-Tree -Source $docRoot -Dest $docDest
if (-not (Find-First $docDest "node.exe" $null)) {
  Copy-Item -LiteralPath $node.FullName -Destination (Join-Path $docDest "node.exe") -Force
  Write-Host "  copied node.exe from outside the Document Server root"
}
if (-not (Find-First $docDest "default.json" $null) -and $defaultJson) {
  $configDest = Join-Path $docDest "config"
  New-Item -ItemType Directory -Force -Path $configDest | Out-Null
  Copy-Item -LiteralPath (Join-Path $defaultJson.Directory.FullName "*") -Destination $configDest -Recurse -Force
  Write-Host "  copied config directory from outside the Document Server root"
}
if (-not (Find-First $docDest "createdb.sql" $null)) {
  $schemaDest = Join-Path $docDest "server\schema\postgresql"
  New-Item -ItemType Directory -Force -Path $schemaDest | Out-Null
  Copy-Item -LiteralPath $schema.FullName -Destination (Join-Path $schemaDest "createdb.sql") -Force
  Write-Host "  copied createdb.sql from outside the Document Server root"
}

$erlangZip = Join-Path $work "otp_win64_$ErlangVersion.zip"
Download-File -Url $ErlangUrl -Destination $erlangZip
$erlangExtract = Join-Path $work "erlang-extract"
if (Test-Path -LiteralPath $erlangExtract) { Remove-Item -LiteralPath $erlangExtract -Recurse -Force }
Expand-Archive -Path $erlangZip -DestinationPath $erlangExtract -Force
$erl = Find-First $erlangExtract "erl.exe" $null
if (-not $erl) { throw "Erlang zip did not contain erl.exe" }
$erlangHomeSrc = $erl.Directory.Parent.FullName
$erlangDest = Join-Path $DestinationDir "erlang"
Write-Host "  copying Erlang from $erlangHomeSrc"
Copy-Tree -Source $erlangHomeSrc -Dest $erlangDest

$rabbitZip = Join-Path $work "rabbitmq-server-windows-$RabbitVersion.zip"
Download-File -Url $RabbitUrl -Destination $rabbitZip
$rabbitExtract = Join-Path $work "rabbit-extract"
if (Test-Path -LiteralPath $rabbitExtract) { Remove-Item -LiteralPath $rabbitExtract -Recurse -Force }
Expand-Archive -Path $rabbitZip -DestinationPath $rabbitExtract -Force
$rabbitBat = Find-First $rabbitExtract "rabbitmq-server.bat" $null
if (-not $rabbitBat) { throw "RabbitMQ zip did not contain rabbitmq-server.bat" }
$rabbitSrc = $rabbitBat.Directory.Parent.FullName
$rabbitDest = Join-Path $DestinationDir "rabbitmq"
Write-Host "  copying RabbitMQ from $rabbitSrc"
Copy-Tree -Source $rabbitSrc -Dest $rabbitDest

function Find-InDest([string]$Filter, [string]$PathLike) {
  Find-First $DestinationDir $Filter $PathLike
}

$nginxOut = Find-InDest "nginx.exe" "*nginx*"
$docOut = Find-InDest "server.js" "*DocService*"
$converterOut = Find-InDest "convertermaster.js" "*FileConverter*"
$schemaOut = Find-InDest "createdb.sql" "*postgresql*"
$nodeOut = Find-InDest "node.exe" $null
$defaultOut = Get-ChildItem -Path $DestinationDir -Recurse -Filter "default.json" -File |
  Where-Object { $_.FullName -notmatch "node_modules" } |
  Select-Object -First 1
$rabbitOut = Find-InDest "rabbitmq-server.bat" $null
$erlOut = Find-InDest "erl.exe" $null
if (-not ($nginxOut -and $docOut -and $converterOut -and $schemaOut -and $nodeOut -and $defaultOut -and $rabbitOut -and $erlOut)) {
  throw "OnlyOffice bundle copy is incomplete"
}

$manifest = [ordered]@{
  tracked_docker_version = "8.2.2"
  documentserver_url = $DocumentServerUrl
  documentserver_sha256 = $hash
  erlang_version = $ErlangVersion
  rabbitmq_version = $RabbitVersion
  license = "AGPL-3.0 (ONLYOFFICE Docs Community). Commercial embedding requires an OnlyOffice Developer license."
  nginx = (Relative-To $DestinationDir $nginxOut.FullName)
  docservice = (Relative-To $DestinationDir $docOut.FullName)
  converter = (Relative-To $DestinationDir $converterOut.FullName)
  node = (Relative-To $DestinationDir $nodeOut.FullName)
  schema = (Relative-To $DestinationDir $schemaOut.FullName)
  config_dir = (Relative-To $DestinationDir $defaultOut.Directory.FullName)
  rabbitmq = (Relative-To $DestinationDir $rabbitOut.FullName)
  erlang_home = (Relative-To $DestinationDir $erlOut.Directory.Parent.FullName)
}
$manifestPath = Join-Path $DestinationDir "bundle.json"
$manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$notice = @"
ONLYOFFICE Docs Community Edition is licensed under AGPL-3.0.
This desktop build vendors the official Windows installer plus Erlang/OTP $ErlangVersion and RabbitMQ $RabbitVersion so Word editing works offline after install.
Redistributing that combination inside a closed-source product requires an OnlyOffice commercial Developer license before a public release.
Document Server installer SHA256: $hash
"@
Set-Content -LiteralPath (Join-Path $DestinationDir "LICENSE-REDISTRIBUTION.txt") -Value $notice -Encoding UTF8
Write-Host "OnlyOffice bundle ready: $DestinationDir"
