from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from app.services.local_paths import COGVIDEOX_MODEL_DIR, HF_HOME, HF_HUB_CACHE

from loguru import logger

from app.config import config
from app.utils import utils

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_ROOT = PROJECT_ROOT / "local_apps" / "cogvideox"
DEFAULT_PYTHON = WORKER_ROOT / ".venv" / "Scripts" / "python.exe"
DEFAULT_WORKER = WORKER_ROOT / "cogvideox_worker.py"
DEFAULT_MODEL_DIR = COGVIDEOX_MODEL_DIR


class CogVideoXLocalError(RuntimeError):
    pass


def _cfg(name: str, default):
    return config.app.get(name, default)


def _run_quiet(cmd, timeout=60):
    try:
        return subprocess.run(
            [str(x) for x in cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )
    except Exception:
        return None


def _kill_port_listener(port: int) -> None:
    if os.name != "nt":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
        )
        pids = set()
        needle = f":{port}"
        for line in result.stdout.splitlines():
            if needle in line and "LISTENING" in line.upper():
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pids.add(parts[-1])
        for pid in pids:
            _run_quiet(["taskkill", "/PID", pid, "/F"], timeout=15)
    except Exception:
        pass


def _release_other_gpu_models() -> None:
    """Leave as much of the 8 GB GPU free as possible before CogVideoX starts."""
    # Reuse the full local runtime manager when installed.
    try:
        from app.services import local_auto_runtime

        if local_auto_runtime.is_enabled():
            local_auto_runtime.release_ollama()
            local_auto_runtime.stop_chatterbox()
            local_auto_runtime.release_localai_gpu()
            return
    except Exception as exc:
        logger.warning(f"CogVideoX: Local Automatic release hook unavailable: {exc}")

    # Standalone fallback for installations that only have the CogVideoX add-on.
    ollama = shutil.which("ollama")
    if ollama:
        _run_quiet(
            [ollama, "stop", str(_cfg("ollama_model_name", "qwen3:8b"))],
            timeout=30,
        )
    _kill_port_listener(4123)

    # Restarting the known LocalAI container unloads DreamShaper from VRAM while
    # preserving its D:-backed model files and backend installation.
    if shutil.which("docker"):
        try:
            inspect = subprocess.run(
                ["docker", "inspect", "local-ai"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            )
            if inspect.returncode == 0:
                _run_quiet(["docker", "restart", "local-ai"], timeout=90)
        except Exception:
            pass


def _aspect_name(video_aspect) -> str:
    value = str(getattr(video_aspect, "value", video_aspect) or "").lower()
    if "9:16" in value or "portrait" in value:
        return "portrait"
    if "1:1" in value or "square" in value:
        return "square"
    return "landscape"


def status() -> dict:
    python_path = Path(str(_cfg("cogvideox_python", DEFAULT_PYTHON)))
    worker_path = Path(str(_cfg("cogvideox_worker", DEFAULT_WORKER)))
    model_dir = Path(str(_cfg("cogvideox_model_dir", DEFAULT_MODEL_DIR)))
    return {
        "python": str(python_path),
        "python_ok": python_path.is_file(),
        "worker": str(worker_path),
        "worker_ok": worker_path.is_file(),
        "model_dir": str(model_dir),
        "model_ok": (model_dir / "model_index.json").is_file(),
    }


def generate_videos(
    *,
    task_id: str,
    search_terms: list[str],
    video_aspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str = "",
) -> list[str]:
    if not bool(_cfg("cogvideox_local_enabled", True)):
        raise CogVideoXLocalError("CogVideoX Local is disabled")

    python_path = Path(str(_cfg("cogvideox_python", DEFAULT_PYTHON)))
    worker_path = Path(str(_cfg("cogvideox_worker", DEFAULT_WORKER)))
    model_dir = Path(str(_cfg("cogvideox_model_dir", DEFAULT_MODEL_DIR)))

    if not python_path.is_file():
        raise CogVideoXLocalError(
            f"CogVideoX runtime missing: {python_path}. Run SETUP_COGVIDEOX_LOCAL.bat."
        )
    if not worker_path.is_file():
        raise CogVideoXLocalError(f"CogVideoX worker missing: {worker_path}")
    if not (model_dir / "model_index.json").is_file():
        raise CogVideoXLocalError(
            f"CogVideoX model missing: {model_dir}. Run DOWNLOAD_COGVIDEOX_MODEL.bat."
        )

    terms = [str(x).strip() for x in (search_terms or []) if str(x).strip()]
    if not terms:
        raise CogVideoXLocalError("No scene prompts were supplied")

    fps = int(_cfg("cogvideox_fps", 8))
    frames = int(_cfg("cogvideox_num_frames", 33))
    frames = max(17, min(frames, 161))
    frames = ((frames - 1) // 16) * 16 + 1
    generated_seconds = max((frames - 1) / max(fps, 1), 1.0)
    usable_seconds = min(max(float(max_clip_duration), 1.0), generated_seconds)
    scene_count = max(1, int(math.ceil(max(float(audio_duration), usable_seconds) / usable_seconds)))
    scene_count = min(scene_count, int(_cfg("cogvideox_max_scenes", 6)))

    selected_terms = [terms[i % len(terms)] for i in range(scene_count)]
    output_root = Path(material_directory) if material_directory else Path(utils.task_dir(task_id))
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = [output_root / f"cogvideox-{i:02d}.mp4" for i in range(1, scene_count + 1)]

    prompts = [
        (
            f"{term}. Cinematic realistic video, natural coherent motion, realistic lighting, "
            "detailed environment, smooth camera movement, professional cinematography, "
            "no text, no subtitles, no logos, no watermark."
        )
        for term in selected_terms
    ]

    request = {
        "model_dir": str(model_dir),
        "prompts": prompts,
        "outputs": [str(path) for path in outputs],
        "aspect": _aspect_name(video_aspect),
        "num_frames": frames,
        "fps": fps,
        "num_inference_steps": int(_cfg("cogvideox_steps", 20)),
        "guidance_scale": float(_cfg("cogvideox_guidance_scale", 6.0)),
        "seed": int(_cfg("cogvideox_seed", 42)),
        "sequential_cpu_offload": bool(_cfg("cogvideox_sequential_cpu_offload", True)),
        "int8": bool(_cfg("cogvideox_int8", True)),
        "oom_retry_shorter": bool(_cfg("cogvideox_oom_retry_shorter", True)),
    }

    request_file = output_root / "cogvideox-request.json"
    log_file = output_root / "cogvideox-worker.log"
    request_file.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")

    _release_other_gpu_models()

    env = os.environ.copy()
    env["HF_HOME"] = str(HF_HOME)
    env["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    timeout = int(_cfg("cogvideox_timeout_seconds", 14400))
    logger.info(
        f"CogVideoX Local: scenes={scene_count} frames={frames} "
        f"steps={request['num_inference_steps']} aspect={request['aspect']}"
    )

    try:
        result = subprocess.run(
            [str(python_path), str(worker_path), "--request", str(request_file)],
            cwd=str(worker_path.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CogVideoXLocalError(f"CogVideoX exceeded timeout {timeout}s") from exc

    log_file.write_text(result.stdout or "", encoding="utf-8")
    if result.returncode != 0:
        tail = "\n".join((result.stdout or "").splitlines()[-30:])
        raise CogVideoXLocalError(
            f"CogVideoX worker failed. Log: {log_file}\nLast output:\n{tail}"
        )

    missing = [str(p) for p in outputs if not p.is_file() or p.stat().st_size < 10000]
    if missing:
        raise CogVideoXLocalError("Invalid/missing CogVideoX outputs: " + ", ".join(missing))

    logger.success(f"CogVideoX Local generated {len(outputs)} material clips")
    return [str(path) for path in outputs]
