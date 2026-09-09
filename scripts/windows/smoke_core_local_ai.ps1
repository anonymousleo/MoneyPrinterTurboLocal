param()

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-MptRepoRoot
Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
Set-Location $RepoRoot

$RootPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SmokeScript = Join-Path $PSScriptRoot "smoke_core_local_ai.py"

if (-not (Test-Path $RootPython)) {
    throw "Project .venv missing. Run INSTALL.bat first."
}
if (-not (Test-Path $SmokeScript)) {
    throw "Smoke-test helper missing."
}

Write-Step "Core Local AI Functional Smoke"
& $RootPython $SmokeScript
exit $LASTEXITCODE
