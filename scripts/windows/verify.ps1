param()

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-MptRepoRoot
Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
Set-Location $RepoRoot

$Failures = New-Object System.Collections.Generic.List[string]

function Pass([string]$Message) { Write-Host "[PASS] $Message" }
function Fail([string]$Message) { Write-Host "[FAIL] $Message"; $Failures.Add($Message) }
function Warn([string]$Message) { Write-Host "[WARN] $Message" }

Write-Step "MoneyPrinterTurbo-LocalAI Verification"

$UvExe = Join-Path $RepoRoot ".tools\uv\uv.exe"
if (Test-Path $UvExe) {
    Pass "project-local uv exists"
    & $UvExe --version
} else {
    Fail "project-local uv is missing; run INSTALL.bat"
}

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $PythonExe) {
    Pass "project Python environment exists"
    & $PythonExe --version

    & $PythonExe -c "import streamlit, requests; print('core Python imports: PASS')"
    if ($LASTEXITCODE -eq 0) { Pass "core Python imports" } else { Fail "core Python imports" }

    & $PythonExe -m compileall -q `
        "app/services/local_paths.py" `
        "app/services/local_auto_runtime.py" `
        "app/services/local_models.py" `
        "app/services/cogvideox_local.py" `
        "app/services/task.py" `
        "app/services/voice.py" `
        "webui/Main.py"
    if ($LASTEXITCODE -eq 0) { Pass "LocalAI Python compilation" } else { Fail "LocalAI Python compilation" }
} else {
    Fail ".venv is missing; run INSTALL.bat"
}

if (Test-Path (Join-Path $RepoRoot "config.toml")) {
    Pass "config.toml exists"
} else {
    Fail "config.toml missing"
}

$ffmpeg = Find-Executable "ffmpeg.exe"
if ($ffmpeg) {
    Pass "FFmpeg found: $ffmpeg"
} else {
    Fail "FFmpeg not found"
}

$ollama = Find-Executable "ollama.exe"
if ($ollama) {
    Pass "Ollama found: $ollama"
    & $ollama --version
} else {
    Warn "Ollama not found; local Qwen LLM will be unavailable until installed."
}

$nvidia = Find-Executable "nvidia-smi.exe"
if ($nvidia) {
    Pass "NVIDIA driver utilities found"
    & $nvidia --query-gpu=name,memory.total,driver_version --format=csv,noheader
} else {
    Warn "nvidia-smi not found. CogVideoX GPU mode requires a supported NVIDIA setup."
}

Write-Host ""
Write-Host "Models root    : $env:MPT_LOCAL_MODELS_DIR"
Write-Host "CogVideoX path : $env:MPT_COGVIDEOX_MODEL_DIR"
if ($env:HTTPS_PROXY) { Write-Host "Proxy          : $env:HTTPS_PROXY" }
else { Write-Host "Proxy          : none" }

$ProfileMarker = Join-Path $RepoRoot ".runtime\local_ai_profile.txt"
if (Test-Path $ProfileMarker) {
    $InstalledProfile = (Get-Content -LiteralPath $ProfileMarker -Raw).Trim()
    if ($InstalledProfile -in @("Core","Full")) {
        Write-Step "Local AI payload verification ($InstalledProfile)"
        $LocalVerifier = Join-Path $PSScriptRoot "verify_local_ai.ps1"
        if (-not (Test-Path $LocalVerifier)) {
            Fail "verify_local_ai.ps1 is missing"
        } else {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $LocalVerifier
            if ($LASTEXITCODE -eq 0) {
                Pass "Local AI payload verification ($InstalledProfile)"
            } else {
                Fail "Local AI payload verification ($InstalledProfile)"
            }
        }
    } elseif ($InstalledProfile -eq "Base") {
        Warn "Base-only profile installed; local AI payload verification skipped."
    } else {
        Warn "Unknown local AI profile marker: $InstalledProfile"
    }
} else {
    Warn "No local AI profile marker found. Run INSTALL.bat or SETUP_LOCAL_AI.bat."
}

if ($Failures.Count -gt 0) {
    Write-Host ""
    Write-Host "VERIFICATION FAILED: $($Failures.Count) required check(s) failed."
    exit 1
}

Write-Host ""
Write-Host "VERIFICATION PASS"
exit 0
