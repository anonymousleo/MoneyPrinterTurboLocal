param(
    [switch]$SkipOllama,
    [switch]$SkipFFmpeg
)

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-MptRepoRoot
Set-MptRuntimeEnvironment -RepoRoot $RepoRoot
Set-Location $RepoRoot

Write-Step "MoneyPrinterTurbo-LocalAI Windows Installer"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "This installer currently supports Windows only."
}

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

Write-Step "6. Installation summary"
Write-Host "Repository     : $RepoRoot"
Write-Host "Python         : $PythonExe"
Write-Host "Models root    : $env:MPT_LOCAL_MODELS_DIR"
Write-Host "CogVideoX path : $env:MPT_COGVIDEOX_MODEL_DIR"
if ($env:HTTPS_PROXY) {
    Write-Host "Proxy detected : $env:HTTPS_PROXY"
} else {
    Write-Host "Proxy detected : none"
}

Write-Host ""
Write-Host "Core Windows environment installation completed."
Write-Host "Run VERIFY.bat next."
Write-Host "Chatterbox and the optional CogVideoX model are installed in later setup stages."
