from pathlib import Path
from local_paths import COGVIDEOX_MODEL_DIR, HF_HOME, HF_HUB_CACHE, HF_XET_CACHE

print("=" * 72)
print("COGVIDEOX LOCAL RUNTIME PREFLIGHT")
print("=" * 72)

import torch
print("Torch                 :", torch.__version__)
print("Torch CUDA            :", torch.version.cuda)
print("CUDA available        :", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("FAIL: CUDA unavailable")

props = torch.cuda.get_device_properties(0)
vram = props.total_memory / (1024**3)
print("GPU                   :", props.name)
print("VRAM GiB              :", f"{vram:.2f}")
if vram < 7.5:
    raise SystemExit("FAIL: less than 7.5 GiB physical VRAM")

import diffusers
import transformers
import accelerate
import torchao
print("diffusers             :", diffusers.__version__)
print("transformers          :", transformers.__version__)
print("accelerate            :", accelerate.__version__)
print("torchao               :", getattr(torchao, "__version__", "installed"))

from diffusers import AutoencoderKLCogVideoX, CogVideoXPipeline, CogVideoXTransformer3DModel
from transformers import T5EncoderModel
from torchao.quantization import int8_weight_only, quantize_
print("CogVideoX imports     : PASS")
print("TorchAO INT8 imports  : PASS")

model_dir = COGVIDEOX_MODEL_DIR
print("Model directory       :", model_dir)
print("Model downloaded      :", (model_dir / "model_index.json").is_file())
print("RUNTIME_PREFLIGHT_PASS")
