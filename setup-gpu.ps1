$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Missing .venv. Run setup.cmd first."
}

Write-Host "Installing the optional NVIDIA CUDA 12 runtime for Whisper..."
Write-Host "The download is approximately 1 GB and requires additional disk space."
& $venvPython -m pip install -r requirements-gpu.txt

Write-Host ""
Write-Host "GPU runtime installation complete. Run run.cmd and select Auto or NVIDIA CUDA."
