$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

function Fail($Message) {
    Write-Error "[run_tests] $Message"
    exit 1
}

function Add-PythonCandidate([System.Collections.Generic.List[string]] $Candidates, [string] $Path) {
    if ($Path -and -not $Candidates.Contains($Path)) {
        $Candidates.Add($Path)
    }
}

$Candidates = [System.Collections.Generic.List[string]]::new()
if ($env:VIRTUAL_ENV) {
    Add-PythonCandidate $Candidates (Join-Path $env:VIRTUAL_ENV "Scripts\python.exe")
}
Add-PythonCandidate $Candidates (Join-Path $Root ".venv311\Scripts\python.exe")
Add-PythonCandidate $Candidates (Join-Path $Root ".venv\Scripts\python.exe")

$Python = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) {
    Fail "Missing virtual environment. Run scripts/setup_dev.ps1 first."
}

Write-Host "[run_tests] Using Python $Python"

try {
    py --version | Out-Null
} catch {
    Fail "Python launcher 'py' is required."
}

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = Join-Path $Root "src"
Write-Host "[run_tests] Running pytest"
& $Python -m pytest -q -p no:cacheprovider
