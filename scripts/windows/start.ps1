param()

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-MptRepoRoot
Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
Set-Location $RepoRoot

$UvExe = Join-Path $RepoRoot ".tools\uv\uv.exe"
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $UvExe) -or -not (Test-Path $PythonExe)) {
    Write-Host "Runtime is not installed."
    Write-Host "Run INSTALL.bat and VERIFY.bat first."
    exit 2
}

Write-Step "Starting MoneyPrinterTurbo-LocalAI"
Write-Host "Models root : $env:MPT_LOCAL_MODELS_DIR"
if ($env:HTTPS_PROXY) { Write-Host "Proxy       : $env:HTTPS_PROXY" }
Write-Host ""

$env:PATH = "$(Split-Path $UvExe);$env:PATH"
& cmd.exe /c "`"$RepoRoot\webui.bat`""
exit $LASTEXITCODE
