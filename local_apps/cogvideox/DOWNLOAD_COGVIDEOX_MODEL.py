from __future__ import annotations

import os
from pathlib import Path
from local_paths import COGVIDEOX_MODEL_DIR, HF_HOME, HF_HUB_CACHE, HF_XET_CACHE

MODEL_ID = "zai-org/CogVideoX1.5-5B"
MODEL_DIR = COGVIDEOX_MODEL_DIR

os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
os.environ["HF_XET_CACHE"] = str(HF_XET_CACHE)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PYTHONUTF8"] = "1"

from huggingface_hub import snapshot_download

MODEL_DIR.mkdir(parents=True, exist_ok=True)
print("=" * 72)
print("COGVIDEOX1.5-5B MODEL DOWNLOAD")
print("=" * 72)
print("Repository :", MODEL_ID)
print("Destination:", MODEL_DIR)
print("The complete model is stored on D:.")

snapshot_download(
    repo_id=MODEL_ID,
    local_dir=str(MODEL_DIR),
)

if not (MODEL_DIR / "model_index.json").is_file():
    raise SystemExit("FAIL: model_index.json is missing after download")
print("MODEL_DOWNLOAD_PASS")
