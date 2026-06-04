$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

function Fail($Message) {
    Write-Error "[run_control_panel] $Message"
    exit 1
}

function Resolve-Python {
    if ($env:VIRTUAL_ENV) {
        $ActivePython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path $ActivePython) {
            return $ActivePython
        }
        Fail "VIRTUAL_ENV is set to '$env:VIRTUAL_ENV', but Scripts\python.exe was not found."
    }

    $Candidates = @(
        (Join-Path $Root ".venv311\Scripts\python.exe"),
        (Join-Path $Root ".venv\Scripts\python.exe")
    )

    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            return $Candidate
        }
    }

    Fail "Missing active venv, .venv311, or .venv. Run scripts/setup_dev.ps1 first."
}

$Python = Resolve-Python

$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*#" -or $_ -notmatch "=") { return }
        $name, $value = $_ -split "=", 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
    Write-Host "[run_control_panel] Loaded .env"
}

$env:PYTHONPATH = Join-Path $Root "src"
Write-Host "[run_control_panel] Using Python: $Python"
Write-Host "[run_control_panel] Starting Screen Translator control panel"
& $Python -m screen_translator.control_app
$ExitCode = $LASTEXITCODE
Write-Host "[run_control_panel] Exit code: $ExitCode"
exit $ExitCode
