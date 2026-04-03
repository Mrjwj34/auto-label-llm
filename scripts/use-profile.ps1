param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev_low_resource", "test_real_stack", "demo_prod")]
    [string]$Profile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$helperScript = Join-Path $PSScriptRoot "use_profile.py"
if (-not (Test-Path -LiteralPath $helperScript)) {
    throw "Profile helper script not found: $helperScript"
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython $helperScript --repo-root $repoRoot --profile $Profile
    exit $LASTEXITCODE
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source $helperScript --repo-root $repoRoot --profile $Profile
    exit $LASTEXITCODE
}

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    & $pyLauncher.Source -3 $helperScript --repo-root $repoRoot --profile $Profile
    exit $LASTEXITCODE
}

throw "Python was not found. Install Python or create .venv before switching profiles."
