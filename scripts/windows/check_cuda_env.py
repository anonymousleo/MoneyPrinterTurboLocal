from __future__ import annotations

import argparse
import importlib


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--require", nargs="*", default=[])
    args = ap.parse_args()

    import torch

    print(f"{args.label}_TORCH={torch.__version__}")
    print(f"{args.label}_CUDA_AVAILABLE={torch.cuda.is_available()}")

    if not torch.cuda.is_available():
        raise SystemExit(f"{args.label}_CUDA_UNAVAILABLE")

    for module_name in args.require:
        module = importlib.import_module(module_name)
        version = getattr(module, "__version__", "unknown")
        print(f"{args.label}_{module_name.upper()}={version}")

    if torch.cuda.device_count() > 0:
        print(f"{args.label}_GPU={torch.cuda.get_device_name(0)}")
        props = torch.cuda.get_device_properties(0)
        print(f"{args.label}_VRAM_BYTES={props.total_memory}")

    print(f"{args.label}_CUDA_ENV_PASS")


if __name__ == "__main__":
    main()
