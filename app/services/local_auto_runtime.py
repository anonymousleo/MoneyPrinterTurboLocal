from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from app.services.local_paths import HF_HOME, HF_HUB_CACHE, OLLAMA_MODELS_DIR
from typing import Any

import requests
from loguru import logger
from app.config import config

VERSION = "0.2.0"
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_OPENAI_URL = f"{OLLAMA_URL}/v1"
OLLAMA_MODEL_DEFAULT = "qwen3:8b"
CHATTERBOX_URL = "http://127.0.0.1:4123"
CHATTERBOX_OPENAI_URL = f"{CHATTERBOX_URL}/v1"
CHATTERBOX_READY_TIMEOUT = 240
LOCALAI_URL = "http://127.0.0.1:8081"
LOCALAI_OPENAI_URL = f"{LOCALAI_URL}/v1"
LOCALAI_MODEL_DEFAULT = "dreamshaper-native"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHATTERBOX_ROOT = PROJECT_ROOT / "local_apps" / "chatterbox-tts-api"
CHATTERBOX_PYTHON = CHATTERBOX_ROOT / ".venv" / "Scripts" / "python.exe"
CHATTERBOX_MAIN = CHATTERBOX_ROOT / "main.py"
WHISPER_MEDIUM = PROJECT_ROOT / "models" / "whisper-medium"

_lock = threading.RLock()
_chatterbox_process: subprocess.Popen | None = None
_last_localai_release = 0.0


class LocalAutomaticError(RuntimeError):
    pass


def is_enabled() -> bool:
    value = config.app.get("local_auto_enabled", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _set_no_proxy() -> None:
    required = ["127.0.0.1", "localhost", "host.docker.internal"]
    for key in ("NO_PROXY", "no_proxy"):
        existing = [x.strip() for x in os.environ.get(key, "").split(",") if x.strip()]
        for item in required:
            if item not in existing:
                existing.append(item)
        os.environ[key] = ",".join(existing)


_set_no_proxy()


def _run(cmd, *, cwd=None, check=False, timeout=None):
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        timeout=timeout,
    )


def _get_json(url: str, timeout: float = 3.0):
    try:
        response = requests.get(url, timeout=timeout)
        if response.ok:
            return response.json()
    except Exception:
        pass
    return None


def _wait_until(predicate, timeout: float, interval: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def find_ollama() -> str:
    found = shutil.which("ollama")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise LocalAutomaticError("ollama.exe was not found")


def ollama_ready() -> bool:
    return isinstance(_get_json(f"{OLLAMA_URL}/api/tags", timeout=1.5), dict)


def ensure_ollama() -> None:
    if not is_enabled():
        return
    with _lock:
        _set_no_proxy()
        if ollama_ready():
            return
        exe = find_ollama()
        env = os.environ.copy()
        env.setdefault("OLLAMA_MODELS", str(OLLAMA_MODELS_DIR))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        logger.info("Local Automatic: starting Ollama")
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            creationflags=flags,
        )
        if not _wait_until(ollama_ready, 60, 1):
            raise LocalAutomaticError("Ollama did not become ready on 127.0.0.1:11434")


def release_ollama() -> None:
    if not is_enabled():
        return
    try:
        model = str(config.app.get("ollama_model_name") or OLLAMA_MODEL_DEFAULT)
        _run([find_ollama(), "stop", model], timeout=20)
        logger.info(f"Local Automatic: released Ollama model {model}")
    except Exception as exc:
        logger.warning(f"Local Automatic: could not release Ollama model: {exc}")


def docker_ready() -> bool:
    try:
        return _run(["docker", "info"], timeout=10).returncode == 0
    except Exception:
        return False


def ensure_docker() -> None:
    if docker_ready():
        return
    docker_desktop = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
    if docker_desktop.is_file():
        logger.info("Local Automatic: starting Docker Desktop")
        subprocess.Popen([str(docker_desktop)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if _wait_until(docker_ready, 150, 3):
            return
    raise LocalAutomaticError("Docker Desktop is not ready")


def localai_ready() -> bool:
    data = _get_json(f"{LOCALAI_URL}/v1/models", timeout=2.0)
    return isinstance(data, dict) and isinstance(data.get("data"), list)


def ensure_localai() -> None:
    if not is_enabled():
        return
    with _lock:
        release_ollama()
        stop_chatterbox()
        _set_no_proxy()
        if not localai_ready():
            ensure_docker()
            result = _run(["docker", "start", "local-ai"], timeout=30)
            if result.returncode != 0:
                raise LocalAutomaticError(
                    "Could not start LocalAI container 'local-ai': " + (result.stdout or "").strip()
                )
            if not _wait_until(localai_ready, 120, 2):
                raise LocalAutomaticError("LocalAI did not become ready on 127.0.0.1:8081")
        models = _get_json(f"{LOCALAI_URL}/v1/models", timeout=5) or {}
        ids = {
            str(item.get("id"))
            for item in models.get("data", [])
            if isinstance(item, dict) and item.get("id")
        }
        wanted = str(config.app.get("openai_image_model") or LOCALAI_MODEL_DEFAULT)
        if wanted not in ids:
            raise LocalAutomaticError(f"LocalAI is running but model '{wanted}' is not registered")


def release_localai_gpu() -> None:
    global _last_localai_release
    if not is_enabled() or not docker_ready():
        return
    # Avoid restarting LocalAI twice when the material-stage handoff is followed
    # immediately by the task-level finally cleanup.
    if time.time() - _last_localai_release < 30:
        return
    try:
        inspect = _run(["docker", "inspect", "-f", "{{.State.Running}}", "local-ai"], timeout=10)
        if inspect.returncode != 0:
            return
        if (inspect.stdout or "").strip().lower() != "true":
            return
        logger.info("Local Automatic: releasing LocalAI GPU state")
        _run(["docker", "restart", "local-ai"], timeout=60)
        _wait_until(localai_ready, 120, 2)
        _last_localai_release = time.time()
    except Exception as exc:
        logger.warning(f"Local Automatic: could not release LocalAI GPU state: {exc}")


def _listener_pids(port: int) -> set[int]:
    if os.name != "nt":
        return set()
    try:
        result = _run(["netstat", "-ano"], timeout=10)
    except Exception:
        return set()
    pids: set[int] = set()
    needle = f":{port}"
    for line in (result.stdout or "").splitlines():
        if needle in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(int(parts[-1]))
    return pids


def _kill_listener(port: int) -> None:
    if os.name != "nt":
        return
    for pid in _listener_pids(port):
        try:
            _run(["taskkill", "/PID", str(pid), "/F"], timeout=15)
        except Exception:
            pass


def chatterbox_health() -> dict:
    data = _get_json(f"{CHATTERBOX_URL}/health", timeout=2.0)
    return data if isinstance(data, dict) else {}


def chatterbox_model_loaded() -> bool:
    return chatterbox_health().get("model_loaded") is True


def _chatterbox_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HF_HOME"] = str(HF_HOME)
    env["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    env.pop("HF_HUB_OFFLINE", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_PROXY"] = os.environ.get("NO_PROXY", "127.0.0.1,localhost")
    env["no_proxy"] = os.environ.get("no_proxy", "127.0.0.1,localhost")
    return env


def ensure_chatterbox_ready(timeout: int = CHATTERBOX_READY_TIMEOUT) -> None:
    global _chatterbox_process
    if not is_enabled():
        return
    with _lock:
        release_ollama()
        release_localai_gpu()
        _set_no_proxy()
        if chatterbox_model_loaded():
            return
        if chatterbox_health():
            if _wait_until(chatterbox_model_loaded, min(30, timeout), 2):
                return
            _kill_listener(4123)
        if not CHATTERBOX_PYTHON.is_file() or not CHATTERBOX_MAIN.is_file():
            raise LocalAutomaticError("Chatterbox local app or its verified .venv is missing")
        logger.info("Local Automatic: starting Chatterbox CUDA server")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _chatterbox_process = subprocess.Popen(
            [str(CHATTERBOX_PYTHON), str(CHATTERBOX_MAIN)],
            cwd=str(CHATTERBOX_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_chatterbox_env(),
            creationflags=flags,
        )
        if not _wait_until(chatterbox_model_loaded, timeout, 2):
            stop_chatterbox()
            raise LocalAutomaticError(
                "Chatterbox HTTP server started but model_loaded never became true"
            )
        time.sleep(1.0)


def stop_chatterbox() -> None:
    global _chatterbox_process
    if not is_enabled():
        return
    proc = _chatterbox_process
    _chatterbox_process = None
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    _kill_listener(4123)
    logger.info("Local Automatic: Chatterbox stopped/released")


_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2300, 0x23FF))


def _is_emoji_like(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in _EMOJI_RANGES)


def sanitize_spoken_text(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    cleaned: list[str] = []
    for ch in text:
        if _is_emoji_like(ch):
            continue
        category = unicodedata.category(ch)
        if category in {"Cc", "Cf", "Cs", "Co", "Cn"}:
            if ch in "\n\t":
                cleaned.append(ch)
            continue
        if category == "So":
            continue
        cleaned.append(ch)
    value = "".join(cleaned)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def cleanup_transient_gpu_services() -> None:
    if not is_enabled():
        return
    try:
        release_ollama()
    finally:
        try:
            stop_chatterbox()
        finally:
            release_localai_gpu()


def apply_verified_local_preset() -> None:
    config.app["local_auto_enabled"] = True
    config.app["llm_provider"] = "ollama"
    config.app["ollama_base_url"] = OLLAMA_OPENAI_URL
    config.app["ollama_model_name"] = OLLAMA_MODEL_DEFAULT
    config.app["video_source"] = "openai_image"
    config.app["openai_image_base_url"] = LOCALAI_OPENAI_URL
    config.app["openai_image_model"] = LOCALAI_MODEL_DEFAULT
    config.app["openai_image_size"] = "512x512"
    config.app["openai_image_prompt_template"] = (
        "{term}, cinematic realistic photography, highly detailed, no text, no logo, no watermark"
    )
    config.app["subtitle_provider"] = "whisper"
    config.chatterbox["base_url"] = CHATTERBOX_OPENAI_URL
    config.chatterbox["api_key"] = ""
    config.chatterbox["model_id"] = "chatterbox-tts-1"
    config.chatterbox["voices"] = ["alloy"]
    config.ui["voice_mode"] = "tts"
    config.ui["tts_server"] = "chatterbox"
    config.ui["voice_name"] = "chatterbox:alloy"
    config.whisper["model_size"] = "medium"
    config.whisper["device"] = "cpu"
    config.whisper["compute_type"] = "int8"
    config.save_config()


def quick_health() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "ollama": ollama_ready(),
        "localai": localai_ready(),
        "chatterbox_installed": CHATTERBOX_PYTHON.is_file() and CHATTERBOX_MAIN.is_file(),
        "chatterbox_loaded": chatterbox_model_loaded(),
        "whisper": WHISPER_MEDIUM.is_dir(),
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }
