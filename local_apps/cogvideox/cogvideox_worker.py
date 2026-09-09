from __future__ import annotations

import argparse
import gc
import json
import os
import traceback
from pathlib import Path
from local_paths import COGVIDEOX_MODEL_DIR, HF_HOME, HF_HUB_CACHE, HF_XET_CACHE


def load_pipeline(model_dir: str, use_int8: bool, sequential_cpu_offload: bool):
    import torch
    from diffusers import (
        AutoencoderKLCogVideoX,
        CogVideoXPipeline,
        CogVideoXTransformer3DModel,
    )
    from transformers import T5EncoderModel

    dtype = torch.bfloat16
    kwargs = {"torch_dtype": dtype, "local_files_only": True}

    text_encoder = T5EncoderModel.from_pretrained(
        model_dir, subfolder="text_encoder", **kwargs
    )
    transformer = CogVideoXTransformer3DModel.from_pretrained(
        model_dir, subfolder="transformer", **kwargs
    )
    vae = AutoencoderKLCogVideoX.from_pretrained(
        model_dir, subfolder="vae", **kwargs
    )

    if use_int8:
        from torchao.quantization import int8_weight_only, quantize_

        quantize_(text_encoder, int8_weight_only())
        quantize_(transformer, int8_weight_only())
        quantize_(vae, int8_weight_only())

    pipe = CogVideoXPipeline.from_pretrained(
        model_dir,
        text_encoder=text_encoder,
        transformer=transformer,
        vae=vae,
        torch_dtype=dtype,
        local_files_only=True,
    )

    pipe.vae.enable_tiling()
    pipe.vae.enable_slicing()
    return pipe


def precompute_prompt_embeddings_cpu(pipe, prompts, guidance: float):
    import torch

    do_cfg = guidance > 1.0
    pairs = []
    print(
        f"CPU_T5_PRECOMPUTE_START scenes={len(prompts)} cfg={do_cfg}",
        flush=True,
    )

    pipe.text_encoder.eval()
    with torch.inference_mode():
        negative_cache = None
        if do_cfg:
            negative_cache, _ = pipe.encode_prompt(
                prompt="",
                negative_prompt=None,
                do_classifier_free_guidance=False,
                num_videos_per_prompt=1,
                device=torch.device("cpu"),
                dtype=torch.bfloat16,
            )
            negative_cache = negative_cache.detach().cpu()

        for index, prompt in enumerate(prompts, start=1):
            prompt_embeds, _ = pipe.encode_prompt(
                prompt=prompt,
                negative_prompt=None,
                do_classifier_free_guidance=False,
                num_videos_per_prompt=1,
                device=torch.device("cpu"),
                dtype=torch.bfloat16,
            )
            prompt_embeds = prompt_embeds.detach().cpu()
            negative_embeds = (
                negative_cache.clone() if negative_cache is not None else None
            )
            pairs.append((prompt_embeds, negative_embeds))
            print(
                f"CPU_T5_SCENE {index}/{len(prompts)} PASS "
                f"shape={tuple(prompt_embeds.shape)}",
                flush=True,
            )

    pipe.register_modules(text_encoder=None, tokenizer=None)
    gc.collect()
    torch.cuda.empty_cache()
    print("CPU_T5_RELEASED", flush=True)
    return pairs


def enable_video_offload(pipe, sequential_cpu_offload: bool):
    if sequential_cpu_offload:
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.enable_model_cpu_offload()
    print(
        "VIDEO_OFFLOAD_READY mode="
        + ("sequential" if sequential_cpu_offload else "model"),
        flush=True,
    )


def generate_one(
    pipe,
    prompt_embeds,
    negative_prompt_embeds,
    output: str,
    *,
    frames: int,
    fps: int,
    steps: int,
    guidance: float,
    seed: int,
):
    import torch
    from diffusers.utils import export_to_video

    generator = torch.Generator(device="cpu").manual_seed(seed)

    prompt_embeds_cuda = prompt_embeds.to(
        device="cuda", dtype=torch.bfloat16
    )
    negative_prompt_embeds_cuda = (
        negative_prompt_embeds.to(device="cuda", dtype=torch.bfloat16)
        if negative_prompt_embeds is not None
        else None
    )

    result = pipe(
        prompt=None,
        prompt_embeds=prompt_embeds_cuda,
        negative_prompt_embeds=negative_prompt_embeds_cuda,
        num_videos_per_prompt=1,
        num_inference_steps=steps,
        num_frames=frames,
        guidance_scale=guidance,
        generator=generator,
    )
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    export_to_video(result.frames[0], output, fps=fps)

    del prompt_embeds_cuda
    if negative_prompt_embeds_cuda is not None:
        del negative_prompt_embeds_cuda


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()

    req = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))

    os.environ.setdefault("HF_HOME", str(HF_HOME))
    os.environ.setdefault("HF_HUB_CACHE", str(HF_HUB_CACHE))
    os.environ.setdefault("PYTHONUTF8", "1")

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available in the CogVideoX runtime")

    props = torch.cuda.get_device_properties(0)
    total_gib = props.total_memory / (1024**3)
    print("=" * 72, flush=True)
    print("COGVIDEOX LOCAL WORKER", flush=True)
    print("=" * 72, flush=True)
    print(f"GPU={props.name}", flush=True)
    print(f"VRAM_TOTAL_GIB={total_gib:.2f}", flush=True)
    print(f"TORCH={torch.__version__}", flush=True)
    print(f"CUDA={torch.version.cuda}", flush=True)

    if total_gib < 7.5:
        raise RuntimeError(
            f"8GB-safe profile requires >=7.5 GiB physical VRAM; found {total_gib:.2f}"
        )

    frames = int(req.get("num_frames", 49))
    if (frames - 1) % 16 != 0:
        frames = ((frames - 1) // 16) * 16 + 1
    fps = int(req.get("fps", 8))
    steps = int(req.get("num_inference_steps", 20))
    guidance = float(req.get("guidance_scale", 6.0))
    seed = int(req.get("seed", 42))
    use_int8 = bool(req.get("int8", True))
    sequential = bool(req.get("sequential_cpu_offload", True))

    print(
        f"PROFILE frames={frames} fps={fps} steps={steps} "
        f"int8={use_int8} sequential_cpu_offload={sequential}",
        flush=True,
    )

    prompts = list(req["prompts"])
    outputs = list(req["outputs"])
    if len(prompts) != len(outputs):
        raise ValueError("prompts/outputs length mismatch")

    pipe = load_pipeline(
        str(req["model_dir"]),
        use_int8=use_int8,
        sequential_cpu_offload=sequential,
    )

    embedding_pairs = precompute_prompt_embeddings_cpu(
        pipe, prompts, guidance
    )

    if bool(req.get("cpu_t5_preflight_only", False)):
        del pipe
        gc.collect()
        torch.cuda.empty_cache()
        print("CPU_T5_PREFLIGHT_PASS", flush=True)
        return 0

    enable_video_offload(pipe, sequential)

    for index, ((prompt_embeds, negative_prompt_embeds), output) in enumerate(
        zip(embedding_pairs, outputs), start=1
    ):
        print(f"SCENE {index}/{len(prompts)} START", flush=True)
        current_frames = frames
        try:
            generate_one(
                pipe,
                prompt_embeds,
                negative_prompt_embeds,
                output,
                frames=current_frames,
                fps=fps,
                steps=steps,
                guidance=guidance,
                seed=seed + index - 1,
            )
        except torch.cuda.OutOfMemoryError:
            if not bool(req.get("oom_retry_shorter", True)) or current_frames <= 17:
                raise
            retry_frames = 33 if current_frames > 33 else 17
            print(f"CUDA_OOM: retrying scene with {retry_frames} frames", flush=True)
            gc.collect()
            torch.cuda.empty_cache()
            current_frames = retry_frames
            generate_one(
                pipe,
                prompt_embeds,
                negative_prompt_embeds,
                output,
                frames=current_frames,
                fps=fps,
                steps=steps,
                guidance=guidance,
                seed=seed + index - 1,
            )

        gc.collect()
        torch.cuda.empty_cache()
        allocated = torch.cuda.memory_allocated() / (1024**3)
        reserved = torch.cuda.memory_reserved() / (1024**3)
        print(
            f"SCENE {index}/{len(prompts)} PASS "
            f"allocated_gib={allocated:.2f} reserved_gib={reserved:.2f}",
            flush=True,
        )

    del pipe
    gc.collect()
    torch.cuda.empty_cache()
    print("COGVIDEOX_WORKER_PASS", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("COGVIDEOX_WORKER_FAIL", flush=True)
        raise SystemExit(1)
