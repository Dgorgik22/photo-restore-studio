param([string]$ReleaseDirectory='')
$ErrorActionPreference='Stop'
$restoreProject=Split-Path -Parent $PSScriptRoot
if(-not $ReleaseDirectory) {$ReleaseDirectory=Join-Path (Split-Path -Parent $restoreProject) 'Releases\PhotoRestoreStudio-0.25-alpha-lite'}
$restoreRelease=[IO.Path]::GetFullPath($ReleaseDirectory)
$restoreManifest=Get-Content -LiteralPath (Join-Path $restoreRelease 'manifest.json') -Raw | ConvertFrom-Json
if($restoreManifest.version -ne '0.25-alpha-lite') {throw 'Unexpected release version'}
$restorePayload=Join-Path $PSScriptRoot 'release.json'
@{version=$restoreManifest.version;archives=$restoreManifest.archives;models=$restoreManifest.models;unpacked_bytes=$restoreManifest.unpacked_bytes} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $restorePayload -Encoding UTF8
$restoreCompiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$restoreSetup=Join-Path $restoreRelease 'PhotoRestoreStudio-0.25-alpha-lite-Setup.exe'
& $restoreCompiler /nologo /target:winexe /platform:anycpu /optimize+ /debug- /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Net.Http.dll /r:System.Web.Extensions.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll "/win32icon:$(Join-Path $restoreProject 'assets\brand\photo-restore.ico')" "/resource:$restorePayload,release.json" "/out:$restoreSetup" (Join-Path $PSScriptRoot 'InstallerEngine.cs') (Join-Path $PSScriptRoot 'Setup.cs')
if($LASTEXITCODE -ne 0) {throw 'Setup compilation failed'}
Get-Item -LiteralPath $restoreSetup | Select-Object Name,Length
