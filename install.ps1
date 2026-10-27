param([string]$PythonExecutable = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PIP_NO_CACHE_DIR = '1'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if (-not $PythonExecutable) {
        $PythonExecutable = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    }
    if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw 'Для сборки укажите Python 3.12: .\install.ps1 -PythonExecutable <путь к python.exe>' }
    & $PythonExecutable -c "import sys; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'"
    if ($LASTEXITCODE -ne 0) { throw 'Для среды сборки нужен Python 3.12.' }
    & $PythonExecutable -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать среду сборки.' }
}
$wheel = Join-Path $PSScriptRoot 'wheels/torch-2.7.1+cu128-cp312-cp312-win_amd64.whl'
if (Test-Path -LiteralPath $wheel) {
    & $python -m pip install $wheel 'torchvision==0.22.1+cu128' --index-url https://download.pytorch.org/whl/cu128 --no-cache-dir --timeout 30 --retries 1
} else {
    & $python -m pip install 'torch==2.7.1' 'torchvision==0.22.1' --index-url https://download.pytorch.org/whl/cu128 --no-cache-dir --timeout 30 --retries 1
}
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить CUDA-библиотеки' }
& $python -m pip install wheel cython --no-cache-dir --timeout 30 --retries 1
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить инструменты сборки' }
& $python -m pip install -r requirements.txt --no-build-isolation --no-cache-dir --timeout 30 --retries 1
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости приложения' }
