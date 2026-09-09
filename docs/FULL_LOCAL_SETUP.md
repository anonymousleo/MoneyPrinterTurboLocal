# Fully Local AI Setup

After `INSTALL.bat` and `VERIFY.bat` pass, install the local AI payloads.

## Core profile

```bat
SETUP_LOCAL_AI.bat -Profile Core
VERIFY_LOCAL_AI.bat
```

Core installs/prepares:

- Ollama `qwen3:8b`
- `Systran/faster-whisper-medium`
- Chatterbox TTS API with its own isolated CUDA environment

## Full profile

```bat
SETUP_LOCAL_AI.bat -Profile Full
VERIFY_LOCAL_AI.bat
```

Full adds CogVideoX1.5-5B. The model is approximately 31 GB, so it remains
explicitly optional.

## Why separate environments?

Chatterbox and CogVideoX have heavy and partly conflicting CUDA/PyTorch
dependency stacks. Keeping them isolated prevents their dependencies from
destabilizing MoneyPrinterTurbo's main `.venv`.

## Model weights

No model weights are committed to Git. Runtime downloads live in ignored local
directories and are governed by their upstream licenses.
