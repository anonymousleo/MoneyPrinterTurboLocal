param(
    [ValidateSet("Core","Full")]
    [string]$Profile = "Core"
)

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-MptRepoRoot
Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
Set-Location $RepoRoot

$UvExe = Join-Path $RepoRoot ".tools\uv\uv.exe"
$RootPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Manifest = Join-Path $RepoRoot "local_ai_manifest.json"
$ProvenanceDir = Join-Path $RepoRoot ".runtime\provenance"

if (-not (Test-Path $UvExe)) { throw "Project-local uv missing. Run INSTALL.bat first." }
if (-not (Test-Path $RootPython)) { throw "Project .venv missing. Run INSTALL.bat first." }
if (-not (Test-Path $Manifest)) { throw "local_ai_manifest.json missing." }

New-Item -ItemType Directory -Force -Path $ProvenanceDir | Out-Null
$cfg = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json

function Wait-Http {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$Attempts = 30,
        [int]$DelaySeconds = 1
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            Invoke-RestMethod -Uri $Url -TimeoutSec 2 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    return $false
}

Write-Step "1. Ollama / Qwen3:8B"
$ollama = Find-Executable "ollama.exe"
if (-not $ollama) { throw "Ollama not found. Run INSTALL.bat first." }

$ollamaReady = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
    $ollamaReady = $true
}
catch {}

if (-not $ollamaReady) {
    Write-Host "Starting Ollama service for setup..."
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    if (-not (Wait-Http -Url "http://127.0.0.1:11434/api/tags")) {
        throw "Ollama service did not become ready."
    }
}

& $ollama pull ([string]$cfg.qwen.model)
if ($LASTEXITCODE -ne 0) { throw "Ollama pull failed." }

& $ollama show ([string]$cfg.qwen.model) | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Ollama model verification failed." }
Write-Host "[PASS] Qwen model available: $($cfg.qwen.model)"

Write-Step "2. Faster-Whisper medium"
$WhisperDir = Join-Path $RepoRoot ([string]$cfg.whisper.local_dir)
New-Item -ItemType Directory -Force -Path $WhisperDir | Out-Null

$env:MPT_WHISPER_REPO = [string]$cfg.whisper.repo
$env:MPT_WHISPER_REV = [string]$cfg.whisper.revision
$env:MPT_WHISPER_DIR = $WhisperDir

$WhisperPython = 'import os; from pathlib import Path; from huggingface_hub import snapshot_download; repo=os.environ["MPT_WHISPER_REPO"]; rev=os.environ["MPT_WHISPER_REV"]; dest=Path(os.environ["MPT_WHISPER_DIR"]); snapshot_download(repo_id=repo, revision=rev, local_dir=str(dest)); req=["model.bin","config.json","tokenizer.json"]; missing=[x for x in req if not (dest/x).exists()]; print("WHISPER", dest, "missing", missing); raise SystemExit(1 if missing else 0)'
& $RootPython -c $WhisperPython
if ($LASTEXITCODE -ne 0) { throw "Whisper model setup failed." }
Write-Host "[PASS] Faster-Whisper medium"

Write-Step "3. Chatterbox TTS API"
$ChatterDir = Join-Path $RepoRoot "local_apps\chatterbox-tts-api"
$ChatterTmp = Join-Path $env:TEMP ("mpt-chatterbox-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $ChatterTmp | Out-Null

try {
    $commitInfo = Invoke-RestMethod `
        -Uri "https://api.github.com/repos/travisvn/chatterbox-tts-api/commits/main" `
        -Headers @{ "User-Agent" = "MoneyPrinterTurbo-LocalAI" } `
        -TimeoutSec 60

    $sha = [string]$commitInfo.sha
    if ([string]::IsNullOrWhiteSpace($sha)) {
        throw "Could not resolve Chatterbox source revision."
    }

    $zip = Join-Path $ChatterTmp "source.zip"
    $extract = Join-Path $ChatterTmp "extract"
    $url = "https://github.com/travisvn/chatterbox-tts-api/archive/$sha.zip"

    Write-Host "Resolved Chatterbox revision: $sha"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force

    $sourceRoot = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
    if (-not $sourceRoot) { throw "Chatterbox archive root not found." }

    if (Test-Path $ChatterDir) {
        Remove-Item -LiteralPath $ChatterDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $ChatterDir) | Out-Null
    Move-Item -LiteralPath $sourceRoot.FullName -Destination $ChatterDir
    Set-Content -LiteralPath (Join-Path $ChatterDir ".source-revision") -Value $sha -Encoding ASCII

    Push-Location $ChatterDir
    try {
        & $UvExe sync --python 3.11
        if ($LASTEXITCODE -ne 0) { throw "Chatterbox uv sync failed." }

        $ChatterPython = Join-Path $ChatterDir ".venv\Scripts\python.exe"
        if (-not (Test-Path $ChatterPython)) {
            throw "Chatterbox .venv was not created."
        }

        & $UvExe pip install --python $ChatterPython --reinstall `
            torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 `
            --index-url https://download.pytorch.org/whl/cu124
        if ($LASTEXITCODE -ne 0) {
            throw "Chatterbox CUDA Torch installation failed."
        }

        $EnvLines = @(
            "DEVICE=cuda",
            "PORT=4123",
            "MODEL_CACHE_DIR=./models",
            "MAX_CHUNK_LENGTH=200",
            "MEMORY_CLEANUP_INTERVAL=3",
            "CUDA_CACHE_CLEAR_INTERVAL=1",
            "USE_MULTILINGUAL_MODEL=true"
        )
        Set-Content -LiteralPath (Join-Path $ChatterDir ".env") -Value $EnvLines -Encoding ASCII

        $ChatterCheck = 'import torch; print("CHATTERBOX TORCH", torch.__version__, "CUDA", torch.cuda.is_available()); raise SystemExit(0 if torch.cuda.is_available() else 1)'
        & $ChatterPython -c $ChatterCheck
        if ($LASTEXITCODE -ne 0) {
            throw "Chatterbox CUDA verification failed."
        }
    }
    finally {
        Pop-Location
    }

    @{
        repository = "travisvn/chatterbox-tts-api"
        revision = $sha
        resolved_at = (Get-Date).ToString("o")
        license = "AGPL-3.0"
    } | ConvertTo-Json | Set-Content `
        -LiteralPath (Join-Path $ProvenanceDir "chatterbox.json") `
        -Encoding UTF8

    Write-Host "[PASS] Chatterbox runtime prepared"
}
finally {
    if (Test-Path $ChatterTmp) {
        Remove-Item -LiteralPath $ChatterTmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($Profile -eq "Full") {
    Write-Step "4. CogVideoX1.5-5B Full profile"

    $CogDir = Join-Path $RepoRoot "local_apps\cogvideox"
    $CogVenv = Join-Path $CogDir ".venv"
    $CogPython = Join-Path $CogVenv "Scripts\python.exe"

    if (-not (Test-Path $CogPython)) {
        & $UvExe venv --python 3.11 $CogVenv
        if ($LASTEXITCODE -ne 0) { throw "CogVideoX venv creation failed." }
    }

    & $UvExe pip install --python $CogPython `
        "diffusers==0.35.2" `
        "transformers==4.57.6" `
        "accelerate==1.14.0" `
        "torchao==0.12.0" `
        "imageio==2.37.4" `
        "imageio-ffmpeg==0.6.0" `
        "huggingface-hub==0.36.0" `
        "hf-xet==1.6.0" `
        "sentencepiece>=0.2.0" `
        "safetensors>=0.4.0"

    if ($LASTEXITCODE -ne 0) {
        throw "CogVideoX dependency installation failed."
    }

    & $UvExe pip install --python $CogPython --reinstall `
        torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 `
        --index-url https://download.pytorch.org/whl/cu124

    if ($LASTEXITCODE -ne 0) {
        throw "CogVideoX CUDA Torch installation failed."
    }

    $env:MPT_COGVIDEOX_REVISION = [string]$cfg.cogvideox.revision

    & $CogPython (Join-Path $CogDir "DOWNLOAD_COGVIDEOX_MODEL.py")
    if ($LASTEXITCODE -ne 0) {
        throw "CogVideoX model download failed."
    }

    $CogCheck = 'import torch, diffusers, transformers, accelerate, torchao; print("COGVIDEOX ENV", torch.__version__, torch.cuda.is_available(), diffusers.__version__, transformers.__version__); raise SystemExit(0 if torch.cuda.is_available() else 1)'
    & $CogPython -c $CogCheck
    if ($LASTEXITCODE -ne 0) {
        throw "CogVideoX environment verification failed."
    }

    @{
        repository = [string]$cfg.cogvideox.repo
        revision = [string]$cfg.cogvideox.revision
        resolved_at = (Get-Date).ToString("o")
        license = [string]$cfg.cogvideox.license
    } | ConvertTo-Json | Set-Content `
        -LiteralPath (Join-Path $ProvenanceDir "cogvideox.json") `
        -Encoding UTF8

    Write-Host "[PASS] CogVideoX Full profile prepared"
}
else {
    Write-Step "4. CogVideoX skipped"
    Write-Host "Core profile selected."
    Write-Host "Run SETUP_LOCAL_AI.bat -Profile Full later for CogVideoX."
}

Write-Step "Local AI setup complete"
Write-Host "Profile       : $Profile"
Write-Host "Models root   : $env:MPT_LOCAL_MODELS_DIR"
Write-Host "Qwen          : $($cfg.qwen.model)"
Write-Host "Whisper       : $WhisperDir"
Write-Host "Chatterbox    : $ChatterDir"
Write-Host "Run VERIFY_LOCAL_AI.bat next."
