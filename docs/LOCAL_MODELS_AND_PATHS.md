# Local Models and Portable Paths

MoneyPrinterTurbo-LocalAI does not require fixed drive letters.

## Default model location

If no override is supplied, local assets are stored under:

```text
<MoneyPrinterTurbo-LocalAI>\models\
```

Typical layout:

```text
models\
├── HuggingFace\
├── Ollama\
└── CogVideoX\
    └── CogVideoX1.5-5B\
```

## Environment overrides

| Variable | Purpose |
|---|---|
| `MPT_LOCAL_MODELS_DIR` | Root directory for all local models |
| `MPT_HF_HOME` / `HF_HOME` | Hugging Face cache root |
| `HF_HUB_CACHE` | Hugging Face Hub cache |
| `HF_XET_CACHE` | Hugging Face Xet cache |
| `MPT_OLLAMA_MODELS_DIR` / `OLLAMA_MODELS` | Ollama model directory |
| `MPT_COGVIDEOX_MODEL_DIR` | Exact CogVideoX1.5-5B model directory |

Example:

```bat
set MPT_LOCAL_MODELS_DIR=%USERPROFILE%\MoneyPrinterTurbo-Models
```

Moving the application between drives should not require editing source code.
