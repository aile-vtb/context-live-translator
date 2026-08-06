$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$env:PYTHONIOENCODING = "utf-8"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Windows Python Launcher (py.exe) was not found. Install 64-bit Python 3.11 first."
}

$selectedPython = $null
$savedErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
foreach ($candidate in @("-3.11", "-3.10", "-3.12")) {
    & py $candidate -c "import struct, sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,13) and struct.calcsize('P') == 8 else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $selectedPython = $candidate
        break
    }
}
$ErrorActionPreference = $savedErrorPreference
if (-not $selectedPython) {
    throw "64-bit Python 3.10, 3.11, or 3.12 is required. Install Python 3.11.9 x64 from README_FIRST.md."
}

$pythonDescription = & py $selectedPython -c "import platform, struct; print(platform.python_version() + ' (' + str(struct.calcsize('P') * 8) + '-bit)')"
Write-Host "Using Python $pythonDescription"

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv with $selectedPython..."
    & py $selectedPython -m venv .venv
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
Write-Host "Installing pinned runtime dependencies..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements-lock.txt
& $venvPython -m pip install -e . --no-deps

Write-Host ""
Write-Host "Running read-only diagnostics (missing model errors are expected before setup)..."
& $venvPython -m context_live_translator --doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Dependencies are installed, but local model or hardware setup is incomplete. See README.md."
}

Write-Host ""
Write-Host "Installation complete. No models were downloaded. Run run.cmd, then configure models in the GUI."
