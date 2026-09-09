Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-MptRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Add-PathEntry {
    param([Parameter(Mandatory=$true)][string]$PathEntry)
    if (-not (Test-Path $PathEntry)) { return }
    $parts = @($env:PATH -split ";" | Where-Object { $_ })
    if ($parts -notcontains $PathEntry) {
        $env:PATH = "$PathEntry;$env:PATH"
    }
}

function Get-WindowsProxyUrl {
    try {
        $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        $cfg = Get-ItemProperty -Path $key -ErrorAction Stop
        if ([int]$cfg.ProxyEnable -ne 1) { return $null }
        $raw = [string]$cfg.ProxyServer
        if ([string]::IsNullOrWhiteSpace($raw)) { return $null }

        if ($raw.Contains("=")) {
            $pairs = @{}
            foreach ($entry in $raw.Split(";")) {
                if (-not $entry.Contains("=")) { continue }
                $kv = $entry.Split("=", 2)
                $pairs[$kv[0].Trim().ToLowerInvariant()] = $kv[1].Trim()
            }
            if ($pairs.ContainsKey("https")) { $raw = $pairs["https"] }
            elseif ($pairs.ContainsKey("http")) { $raw = $pairs["http"] }
            else { return $null }
        }

        if ($raw -notmatch "^[a-zA-Z]+://") {
            $raw = "http://$raw"
        }
        return $raw
    }
    catch {
        return $null
    }
}

function Set-MptRuntimeEnvironment {
    param([Parameter(Mandatory=$true)][string]$RepoRoot)

    $modelRoot = if ($env:MPT_LOCAL_MODELS_DIR) {
        $env:MPT_LOCAL_MODELS_DIR
    } else {
        Join-Path $RepoRoot "models"
    }

    $env:MPT_LOCAL_MODELS_DIR = $modelRoot
    if (-not $env:MPT_HF_HOME -and -not $env:HF_HOME) {
        $env:MPT_HF_HOME = Join-Path $modelRoot "HuggingFace"
    }
    if (-not $env:OLLAMA_MODELS) {
        $env:OLLAMA_MODELS = Join-Path $modelRoot "Ollama"
    }
    if (-not $env:MPT_COGVIDEOX_MODEL_DIR) {
        $env:MPT_COGVIDEOX_MODEL_DIR = Join-Path $modelRoot "CogVideoX\CogVideoX1.5-5B"
    }

    New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null

    $proxy = Get-WindowsProxyUrl
    if ($proxy) {
        if (-not $env:HTTP_PROXY)  { $env:HTTP_PROXY = $proxy }
        if (-not $env:HTTPS_PROXY) { $env:HTTPS_PROXY = $proxy }
        if (-not $env:http_proxy)  { $env:http_proxy = $proxy }
        if (-not $env:https_proxy) { $env:https_proxy = $proxy }
    }

    $localNoProxy = "127.0.0.1,localhost,host.docker.internal"
    if (-not $env:NO_PROXY) { $env:NO_PROXY = $localNoProxy }
    if (-not $env:no_proxy) { $env:no_proxy = $localNoProxy }

    $uvDir = Join-Path $RepoRoot ".tools\uv"
    Add-PathEntry $uvDir
    Add-PathEntry (Join-Path $env:LOCALAPPDATA "Programs\Ollama")
    Add-PathEntry (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
}

function Find-Executable {
    param([Parameter(Mandatory=$true)][string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host $Text
    Write-Host ("=" * 72)
}
