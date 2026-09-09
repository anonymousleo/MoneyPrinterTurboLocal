param()

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-MptRepoRoot
Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
Set-Location $RepoRoot

$Failures = New-Object System.Collections.Generic.List[string]

function Pass([string]$Message) {
    Write-Host "[PASS] $Message"
}

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message"
    $Failures.Add($Message)
}

function Warn([string]$Message) {
    Write-Host "[WARN] $Message"
}

$cfg = Get-Content `
    -LiteralPath (Join-Path $RepoRoot "local_ai_manifest.json") `
    -Raw | ConvertFrom-Json

Write-Step "MoneyPrinterTurbo-LocalAI Payload Verification"

$ollama = Find-Executable "ollama.exe"
if ($ollama) {
    & $ollama show ([string]$cfg.qwen.model) *> $null
    if ($LASTEXITCODE -eq 0) {
        Pass "Ollama model $($cfg.qwen.model)"
    }
    else {
        Fail "Ollama model $($cfg.qwen.model) missing"
    }
}
else {
    Fail "Ollama executable missing"
}

$WhisperDir = Join-Path $RepoRoot ([string]$cfg.whisper.local_dir)
$WhisperRequired = @("model.bin", "config.json", "tokenizer.json")
$MissingWhisper = @(
    $WhisperRequired | Where-Object {
        -not (Test-Path (Join-Path $WhisperDir $_))
    }
)

if ($MissingWhisper.Count -eq 0) {
    Pass "faster-whisper medium model"
}
else {
    Fail ("Whisper incomplete: " + ($MissingWhisper -join ", "))
}

$ChatterDir = Join-Path $RepoRoot "local_apps\chatterbox-tts-api"
$ChatterPython = Join-Path $ChatterDir ".venv\Scripts\python.exe"

if (Test-Path $ChatterPython) {
    $ChatterCheck = 'import torch; print(torch.__version__, torch.cuda.is_available()); raise SystemExit(0 if torch.cuda.is_available() else 1)'
    & $ChatterPython -c $ChatterCheck

    if ($LASTEXITCODE -eq 0) {
        Pass "Chatterbox CUDA environment"
    }
    else {
        Fail "Chatterbox CUDA environment"
    }

    $RevisionFile = Join-Path $ChatterDir ".source-revision"
    if (Test-Path $RevisionFile) {
        $rev = (Get-Content -LiteralPath $RevisionFile -Raw).Trim()
        Pass "Chatterbox source revision recorded: $rev"
    }
    else {
        Warn "Chatterbox source revision file missing"
    }
}
else {
    Fail "Chatterbox runtime missing"
}

$CogDir = Join-Path $RepoRoot "local_apps\cogvideox"
$CogPython = Join-Path $CogDir ".venv\Scripts\python.exe"
$CogModel = $env:MPT_COGVIDEOX_MODEL_DIR

if (Test-Path $CogPython) {
    $CogCheck = 'import torch, diffusers, transformers, accelerate, torchao; print(torch.__version__, torch.cuda.is_available(), diffusers.__version__, transformers.__version__); raise SystemExit(0 if torch.cuda.is_available() else 1)'
    & $CogPython -c $CogCheck

    if ($LASTEXITCODE -eq 0) {
        Pass "CogVideoX CUDA environment"
    }
    else {
        Fail "CogVideoX CUDA environment"
    }

    if (Test-Path (Join-Path $CogModel "model_index.json")) {
        Pass "CogVideoX model present"
    }
    else {
        Warn "CogVideoX environment exists but model is not downloaded"
    }

    $worker = Join-Path $CogDir "cogvideox_worker.py"
    if (Test-Path $worker) {
        $workerText = Get-Content -LiteralPath $worker -Raw
        $markers = @(
            "CPU_T5_PRECOMPUTE_START",
            "prompt_embeds",
            "enable_sequential_cpu_offload"
        )
        $MissingMarkers = @(
            $markers | Where-Object { -not $workerText.Contains($_) }
        )

        if ($MissingMarkers.Count -eq 0) {
            Pass "CogVideoX 8 GB CPU-T5/sequential-offload markers"
        }
        else {
            Fail (
                "CogVideoX low-VRAM worker markers missing: " +
                ($MissingMarkers -join ", ")
            )
        }
    }
}
else {
    Warn "CogVideoX optional Full profile is not installed"
}

if ($Failures.Count -gt 0) {
    Write-Host ""
    Write-Host "LOCAL AI VERIFICATION FAILED: $($Failures.Count) required check(s) failed."
    exit 1
}

Write-Host ""
Write-Host "LOCAL AI VERIFICATION PASS"
exit 0
