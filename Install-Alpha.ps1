param([string]$Destination='', [switch]$NoShortcut, [switch]$Silent)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Get-ArchiveHash([string]$Path) {
    $stream=[IO.File]::OpenRead($Path)
    $algorithm=[Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
if (-not $Destination) {
    $Destination=Join-Path $env:LOCALAPPDATA 'Programs\PhotoRestoreStudio'
    if (-not $Silent) {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog=New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description='Выберите папку, внутри которой установить Photo Restore Studio'
        $dialog.SelectedPath=Join-Path $env:LOCALAPPDATA 'Programs'
        if ($dialog.ShowDialog() -ne 'OK') { exit 0 }
        $Destination=Join-Path $dialog.SelectedPath 'PhotoRestoreStudio'
    }
}
$target=[IO.Path]::GetFullPath($Destination).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (Test-Path -LiteralPath $target) { throw 'Для первой альфа-версии выберите новую папку. Существующая программа и файлы не заменяются.' }
$manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.version -ne '0.25-alpha-lite') { throw 'Неверная версия комплекта.' }
$archives=@($manifest.archives)
foreach($entry in $archives) {
    if ([IO.Path]::GetFileName($entry.name) -ne $entry.name -or $entry.name -notlike 'PhotoRestoreStudio-0.25-alpha-lite-part-*.zip') { throw 'Неверное имя архива.' }
    $path=Join-Path $PSScriptRoot $entry.name
    if (-not (Test-Path -LiteralPath $path)) { throw "Скачайте недостающий архив: $($entry.name)" }
    Write-Host "Проверка $($entry.name)..."
    if ((Get-ArchiveHash $path) -ne $entry.sha256) { throw "Повреждён архив: $($entry.name)" }
}
$parent=Split-Path -Parent $target
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$stage=Join-Path $parent ('PhotoRestore-install-'+[guid]::NewGuid().ToString('N'))
$stageAbsolute=[IO.Path]::GetFullPath($stage)
if (-not $stageAbsolute.StartsWith([IO.Path]::GetFullPath($parent).TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Неверная временная папка.' }
New-Item -ItemType Directory -Path $stageAbsolute | Out-Null
try {
    foreach($entry in $archives) {
        Write-Host "Установка $($entry.name)..."
        $archive=[IO.Compression.ZipFile]::OpenRead((Join-Path $PSScriptRoot $entry.name))
        try {
            foreach($item in $archive.Entries) {
                $relative=$item.FullName.Replace('/',[IO.Path]::DirectorySeparatorChar)
                $output=[IO.Path]::GetFullPath((Join-Path $stageAbsolute $relative))
                if (-not $output.StartsWith($stageAbsolute+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Недопустимый путь внутри архива.' }
                if ($item.FullName.EndsWith('/')) { New-Item -ItemType Directory -Force -Path $output | Out-Null; continue }
                if (-not $item.FullName.StartsWith('PhotoRestoreStudio/')) { throw 'Неверная структура архива.' }
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($item,$output,$false)
            }
        } finally {$archive.Dispose()}
    }
    $product=Join-Path $stageAbsolute 'PhotoRestoreStudio'
    if (-not (Test-Path -LiteralPath (Join-Path $product 'PhotoRestoreStudio.exe'))) {throw 'Не найден файл запуска.'}
    foreach($property in $manifest.models.PSObject.Properties) {
        $model=Join-Path $product $property.Name
        if (-not [IO.Path]::GetFullPath($model).StartsWith([IO.Path]::GetFullPath($product)+'\',[StringComparison]::OrdinalIgnoreCase)) {throw 'Неверный путь модели.'}
        if ((Get-ArchiveHash $model) -ne $property.Value) {throw 'Ошибка проверки модели.'}
    }
    Move-Item -LiteralPath $product -Destination $target
    Write-Host 'Сжатие библиотек без изменения качества...'
    foreach($folder in @('libraries','plugins')) {
        $compressPath=Join-Path $target $folder
        if (Test-Path -LiteralPath $compressPath) {
            & "$env:SystemRoot\System32\compact.exe" /C /F "/S:$compressPath" /EXE:LZX /I /Q | Out-Null
            if ($LASTEXITCODE -ne 0) {Write-Host 'Сжатие недоступно на этом диске; файлы установлены без сжатия.'}
        }
    }
    if (-not $NoShortcut) {
        $shell=New-Object -ComObject WScript.Shell
        $shortcut=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Photo Restore Studio Alpha.lnk'))
        $shortcut.TargetPath=Join-Path $target 'PhotoRestoreStudio.exe'
        $shortcut.WorkingDirectory=$target
        $shortcut.IconLocation=(Join-Path $target 'PhotoRestoreStudio.exe')+',0'
        $shortcut.Save()
    }
    Write-Host "Готово: $target"
    if (-not $Silent) {[System.Windows.Forms.MessageBox]::Show("Установлено в $target`nЗапустите PhotoRestoreStudio.exe или ярлык на рабочем столе.",'Photo Restore Studio') | Out-Null}
} finally {
    # Only remove the exact random staging directory created above; never the installation.
    if ((Test-Path -LiteralPath $stageAbsolute) -and $stageAbsolute -ne $target -and
        -not ((Get-Item -LiteralPath $stageAbsolute -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Remove-Item -LiteralPath $stageAbsolute -Recurse -Force
    }
}
