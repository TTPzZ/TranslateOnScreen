param(
    [string]$PythonVersion = "3.11",
    [switch]$SkipDesktop
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Fail($Message) {
    Write-Error "[setup_dev] $Message"
    exit 1
}

try {
    py -$PythonVersion --version | Out-Host
} catch {
    Fail "Python launcher 'py -$PythonVersion' failed. Install Python 3.11 or 3.12 and retry."
}

if (-not (Test-Path $Python)) {
    Write-Host "[setup_dev] Creating virtual environment at $Venv"
    py -$PythonVersion -m venv $Venv
}

if (-not (Test-Path $Python)) {
    Fail "Virtual environment was not created correctly."
}

$VersionCheck = & $Python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)"
if ($LASTEXITCODE -ne 0) {
    Fail "Python 3.11 or 3.12 is required. Re-run with a supported launcher target, for example: scripts/setup_dev.ps1 -PythonVersion 3.11"
}

Write-Host "[setup_dev] Upgrading pip"
& $Python -m pip install --upgrade pip

if ($SkipDesktop) {
    Write-Host "[setup_dev] Installing dev dependencies only"
    & $Python -m pip install -e ".[dev]"
} else {
    Write-Host "[setup_dev] Installing dev, desktop, and Google dependencies"
    & $Python -m pip install -e ".[dev,desktop,google]"
}

Write-Host "[setup_dev] Complete. Activate with: .\.venv\Scripts\Activate.ps1"
