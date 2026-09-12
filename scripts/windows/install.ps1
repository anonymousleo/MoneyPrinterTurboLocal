param(
    [switch]$SkipOllama,
    [switch]$SkipFFmpeg,
    [ValidateSet("Prompt","Core","Full","Base")]
    [string]$LocalAIProfile = "Prompt"
)

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-MptRepoRoot
Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
Set-Location $RepoRoot

Write-Step "MoneyPrinterTurbo-LocalAI Windows Installer"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "This installer currently supports Windows only."
}

$ResolvedLocalAIProfile = $LocalAIProfile
if ($ResolvedLocalAIProfile -eq "Prompt") {
    Write-Step "Choose local AI installation profile"
    Write-Host "[1] Core Local"
    Write-Host "    Qwen3:8B + Faster-Whisper medium + Chatterbox TTS"
    Write-Host ""
    Write-Host "[2] Full Local Video"
    Write-Host "    Core Local + CogVideoX1.5-5B (~31 GB model download)"
    Write-Host "    Recommended for NVIDIA GPUs with at least 8 GB VRAM."
    Write-Host ""
    Write-Host "[3] Base environment only"
    Write-Host "    Install the application runtime now; local AI payloads can be added later."
    Write-Host ""

    while ($true) {
        $choice = Read-Host "Select profile [1]"
        if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

        switch ($choice.Trim().ToLowerInvariant()) {
            { $_ -in @("1","core","c") } {
                $ResolvedLocalAIProfile = "Core"
                break
            }
            { $_ -in @("2","full","f") } {
                $ResolvedLocalAIProfile = "Full"
                break
            }
            { $_ -in @("3","base","b") } {
                $ResolvedLocalAIProfile = "Base"
                break
            }
            default {
                Write-Host "Invalid choice. Enter 1, 2, or 3."
                continue
            }
        }
        break
    }
}

Write-Host "Selected profile: $ResolvedLocalAIProfile"

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot ".tools") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot ".runtime") | Out-Null
New-Item -ItemType Directory -Force -Path $env:MPT_LOCAL_MODELS_DIR | Out-Null

Write-Step "1. Installing project-local uv"
$UvDir = Join-Path $RepoRoot ".tools\uv"
$UvExe = Join-Path $UvDir "uv.exe"

if (-not (Test-Path $UvExe)) {
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    $oldInstallDir = $env:UV_INSTALL_DIR
    $oldNoModify = $env:UV_NO_MODIFY_PATH
    try {
        $env:UV_INSTALL_DIR = $UvDir
        $env:UV_NO_MODIFY_PATH = "1"
        $installer = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
        Invoke-Expression $installer
    }
    finally {
        $env:UV_INSTALL_DIR = $oldInstallDir
        $env:UV_NO_MODIFY_PATH = $oldNoModify
    }
}
if (-not (Test-Path $UvExe)) {
    throw "uv installation failed: $UvExe not found."
}
& $UvExe --version

Write-Step "2. Installing managed Python 3.11 and project environment"
& $UvExe python install 3.11
if ($LASTEXITCODE -ne 0) { throw "uv python install 3.11 failed." }

& $UvExe sync --frozen --python 3.11
if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Project Python environment was not created."
}
& $PythonExe --version

Write-Step "3. Creating local configuration"
$Config = Join-Path $RepoRoot "config.toml"
$ConfigExample = Join-Path $RepoRoot "config.example.toml"
if (-not (Test-Path $Config)) {
    Copy-Item $ConfigExample $Config
    Write-Host "Created config.toml from config.example.toml"
} else {
    Write-Host "Existing config.toml preserved."
}

if (-not $SkipFFmpeg) {
    Write-Step "4. Checking FFmpeg"
    $ffmpeg = Find-Executable "ffmpeg.exe"
    if (-not $ffmpeg) {
        $winget = Find-Executable "winget.exe"
        if (-not $winget) {
            Write-Warning "FFmpeg is missing and winget is unavailable. Install FFmpeg manually before video generation."
        } else {
            & $winget install --id Gyan.FFmpeg.Essentials -e --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Automatic FFmpeg installation failed. VERIFY.bat will report it."
            }
            Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
        }
    } else {
        Write-Host "FFmpeg found: $ffmpeg"
    }
}

if (-not $SkipOllama) {
    Write-Step "5. Checking Ollama"
    $ollama = Find-Executable "ollama.exe"
    if (-not $ollama) {
        $winget = Find-Executable "winget.exe"
        if ($winget) {
            & $winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "winget Ollama installation failed; trying official Ollama installer."
            }
        }
        Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
        $ollama = Find-Executable "ollama.exe"
        if (-not $ollama) {
            try {
                $installer = Invoke-RestMethod "https://ollama.com/install.ps1"
                Invoke-Expression $installer
            }
            catch {
                Write-Warning "Ollama automatic installation failed: $($_.Exception.Message)"
            }
            Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
        }
    }
    $ollama = Find-Executable "ollama.exe"
    if ($ollama) {
        Write-Host "Ollama found: $ollama"
    } else {
        Write-Warning "Ollama is not currently available. VERIFY.bat will report it."
    }
}

Write-Step "6. Base environment summary"
Write-Host "Repository     : $RepoRoot"
Write-Host "Python         : $PythonExe"
Write-Host "Models root    : $env:MPT_LOCAL_MODELS_DIR"
Write-Host "CogVideoX path : $env:MPT_COGVIDEOX_MODEL_DIR"
if ($env:HTTPS_PROXY) {
    Write-Host "Proxy detected : $env:HTTPS_PROXY"
} else {
    Write-Host "Proxy detected : none"
}

Write-Step "7. Local AI profile setup"
$ProfileMarker = Join-Path $RepoRoot ".runtime\local_ai_profile.txt"

if ($ResolvedLocalAIProfile -eq "Base") {
    Set-Content -LiteralPath $ProfileMarker -Value "Base" -Encoding ASCII
    Write-Host "Base environment selected."
    Write-Host "Local AI payload installation was intentionally skipped."
    Write-Host "You can install them later with:"
    Write-Host "  SETUP_LOCAL_AI.bat -Profile Core"
    Write-Host "or:"
    Write-Host "  SETUP_LOCAL_AI.bat -Profile Full"
}
else {
    $SetupScript = Join-Path $PSScriptRoot "setup_local_ai.ps1"
    if (-not (Test-Path $SetupScript)) {
        throw "Local AI setup script missing: $SetupScript"
    }

    Write-Host "Installing local AI profile: $ResolvedLocalAIProfile"
    & $SetupScript -Profile $ResolvedLocalAIProfile

    if (-not (Test-Path $ProfileMarker)) {
        throw "Local AI setup completed without creating the profile marker."
    }

    $RecordedProfile = (Get-Content -LiteralPath $ProfileMarker -Raw).Trim()
    if ($RecordedProfile -ne $ResolvedLocalAIProfile) {
        throw "Profile marker mismatch. Expected $ResolvedLocalAIProfile, found $RecordedProfile."
    }
}

Write-Step "8. Installation complete"
Write-Host "Selected profile : $ResolvedLocalAIProfile"
Write-Host "Repository       : $RepoRoot"
Write-Host "Models root      : $env:MPT_LOCAL_MODELS_DIR"
Write-Host ""
Write-Host "Run VERIFY.bat next."
Write-Host "Then run START.bat to launch the WebUI."
Write-Host ""
Write-Host "For unattended installation:"
Write-Host "  INSTALL.bat -LocalAIProfile Core"
Write-Host "  INSTALL.bat -LocalAIProfile Full"
Write-Host "  INSTALL.bat -LocalAIProfile Base"
