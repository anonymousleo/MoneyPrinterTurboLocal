# Windows Installation — MoneyPrinterTurbo-LocalAI

## Quick start

```bat
INSTALL.bat
VERIFY.bat
START.bat
```

`INSTALL.bat` creates a project-local runtime. End users do not need Anaconda
or an existing Python installation.

## What INSTALL.bat does

1. Detects the Windows system proxy and applies it to downloads while excluding
   localhost services.
2. Installs project-local `uv` under `.tools\uv`.
3. Uses `uv` to install managed Python 3.11.
4. Creates `.venv` from the checked-in `uv.lock`.
5. Creates `config.toml` from `config.example.toml` if necessary.
6. Checks/installs FFmpeg.
7. Checks/installs Ollama.
8. Uses `<repo>\models` as the default model root.

## Portable model root

Override it before launching if desired:

```bat
set MPT_LOCAL_MODELS_DIR=E:\AI\Models
START.bat
```

## China / proxy environments

The launcher reads the current user's Windows Internet Settings proxy and sets
`HTTP_PROXY` / `HTTPS_PROXY` for the launched process. Local services remain
excluded through `NO_PROXY`.

No fixed Clash port is embedded in the release.
