#Requires -Version 5.1
<#
.SYNOPSIS
    One command to set up and start the whole VetScribe stack on Windows:
    backend, desktop tray app, and mobile companion.

.DESCRIPTION
    Installs dependencies for all three components, wires them together using the
    per-component `.env` files as the single source of truth for environment
    variables, and then launches every service (each in its own window):

      * backend/.env  - provider keys, note/transcription provider, PORT,
                        VETSCRIBE_BACKEND_API_KEY, VETSCRIBE_EXAMS_PATH.
                        Loaded automatically by BackendConfig.from_env().
      * mobile/.env   - EXPO_PUBLIC_VETSCRIBE_API_URL / _API_KEY. Loaded
                        automatically by Expo.

    Where a `.env` is missing it is created from the matching `.env.example` so
    you have something to fill in. The desktop tray app has no `.env` (it reads
    ~/.vetscribe/config.json), so this script seeds that config from backend/.env
    -- pointing the desktop app at the backend port and copying the shared
    bearer key across so the three pieces agree without hand-editing.

    By default the script runs setup and then starts backend + desktop + mobile.

.PARAMETER NoInstall
    Skip dependency install and .env creation -- just (re)start the services.
    Use this for a fast restart once you've already run setup once.

.PARAMETER NoStart
    Run setup only; do not start any services.

.PARAMETER SkipMobile
    Ignore the mobile app entirely (no npm install, not started) -- useful on the
    exam-room PC that only runs the backend + desktop app.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoInstall

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -SkipMobile
#>
param(
    [switch]$NoInstall,
    [switch]$NoStart,
    [switch]$SkipMobile
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Text)
    Write-Host "    ! $Text" -ForegroundColor Yellow
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# Parse a .env file into an ordered hashtable. Ignores blank lines and comments;
# keeps everything after the first '=' verbatim (values may contain '=').
function Import-DotEnv {
    param([string]$Path)
    $map = [ordered]@{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $idx = $trimmed.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $trimmed.Substring(0, $idx).Trim()
        $val = $trimmed.Substring($idx + 1).Trim()
        # Strip surrounding quotes if present.
        if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $map[$key] = $val
    }
    return $map
}

# Copy example -> real .env only when the real one is missing.
function Initialize-EnvFile {
    param([string]$EnvPath, [string]$ExamplePath, [string]$Label)
    if (Test-Path $EnvPath) {
        Write-Host "    $Label .env already present -- leaving it untouched."
        return $false
    }
    if (-not (Test-Path $ExamplePath)) {
        Write-Warn "$Label has no .env and no .env.example ($ExamplePath) -- skipping."
        return $false
    }
    Copy-Item -LiteralPath $ExamplePath -Destination $EnvPath
    Write-Warn "$Label .env created from .env.example -- edit it and fill in your values."
    return $true
}

# Start one service in its own PowerShell window so its logs stay visible.
function Start-Service-Window {
    param([string]$Title, [string]$WorkingDir, [string]$Command)
    Write-Host "    Starting $Title..."
    Start-Process -FilePath 'powershell' -ArgumentList @(
        '-NoExit', '-Command',
        "`$host.UI.RawUI.WindowTitle = 'VetScribe: $Title'; Set-Location '$WorkingDir'; $Command"
    )
}

Write-Host "VetScribe full-stack launcher" -ForegroundColor Green
Write-Host "Repo: $RepoRoot"

$backendDir = Join-Path $RepoRoot 'backend'
$mobileDir  = Join-Path $RepoRoot 'mobile'

# ---------------------------------------------------------------------------
# Prerequisites (needed to install AND to run)
# ---------------------------------------------------------------------------
Write-Section "Checking prerequisites"

$missing = @()
if (-not (Test-Command 'uv'))     { $missing += 'uv (https://docs.astral.sh/uv/ -- winget install astral-sh.uv)' }
if (-not $SkipMobile) {
    if (-not (Test-Command 'node')) { $missing += 'node (https://nodejs.org/ -- winget install OpenJS.NodeJS.LTS)' }
    if (-not (Test-Command 'npm'))  { $missing += 'npm (ships with Node.js)' }
}
if ($missing.Count -gt 0) {
    Write-Host "Missing required tools:" -ForegroundColor Red
    foreach ($m in $missing) { Write-Host "  - $m" -ForegroundColor Red }
    throw "Install the tools above, then re-run setup.ps1."
}
Write-Host "    uv:   $((uv --version) 2>&1)"
if (-not $SkipMobile) {
    Write-Host "    node: $((node --version) 2>&1)"
    Write-Host "    npm:  $((npm --version) 2>&1)"
}

# ---------------------------------------------------------------------------
# Backend deps + .env
# ---------------------------------------------------------------------------
Write-Section "Backend (backend/)"
if (-not $NoInstall) {
    Initialize-EnvFile `
        -EnvPath (Join-Path $backendDir '.env') `
        -ExamplePath (Join-Path $backendDir '.env.example') `
        -Label 'backend' | Out-Null

    Push-Location $backendDir
    try {
        Write-Host "    Installing backend dependencies (uv sync)..."
        uv sync
        if ($LASTEXITCODE -ne 0) { throw "backend 'uv sync' failed (exit $LASTEXITCODE)." }
    }
    finally { Pop-Location }
}
else {
    Write-Host "    -NoInstall: skipping backend .env creation and uv sync."
}

$backendEnv = Import-DotEnv (Join-Path $backendDir '.env')
$backendPort = if ($backendEnv['PORT']) { $backendEnv['PORT'] } else { '8443' }
$backendKey  = $backendEnv['VETSCRIBE_BACKEND_API_KEY']
if ($null -eq $backendKey) { $backendKey = '' }

# ---------------------------------------------------------------------------
# Desktop deps + config
# ---------------------------------------------------------------------------
Write-Section "Desktop tray app (root)"
if (-not $NoInstall) {
    Push-Location $RepoRoot
    try {
        Write-Host "    Installing desktop dependencies (uv sync)..."
        uv sync
        if ($LASTEXITCODE -ne 0) { throw "desktop 'uv sync' failed (exit $LASTEXITCODE)." }
    }
    finally { Pop-Location }
}
else {
    Write-Host "    -NoInstall: skipping desktop uv sync."
}

# Seed ~/.vetscribe/config.json from backend/.env so the desktop app points at
# the local backend and shares its bearer key. Merge into an existing config so
# we don't stomp a vet's other settings (hotkey, window matcher, etc.).
$vetscribeDir = Join-Path $HOME '.vetscribe'
if (-not (Test-Path $vetscribeDir)) { New-Item -ItemType Directory -Path $vetscribeDir | Out-Null }
$configPath = Join-Path $vetscribeDir 'config.json'

$config = [ordered]@{
    api_endpoint          = "https://localhost:8443/api/soap"
    api_timeout_seconds   = 30
    hotkey                = "<ctrl>+<shift>+r"
    api_key               = ""
    target_window_matcher = "AVImark"
    launch_on_startup     = $false
}
if (Test-Path $configPath) {
    $existing = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    foreach ($p in $existing.PSObject.Properties) { $config[$p.Name] = $p.Value }
}
$config['api_endpoint'] = "http://localhost:$backendPort/api/soap"
$config['api_key'] = $backendKey
($config | ConvertTo-Json) | Set-Content -LiteralPath $configPath -Encoding UTF8
Write-Host "    Wrote desktop config: $configPath"
Write-Host "      api_endpoint = $($config['api_endpoint'])"
if ([string]::IsNullOrEmpty($backendKey)) {
    Write-Warn "backend/.env has no VETSCRIBE_BACKEND_API_KEY -- desktop configured for unauthenticated access."
}

# ---------------------------------------------------------------------------
# Mobile deps + .env
# ---------------------------------------------------------------------------
if ($SkipMobile) {
    Write-Section "Mobile companion (mobile/) -- skipped (-SkipMobile)"
}
else {
    Write-Section "Mobile companion (mobile/)"
    if (-not $NoInstall) {
        Initialize-EnvFile `
            -EnvPath (Join-Path $mobileDir '.env') `
            -ExamplePath (Join-Path $mobileDir '.env.example') `
            -Label 'mobile' | Out-Null

        $mobileEnv = Import-DotEnv (Join-Path $mobileDir '.env')
        if ($mobileEnv['EXPO_PUBLIC_VETSCRIBE_API_URL'] -like '*192.168.1.50*') {
            Write-Warn "mobile/.env still points EXPO_PUBLIC_VETSCRIBE_API_URL at the placeholder LAN IP (192.168.1.50)."
            Write-Warn "Set it to this machine's LAN IP:$backendPort so a physical phone can reach the backend."
        }

        Push-Location $mobileDir
        try {
            Write-Host "    Installing mobile dependencies (npm install)..."
            npm install
            if ($LASTEXITCODE -ne 0) { throw "mobile 'npm install' failed (exit $LASTEXITCODE)." }
        }
        finally { Pop-Location }
    }
    else {
        Write-Host "    -NoInstall: skipping mobile .env creation and npm install."
    }
}

# ---------------------------------------------------------------------------
# Start the services
# ---------------------------------------------------------------------------
if ($NoStart) {
    Write-Section "Setup complete (-NoStart: not launching services)"
    Write-Host "Start them yourself when ready:" -ForegroundColor Green
    Write-Host "  Backend:  cd backend; uv run python -m vetscribe_backend.main"
    Write-Host "  Desktop:  uv run python -m vetscribe.main"
    if (-not $SkipMobile) { Write-Host "  Mobile:   cd mobile; npm start" }
    return
}

Write-Section "Starting services"
Start-Service-Window -Title 'backend' -WorkingDir $backendDir `
    -Command 'uv run python -m vetscribe_backend.main'
# Give the backend a moment to bind its port before the desktop app starts
# polling it.
Start-Sleep -Seconds 3
Start-Service-Window -Title 'desktop' -WorkingDir $RepoRoot `
    -Command 'uv run python -m vetscribe.main'
if (-not $SkipMobile) {
    Start-Service-Window -Title 'mobile' -WorkingDir $mobileDir -Command 'npm start'
}

Write-Section "All services launched"
Write-Host "Each runs in its own window:" -ForegroundColor Green
Write-Host "  Backend:  http://localhost:$backendPort/api/soap"
Write-Host "  Desktop:  tray app (press $($config['hotkey']) to record)"
if (-not $SkipMobile) {
    Write-Host "  Mobile:   Expo dev server -- scan the QR code with Expo Go"
}
Write-Host ""
Write-Host "Close a service by closing its window (or Ctrl+C inside it)."
Write-Host "Fill in API keys in backend\.env before generating real notes."
