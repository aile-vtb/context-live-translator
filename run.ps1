$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Missing .venv. Run .\setup.ps1 first."
}

Set-Location -LiteralPath $projectRoot
& $venvPython -m context_live_translator
