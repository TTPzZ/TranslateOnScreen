$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"

function Fail($Message) {
    Write-Error "[run_server] $Message"
    exit 1
}

if (-not (Test-Path $Python)) {
    Fail "Missing .venv. Run scripts/setup_dev.ps1 first."
}

try {
    py --version | Out-Null
} catch {
    Fail "Python launcher 'py' is required."
}

$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*#" -or $_ -notmatch "=") { return }
        $name, $value = $_ -split "=", 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
    Write-Host "[run_server] Loaded .env"
}

$env:PYTHONPATH = Join-Path $Root "src"
Write-Host "[run_server] Starting FastAPI server on http://127.0.0.1:8000"
& $Python -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
