"""Portable local-AI storage paths for MoneyPrinterTurbo-LocalAI."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    raw = str(os.environ.get(name, "") or "").strip()
    return Path(raw).expanduser() if raw else default


LOCAL_MODELS_ROOT = _env_path("MPT_LOCAL_MODELS_DIR", PROJECT_ROOT / "models")
HF_HOME = _env_path(
    "HF_HOME",
    _env_path("MPT_HF_HOME", LOCAL_MODELS_ROOT / "HuggingFace"),
)
HF_HUB_CACHE = _env_path("HF_HUB_CACHE", HF_HOME / "hub")
HF_XET_CACHE = _env_path("HF_XET_CACHE", HF_HOME / "xet")
OLLAMA_MODELS_DIR = _env_path(
    "OLLAMA_MODELS",
    _env_path("MPT_OLLAMA_MODELS_DIR", LOCAL_MODELS_ROOT / "Ollama"),
)
COGVIDEOX_MODEL_DIR = _env_path(
    "MPT_COGVIDEOX_MODEL_DIR",
    LOCAL_MODELS_ROOT / "CogVideoX" / "CogVideoX1.5-5B",
)


def ensure_local_model_dirs() -> None:
    for path in (LOCAL_MODELS_ROOT, HF_HOME, HF_HUB_CACHE, HF_XET_CACHE):
        path.mkdir(parents=True, exist_ok=True)
