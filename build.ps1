param([string]$OutputDirectory = '',[switch]$KeepPrevious,[switch]$SkipValidation)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Среда разработки удалена для экономии места. Для новой сборки сначала выполните .\install.ps1. Установленный exe работает без неё.' }
$restoreRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$restoreHome = Join-Path $restoreRoot 'PhotoRestoreStudio'
$restoreReleases = Join-Path $restoreRoot 'releases'
function Assert-BuildChild([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not $absolute.StartsWith($restoreRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw "Path outside project: $absolute" }
    if ((Test-Path -LiteralPath $absolute) -and ((Get-Item -LiteralPath $absolute -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Linked path rejected: $absolute" }
    return $absolute
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $restoreReleases ('staging-'+(Get-Date -Format 'yyyyMMdd-HHmmss')) }
$restoreStage = Assert-BuildChild $OutputDirectory
if (Test-Path -LiteralPath $restoreStage) { throw 'Выберите новую папку сборки.' }
if (@(Get-Process PhotoRestoreStudio -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($restoreHome+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) }).Count) { throw 'Перед обновлением закройте Photo Restore Studio.' }
$restoreCache = Join-Path $restoreHome 'storage/cache'
$restoreSettings = Join-Path $restoreHome 'storage/settings.json'
if (Test-Path -LiteralPath $restoreSettings) {
    $chosenCache = (Get-Content -LiteralPath $restoreSettings -Raw | ConvertFrom-Json).cache_path
    if ($chosenCache -and (Test-Path -LiteralPath (Join-Path $chosenCache '.photo-restore-managed.json'))) { $restoreCache = $chosenCache }
}
$restoreBuildCache = Join-Path $restoreCache 'build'
New-Item -ItemType Directory -Force -Path $restoreBuildCache,(Join-Path $restoreCache 'matplotlib'),$restoreReleases | Out-Null
$env:MPLCONFIGDIR = Join-Path $restoreCache 'matplotlib'
& .\.venv\Scripts\python.exe freeze.py --distpath $restoreStage --workpath (Join-Path $restoreBuildCache 'work') --specpath (Join-Path $restoreBuildCache 'spec')
if ($LASTEXITCODE -ne 0) { throw 'Сборка не завершена. Рабочая программа сохранена.' }
$restoreProduct = Join-Path $restoreStage 'PhotoRestoreStudio'
& .\.venv\Scripts\python.exe prune_runtime.py $restoreProduct
if ($LASTEXITCODE -ne 0) { throw 'Не удалось исключить неиспользуемые компоненты.' }
& .\.venv\Scripts\python.exe collect_licenses.py $restoreProduct
if ($LASTEXITCODE -ne 0) { throw 'Не удалось собрать уведомления о лицензиях.' }
foreach ($notice in @('Real-ESRGAN-BSD-3-Clause.txt','PBRify-CC0.txt','CodeFormer-SLab.txt')) {
    Copy-Item -LiteralPath (Join-Path 'assets/licenses' $notice) -Destination (Join-Path $restoreProduct 'licenses')
}
Copy-Item -LiteralPath 'catalog.json' -Destination (Join-Path $restoreProduct 'licenses/models.json')
$restoreBackup = Assert-BuildChild (Join-Path $restoreReleases ('previous-'+(Get-Date -Format 'yyyyMMdd-HHmmss')))
New-Item -ItemType Directory -Force -Path $restoreBackup | Out-Null
$restoreParts = @('PhotoRestoreStudio.exe','libraries','licenses')
$restoreInstalled = [Collections.Generic.List[string]]::new()
try {
    foreach ($part in $restoreParts) {
        $current = Assert-BuildChild (Join-Path $restoreHome $part)
        if (Test-Path -LiteralPath $current) { Move-Item -LiteralPath $current -Destination (Join-Path $restoreBackup $part) }
        Move-Item -LiteralPath (Join-Path $restoreProduct $part) -Destination $current
        $restoreInstalled.Add($part)
    }
    foreach ($document in @('README.md','ARCHITECTURE.md','VALIDATION.md','requirements-lock.txt')) {
        if (Test-Path -LiteralPath $document) { Copy-Item -LiteralPath $document -Destination (Join-Path $restoreHome $document) -Force }
    }
    & compact.exe /C /F "/S:$(Join-Path $restoreHome 'libraries')" /EXE:LZX /I /Q
    & compact.exe /C /F "/S:$(Join-Path $restoreHome 'plugins')" /EXE:LZX /I /Q
    if (-not $SkipValidation) {
        foreach ($argument in @('--startup-probe','--diagnostics')) {
            $validation = Start-Process -FilePath (Join-Path $restoreHome 'PhotoRestoreStudio.exe') -ArgumentList $argument -WindowStyle Hidden -Wait -PassThru
            if ($validation.ExitCode -ne 0) { throw "Проверка готовой программы завершилась с ошибкой: $argument, код $($validation.ExitCode)" }
        }
    }
} catch {
    foreach ($part in $restoreInstalled) {
        $current = Assert-BuildChild (Join-Path $restoreHome $part)
        Remove-Item -LiteralPath $current -Recurse -Force
    }
    foreach ($part in $restoreParts) {
        $previous = Join-Path $restoreBackup $part
        if (Test-Path -LiteralPath $previous) { Move-Item -LiteralPath $previous -Destination (Join-Path $restoreHome $part) }
    }
    throw
}
if (-not $KeepPrevious -and -not $SkipValidation) { Remove-Item -LiteralPath (Assert-BuildChild $restoreBackup) -Recurse -Force }
Remove-Item -LiteralPath (Assert-BuildChild $restoreStage) -Recurse -Force
$restoreShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Photo Restore Studio.lnk'
if (Test-Path -LiteralPath $restoreShortcutPath) {
    $restoreShell = New-Object -ComObject WScript.Shell
    $restoreShortcut = $restoreShell.CreateShortcut($restoreShortcutPath)
    $restoreIcon = [IO.Path]::GetFullPath((Join-Path $restoreHome 'libraries/assets/brand/photo-restore.ico'))
    if ($restoreShortcut.TargetPath -eq (Join-Path $restoreHome 'PhotoRestoreStudio.exe') -or $restoreShortcut.IconLocation -eq "$restoreIcon,0") {
        $restoreShortcut.TargetPath = Join-Path $restoreHome 'PhotoRestoreStudio.exe'
        $restoreShortcut.WorkingDirectory = $restoreHome
        $restoreShortcut.IconLocation = "$restoreIcon,0"
        $restoreShortcut.Save()
    }
}
Write-Output "Installed: $(Join-Path $restoreHome 'PhotoRestoreStudio.exe')"
