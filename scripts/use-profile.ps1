param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev_low_resource", "test_real_stack", "demo_prod")]
    [string]$Profile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-EnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [hashtable]$Values,
        [string]$Header
    )

    $lines = @()
    if ($Header) {
        $lines += "# $Header"
    }

    foreach ($entry in $Values.GetEnumerator()) {
        $lines += "$($entry.Key)=$($entry.Value)"
    }

    $directory = Split-Path -Parent $Path
    if ($directory) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    Set-Content -LiteralPath $Path -Value ($lines -join [Environment]::NewLine) -Encoding UTF8
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$profilePath = Join-Path $repoRoot "configs\profiles\$Profile.json"
if (-not (Test-Path -LiteralPath $profilePath)) {
    throw "Profile definition not found: $profilePath"
}

$profile = Get-Content -LiteralPath $profilePath -Encoding UTF8 | ConvertFrom-Json -AsHashtable
$backendValues = $profile["backend"]
$frontendValues = $profile["frontend"]

if (-not $backendValues -or -not $frontendValues) {
    throw "Invalid profile payload: missing backend/frontend sections."
}

$backendEnvPath = Join-Path $repoRoot ".env.active"
$frontendEnvPath = Join-Path $repoRoot "frontend\.env.local"

Write-EnvFile -Path $backendEnvPath -Values $backendValues -Header "Generated from profile: $Profile"
Write-EnvFile -Path $frontendEnvPath -Values $frontendValues -Header "Generated from profile: $Profile"

Write-Host "Activated profile: $Profile" -ForegroundColor Green
Write-Host "Backend env : $backendEnvPath"
Write-Host "Frontend env: $frontendEnvPath"
Write-Host "Restart frontend if Vite env values changed." -ForegroundColor Yellow
