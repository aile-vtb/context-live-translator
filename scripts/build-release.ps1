param(
    [string]$Version = "",
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $projectRoot

if (-not $AllowDirty) {
    $changes = & git status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Git status failed."
    }
    if ($changes) {
        throw "Working tree is not clean. Commit the release files or use -AllowDirty for a local test."
    }
}

if (-not $Version) {
    $versionLine = Select-String -LiteralPath "pyproject.toml" -Pattern '^version = "([^"]+)"$'
    if (-not $versionLine) {
        throw "Could not read the project version from pyproject.toml."
    }
    $Version = $versionLine.Matches[0].Groups[1].Value
}

if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Invalid release version: $Version"
}

$releaseRoot = Join-Path $projectRoot "dist\release"
$folderName = "ContextLiveTranslator-v$Version-Windows-Setup"
$stageRoot = Join-Path $releaseRoot $folderName
$zipPath = Join-Path $releaseRoot "$folderName.zip"
$checksumPath = "$zipPath.sha256"

$resolvedProject = (Resolve-Path -LiteralPath $projectRoot).Path
if (-not (Test-Path -LiteralPath $releaseRoot)) {
    New-Item -ItemType Directory -Path $releaseRoot | Out-Null
}
$resolvedRelease = (Resolve-Path -LiteralPath $releaseRoot).Path
if (-not $resolvedRelease.StartsWith($resolvedProject + [IO.Path]::DirectorySeparatorChar)) {
    throw "Release directory is outside the project root."
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
if (Test-Path -LiteralPath $checksumPath) {
    Remove-Item -LiteralPath $checksumPath -Force
}
New-Item -ItemType Directory -Path $stageRoot | Out-Null

$files = @(
    "setup.cmd",
    "setup.ps1",
    "setup-gpu.cmd",
    "setup-gpu.ps1",
    "run.cmd",
    "run.ps1",
    "README_FIRST.md",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "SECURITY.md",
    "requirements-lock.txt",
    "requirements-gpu.txt",
    "pyproject.toml"
)
foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $stageRoot
}

$sourceFiles = & git ls-files -- "src"
if ($LASTEXITCODE -ne 0 -or -not $sourceFiles) {
    throw "Could not enumerate tracked source files."
}
foreach ($relativePath in $sourceFiles) {
    $sourcePath = Join-Path $projectRoot $relativePath
    $destinationPath = Join-Path $stageRoot $relativePath
    $destinationDirectory = Split-Path -Parent $destinationPath
    if (-not (Test-Path -LiteralPath $destinationDirectory)) {
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    }
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
}

$forbiddenPatterns = @(
    '\\.git(?:\\|$)',
    '\\.venv(?:\\|$)',
    '\\sessions(?:\\|$)',
    '\\logs(?:\\|$)',
    '\\models(?:\\|$)',
    '\\runtime(?:\\|$)',
    '\\tests(?:\\|$)',
    '\\__pycache__(?:\\|$)',
    '\\[^\\]+\.egg-info(?:\\|$)',
    '\\config\.json$',
    '\\.env(?:\.|$)',
    '\.(?:pyc|pyo|gguf|safetensors|onnx|ct2)$'
)
$stagedFiles = Get-ChildItem -LiteralPath $stageRoot -Recurse -Force -File
$requiredReleaseFiles = @(
    "README_FIRST.md",
    "setup.cmd",
    "setup-gpu.cmd",
    "requirements-gpu.txt",
    "src\context_live_translator\cuda_runtime.py",
    "run.cmd",
    "src\context_live_translator\static\logo.gif"
)
foreach ($relativePath in $requiredReleaseFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $stageRoot $relativePath))) {
        throw "Required release content is missing: $relativePath"
    }
}
foreach ($item in $stagedFiles) {
    foreach ($pattern in $forbiddenPatterns) {
        if ($item.FullName -match $pattern) {
            throw "Forbidden release content: $($item.FullName)"
        }
    }
}

Compress-Archive -LiteralPath $stageRoot -DestinationPath $zipPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $checksumPath -Encoding ASCII

Write-Host "Release package: $zipPath"
Write-Host "SHA-256: $hash"
Write-Host "Files: $($stagedFiles.Count)"
