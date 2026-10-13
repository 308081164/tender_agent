# 下载 Windows 版 ONLYOFFICE Docs Community，并整理成桌面安装包可启动的 sidecar。
# 不把二进制提交进 git。安装包是 Inno Setup 6.7，脚本会下载 innounp 来解包，并需要约 3 GB 临时磁盘。
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
# innounp 2.71.1（commit 6fb49264）支持 Inno Setup 2.0.7–7.1.0。当前 Community 安装包是 6.7.0。
$InnounpUrl = "https://raw.githubusercontent.com/jrathlev/InnoUnpacker-Windows-GUI/6fb49264aacf512a093e7b4fc6fb3dd266dad31a/innounp-2/bin/innounp-2.zip"
$InnounpSha256 = "F2F037FDBC63DE31248EFAE9CCB294398D160DC0CBAD5F36D14C2F159E17BBF5"

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

function Remove-RuntimeUnused([string]$Root, [string[]]$DirNames) {
  if (-not (Test-Path -LiteralPath $Root)) { return }
  $dirs = @(Get-ChildItem -LiteralPath $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $DirNames -contains $_.Name })
  foreach ($dir in $dirs) {
    if (Test-Path -LiteralPath $dir.FullName) {
      Remove-Item -LiteralPath $dir.FullName -Recurse -Force
    }
  }
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

function Ensure-Innounp([string]$WorkDir) {
  $zip = Join-Path $WorkDir "innounp-2.zip"
  Download-File -Url $InnounpUrl -Destination $zip
  $got = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
  if ($got -ne $InnounpSha256) {
    throw "innounp-2.zip sha256 mismatch: $got"
  }
  $dest = Join-Path $WorkDir "innounp"
  if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
  Expand-Archive -Path $zip -DestinationPath $dest -Force
  $exe = Join-Path $dest "innounp.exe"
  if (-not (Test-Path -LiteralPath $exe)) { throw "innounp.exe missing after extract" }
  return $exe
}

function Find-DocRoot([System.IO.FileInfo]$NginxExe) {
  $dir = $NginxExe.Directory
  while ($null -ne $dir) {
    $hasServer = Test-Path -LiteralPath (Join-Path $dir.FullName "server")
    $hasNginx = Test-Path -LiteralPath (Join-Path $dir.FullName "nginx")
    if ($hasServer -and $hasNginx) { return $dir.FullName }
    $dir = $dir.Parent
  }
  return $NginxExe.Directory.Parent.FullName
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
$innounp = Ensure-Innounp $work
Write-Host "  extracting Document Server installer with innounp"
$innounpLog = Join-Path $work "innounp.log"
$prevNative = $PSNativeCommandUseErrorActionPreference
$PSNativeCommandUseErrorActionPreference = $false
try {
  # -d must be glued to the directory. cmd keeps $LASTEXITCODE equal to innounp's exit code.
  & cmd.exe /c "`"$innounp`" -x -b -y -q -d`"$extract`" `"$exePath`" > `"$innounpLog`" 2>&1"
  $innounpExit = $LASTEXITCODE
} finally {
  if ($null -ne $prevNative) { $PSNativeCommandUseErrorActionPreference = $prevNative }
}
if ($innounpExit -ne 0) {
  if (Test-Path -LiteralPath $innounpLog) {
    Get-Content -LiteralPath $innounpLog -Tail 50 | ForEach-Object { Write-Host $_ }
  }
  throw "innounp could not extract onlyoffice-documentserver.exe (exit $innounpExit)"
}

function Select-DefaultJson([string]$Root) {
  $candidates = @(Get-ChildItem -Path $Root -Recurse -Filter "default.json" -File -ErrorAction SilentlyContinue)
  $preferred = $candidates | Where-Object {
    $_.Directory.Name -eq "config" -and $_.FullName -notmatch "[\\/]example[\\/]" -and $_.FullName -notmatch "node_modules"
  } | Select-Object -First 1
  if ($preferred) { return $preferred }
  return $candidates | Where-Object { $_.FullName -notmatch "node_modules" } | Select-Object -First 1
}

function Find-ServiceEntry([string]$Root, [string]$NativeName, [string]$ScriptName, [string]$PathLike) {
  $native = Find-First $Root $NativeName $PathLike
  if ($native) { return $native }
  return Find-First $Root $ScriptName $PathLike
}

$nginx = Find-First $extract "nginx.exe" "*nginx*"
if (-not $nginx) { $nginx = Find-First $extract "nginx.exe" $null }
# Current Community builds ship docservice.exe / converter.exe. Older builds used node scripts.
$docEntry = Find-ServiceEntry $extract "docservice.exe" "server.js" "*DocService*"
$converterEntry = Find-ServiceEntry $extract "converter.exe" "convertermaster.js" "*FileConverter*"
$schema = Find-First $extract "createdb.sql" "*postgresql*"
$defaultJson = Select-DefaultJson $extract
$needsNode = ($docEntry -and $docEntry.Extension -eq ".js") -or ($converterEntry -and $converterEntry.Extension -eq ".js")
$node = $null
if ($needsNode) { $node = Find-First $extract "node.exe" $null }

if (-not $nginx -or -not $docEntry -or -not $converterEntry -or -not $schema -or -not $defaultJson -or ($needsNode -and -not $node)) {
  $missing = @()
  if (-not $nginx) { $missing += "nginx.exe" }
  if (-not $docEntry) { $missing += "docservice.exe|server.js" }
  if (-not $converterEntry) { $missing += "converter.exe|convertermaster.js" }
  if (-not $schema) { $missing += "postgresql/createdb.sql" }
  if (-not $defaultJson) { $missing += "config/default.json" }
  if ($needsNode -and -not $node) { $missing += "node.exe" }
  Write-Host ("Missing: " + ($missing -join ", "))
  Write-Host "Extracted tree (first 40 files):"
  Get-ChildItem -Path $extract -Recurse -File -ErrorAction SilentlyContinue |
    Select-Object -First 40 -ExpandProperty FullName
  throw "OnlyOffice installer layout is incomplete ($($missing -join ', ')). Refusing to ship an incomplete editor."
}

# Install root is the directory that contains both nginx\ and server\.
$docRoot = Find-DocRoot $nginx
$serverMarker = Join-Path $docRoot "server"
if (-not (Test-Path -LiteralPath $serverMarker)) {
  $docRoot = $docEntry.Directory.FullName
  while ($docRoot -and -not ((Test-Path -LiteralPath (Join-Path $docRoot "nginx")) -and (Test-Path -LiteralPath (Join-Path $docRoot "server")))) {
    $parent = Split-Path -Parent $docRoot
    if (-not $parent -or $parent -eq $docRoot) { break }
    $docRoot = $parent
  }
}
$docDest = Join-Path $DestinationDir "documentserver"
Write-Host "  copying Document Server from $docRoot"
Copy-Tree -Source $docRoot -Dest $docDest
if ($needsNode -and -not (Find-First $docDest "node.exe" $null)) {
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
Remove-RuntimeUnused $erlangDest @("doc", "src", "java_src", "examples", "man")

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
$docOut = Find-ServiceEntry $DestinationDir "docservice.exe" "server.js" "*DocService*"
$converterOut = Find-ServiceEntry $DestinationDir "converter.exe" "convertermaster.js" "*FileConverter*"
$schemaOut = Find-InDest "createdb.sql" "*postgresql*"
$nodeOut = $null
if ($needsNode) { $nodeOut = Find-InDest "node.exe" $null }
$defaultOut = Select-DefaultJson $DestinationDir
$rabbitOut = Find-InDest "rabbitmq-server.bat" $null
$erlOut = Find-InDest "erl.exe" $null
if (-not ($nginxOut -and $docOut -and $converterOut -and $schemaOut -and $defaultOut -and $rabbitOut -and $erlOut -and (-not $needsNode -or $nodeOut))) {
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
  schema = (Relative-To $DestinationDir $schemaOut.FullName)
  config_dir = (Relative-To $DestinationDir $defaultOut.Directory.FullName)
  rabbitmq = (Relative-To $DestinationDir $rabbitOut.FullName)
  erlang_home = (Relative-To $DestinationDir $erlOut.Directory.Parent.FullName)
}
if ($nodeOut) {
  $manifest.node = (Relative-To $DestinationDir $nodeOut.FullName)
}
$manifestPath = Join-Path $DestinationDir "bundle.json"
$manifestJson = $manifest | ConvertTo-Json -Depth 4
# Windows PowerShell 5.1 -Encoding UTF8 writes a BOM that Python json.loads rejects.
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($manifestPath, $manifestJson.TrimEnd() + "`n", $utf8NoBom)

$notice = @"
ONLYOFFICE Docs Community Edition is licensed under AGPL-3.0.
This desktop build vendors the official Windows installer plus Erlang/OTP $ErlangVersion and RabbitMQ $RabbitVersion so Word editing works offline after install.
Redistributing that combination inside a closed-source product requires an OnlyOffice commercial Developer license before a public release.
Document Server installer SHA256: $hash
"@
Set-Content -LiteralPath (Join-Path $DestinationDir "LICENSE-REDISTRIBUTION.txt") -Value $notice -Encoding UTF8
Write-Host "OnlyOffice bundle ready: $DestinationDir"
