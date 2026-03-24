param(
    [switch]$DryRun,
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($BackendOnly -and $FrontendOnly) {
    throw "Use either -BackendOnly or -FrontendOnly, not both."
}

function Quote-PowerShellLiteral {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return "'" + $Value.Replace("'", "''") + "'"
}

function Test-PortListening {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        return $null -ne $conn
    } catch {
        return $false
    }
}

function Start-DevWindow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    $quotedDir = Quote-PowerShellLiteral -Value $WorkingDirectory
    $quotedTitle = Quote-PowerShellLiteral -Value $Title
    $bootCommand = @(
        "Set-Location -LiteralPath $quotedDir"
        "try { `$Host.UI.RawUI.WindowTitle = $quotedTitle } catch {}"
        $Command
    ) -join "; "

    $arguments = @(
        "-NoExit"
        "-ExecutionPolicy"
        "Bypass"
        "-Command"
        $bootCommand
    )

    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory $WorkingDirectory | Out-Null
}

$repoRoot = Split-Path -Parent $PSCommandPath
$backendPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$frontendDir = Join-Path $repoRoot "frontend"
$frontendNodeModules = Join-Path $frontendDir "node_modules"

if (-not $FrontendOnly) {
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw "Backend Python not found: $backendPython . Create the virtual environment first."
    }
}

if (-not $BackendOnly) {
    if (-not (Test-Path -LiteralPath $frontendDir)) {
        throw "Frontend directory not found: $frontendDir"
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm was not found in PATH. Install Node.js first."
    }
    if (-not (Test-Path -LiteralPath $frontendNodeModules)) {
        throw "frontend\\node_modules not found. Run 'npm install' in the frontend directory first."
    }
}

$backendCommand = "& $(Quote-PowerShellLiteral -Value $backendPython) -m backend.main"
$frontendCommand = "npm run dev"

if ($DryRun) {
    Write-Host "Temporary dev launcher preview" -ForegroundColor Cyan
    Write-Host "Repo root : $repoRoot"
    if (-not $FrontendOnly) {
        Write-Host "Backend   : $backendCommand"
    }
    if (-not $BackendOnly) {
        Write-Host "Frontend  : $frontendCommand"
    }
    exit 0
}

if (-not $FrontendOnly) {
    if (Test-PortListening -Port 8000) {
        Write-Warning "Port 8000 is already in use. Backend may fail to start."
    }
    Start-DevWindow -Title "Auto Labeling Backend" -WorkingDirectory $repoRoot -Command $backendCommand
}

if (-not $BackendOnly) {
    if (Test-PortListening -Port 5173) {
        Write-Warning "Port 5173 is already in use. Vite may choose another port."
    }
    Start-DevWindow -Title "Auto Labeling Frontend" -WorkingDirectory $frontendDir -Command $frontendCommand
}

Write-Host "Started development services." -ForegroundColor Green
if (-not $FrontendOnly) {
    Write-Host "Backend health: http://127.0.0.1:8000/healthz"
}
if (-not $BackendOnly) {
    Write-Host "Frontend dev : http://localhost:5173"
}
