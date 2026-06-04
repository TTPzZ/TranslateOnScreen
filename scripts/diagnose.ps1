$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

function Fail($Message) {
    Write-Error "[diagnose] $Message"
    exit 1
}

function Resolve-Python {
    if ($env:VIRTUAL_ENV) {
        $ActivePython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
        if (Test-Path $ActivePython) {
            return @{ Command = $ActivePython; Args = @() }
        }
        Fail "VIRTUAL_ENV is set to '$env:VIRTUAL_ENV', but Scripts\python.exe was not found."
    }

    $Candidates = @(
        (Join-Path $Root ".venv311\Scripts\python.exe"),
        (Join-Path $Root ".venv\Scripts\python.exe")
    )

    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            return @{ Command = $Candidate; Args = @() }
        }
    }

    Write-Host "[diagnose] No active venv, .venv311, or .venv found; using Python launcher py -3.11"
    return @{ Command = "py"; Args = @("-3.11") }
}

$Resolved = Resolve-Python
$Python = $Resolved.Command
$PythonArgs = $Resolved.Args
$env:PYTHONPATH = Join-Path $Root "src"
Write-Host "[diagnose] Using Python command: $Python $($PythonArgs -join ' ')"
& $Python @PythonArgs -m screen_translator.diagnostics
$ExitCode = $LASTEXITCODE
Write-Host "[diagnose] Exit code: $ExitCode"
exit $ExitCode
