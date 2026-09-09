"""Local model/runtime management for MoneyPrinterTurbo.

The WebUI uses this module to download open/local model assets without routing
through commercial inference APIs.  Network actions are deliberately limited to
well-known providers and validated identifiers; no user text is ever executed by
a shell.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from app.services.local_paths import HF_HOME, HF_HUB_CACHE
from typing import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests
from loguru import logger

from app.utils import utils


OLLAMA_MODEL_TAG_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)


@dataclass(frozen=True, slots=True)
class DownloadableModel:
    id: str
    name: str
    family: str
    runtime: str
    approx_size: str
    license_name: str
    source_url: str
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# Keep the default list intentionally small and curated.  Custom Ollama tags are
# also supported after strict validation, so users are not locked to this list.
OLLAMA_MODELS: tuple[DownloadableModel, ...] = (
    DownloadableModel(
        id="qwen3:4b",
        name="Qwen3 4B",
        family="LLM",
        runtime="ollama",
        approx_size="~2.5 GB",
        license_name="Apache-2.0",
        source_url="https://ollama.com/library/qwen3:4b",
        notes="Fast starter model for script/keyword generation.",
    ),
    DownloadableModel(
        id="qwen3:8b",
        name="Qwen3 8B",
        family="LLM",
        runtime="ollama",
        approx_size="~5.2 GB",
        license_name="Apache-2.0",
        source_url="https://ollama.com/library/qwen3:8b",
        notes="Recommended default balance of quality and VRAM.",
    ),
    DownloadableModel(
        id="qwen3:14b",
        name="Qwen3 14B",
        family="LLM",
        runtime="ollama",
        approx_size="~9.3 GB",
        license_name="Apache-2.0",
        source_url="https://ollama.com/library/qwen3:14b",
        notes="Higher script quality when sufficient RAM/VRAM is available.",
    ),
    DownloadableModel(
        id="deepseek-r1:8b",
        name="DeepSeek-R1 8B",
        family="LLM",
        runtime="ollama",
        approx_size="~5 GB",
        license_name="MIT / Apache-2.0 base",
        source_url="https://ollama.com/library/deepseek-r1:8b",
        notes="Reasoning-oriented alternative; may be slower for short scripts.",
    ),
)


WHISPER_MODELS: tuple[DownloadableModel, ...] = (
    DownloadableModel(
        id="small",
        name="faster-whisper Small",
        family="Speech-to-text",
        runtime="faster-whisper",
        approx_size="~0.5 GB",
        license_name="MIT model family / see model card",
        source_url="https://huggingface.co/Systran/faster-whisper-small",
        notes="Low-resource subtitle model.",
    ),
    DownloadableModel(
        id="medium",
        name="faster-whisper Medium",
        family="Speech-to-text",
        runtime="faster-whisper",
        approx_size="~1.5 GB",
        license_name="MIT model family / see model card",
        source_url="https://huggingface.co/Systran/faster-whisper-medium",
        notes="Good accuracy/resource compromise.",
    ),
    DownloadableModel(
        id="large-v3",
        name="faster-whisper Large v3",
        family="Speech-to-text",
        runtime="faster-whisper",
        approx_size="~3 GB",
        license_name="MIT model family / see model card",
        source_url="https://huggingface.co/Systran/faster-whisper-large-v3",
        notes="Recommended for highest subtitle accuracy.",
    ),
)


LOCALAI_IMAGE_MODELS: tuple[DownloadableModel, ...] = (
    DownloadableModel(
        id="z-image-turbo-diffusers",
        name="Z-Image-Turbo (Diffusers)",
        family="Text-to-image",
        runtime="localai",
        approx_size="~33 GB upstream; targets ~16 GB VRAM",
        license_name="Apache-2.0",
        source_url="https://huggingface.co/Tongyi-MAI/Z-Image-Turbo",
        notes=(
            "Current LocalAI gallery entry with a permissive upstream license; "
            "recommended default when commercial/monetized use matters."
        ),
    ),
    DownloadableModel(
        id="chroma1-hd",
        name="Chroma1-HD",
        family="Text-to-image",
        runtime="localai",
        approx_size="large (8.9B parameters)",
        license_name="Apache-2.0",
        source_url="https://huggingface.co/lodestones/Chroma1-HD",
        notes=(
            "Permissively licensed FLUX-derived foundation model currently listed "
            "in the LocalAI gallery."
        ),
    ),
    DownloadableModel(
        id="flux.1-dev-ggml",
        name="FLUX.1 dev (GGML)",
        family="Text-to-image",
        runtime="localai",
        approx_size="large; variant-dependent",
        license_name="FLUX.1-dev license — review before commercial use",
        source_url="https://localai.io/docs/features/image-generation/index.html",
        notes=(
            "Official LocalAI GGML image-generation example. Free to download, "
            "but the upstream model license can restrict commercial use."
        ),
    ),
)


CHATTERBOX_REPO_URL = "https://github.com/travisvn/chatterbox-tts-api.git"
CHATTERBOX_SOURCE_URL = "https://github.com/travisvn/chatterbox-tts-api"


class LocalModelError(RuntimeError):
    """Raised for a local runtime/model management failure."""


def project_root() -> Path:
    return Path(utils.root_dir()).resolve()


def local_apps_dir() -> Path:
    path = project_root() / "local_apps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chatterbox_install_dir() -> Path:
    return local_apps_dir() / "chatterbox-tts-api"


def models_dir() -> Path:
    path = project_root() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def whisper_model_dir(model_size: str) -> Path:
    return models_dir() / f"whisper-{model_size}"


def is_whisper_model_downloaded(model_size: str) -> bool:
    path = whisper_model_dir(model_size)
    return path.is_dir() and (path / "model.bin").is_file()


def validate_ollama_model_tag(model_tag: str) -> str:
    tag = str(model_tag or "").strip()
    if not tag or len(tag) > 160 or not OLLAMA_MODEL_TAG_PATTERN.fullmatch(tag):
        raise ValueError("invalid Ollama model tag")
    if ".." in tag or "//" in tag:
        raise ValueError("invalid Ollama model tag")
    return tag


def _normalized_http_url(url: str, *, default: str) -> str:
    candidate = str(url or "").strip() or default
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("service URL must use http:// or https://")
    # Credentials in a local-service URL are both unnecessary and easy to leak in
    # logs/UI, so reject them rather than silently preserving them.
    if parsed.username or parsed.password:
        raise ValueError("service URL must not contain embedded credentials")
    clean_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, clean_path, "", ""))


def service_root_from_v1(url: str, *, default: str) -> str:
    normalized = _normalized_http_url(url, default=default)
    parsed = urlsplit(normalized)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", ""))


def is_local_service_url(url: str, *, default: str = "") -> bool:
    """Return True for loopback/private/Docker-style service endpoints.

    The local-model center intentionally does not become a generic HTTP client.
    This also prevents a previously configured cloud image endpoint from being
    contacted automatically by local runtime health checks.
    """

    try:
        normalized = _normalized_http_url(url, default=default or "http://127.0.0.1")
    except ValueError:
        return False
    hostname = (urlsplit(normalized).hostname or "").strip("[]").lower()
    if not hostname:
        return False
    if hostname in {"localhost", "host.docker.internal"} or hostname.endswith(".localhost"):
        return True
    if hostname.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        # Single-label names are common for Docker Compose services (ollama,
        # localai, chatterbox) and private LAN DNS. Public internet hostnames
        # normally contain at least one dot.
        return "." not in hostname and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", hostname))
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _require_local_service_root(url: str, *, default: str) -> str:
    normalized = _normalized_http_url(url, default=default)
    if not is_local_service_url(normalized, default=default):
        raise ValueError(
            "local model management only accepts localhost, private/LAN, .local, "
            "or Docker service endpoints"
        )
    return service_root_from_v1(normalized, default=default)


def ollama_service_root(base_url: str = "") -> str:
    return _require_local_service_root(
        base_url, default="http://127.0.0.1:11434/v1"
    )


def localai_service_root(base_url: str = "") -> str:
    return _require_local_service_root(
        base_url, default="http://127.0.0.1:8081/v1"
    )


def chatterbox_service_root(base_url: str = "") -> str:
    return _require_local_service_root(
        base_url, default="http://127.0.0.1:4123/v1"
    )


def _error_from_response(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(
                payload.get("error")
                or payload.get("message")
                or payload.get("detail")
                or payload
            )
        return str(payload)
    except Exception:
        return (response.text or response.reason or "request failed").strip()


def check_http_health(url: str, *, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return True, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)


def list_ollama_models(base_url: str = "", *, timeout: float = 4.0) -> list[str]:
    endpoint = f"{ollama_service_root(base_url)}/api/tags"
    response = requests.get(endpoint, timeout=timeout)
    if not response.ok:
        raise LocalModelError(_error_from_response(response))
    data = response.json()
    models = []
    for item in data.get("models", []) if isinstance(data, dict) else []:
        name = item.get("name") if isinstance(item, dict) else None
        if name:
            models.append(str(name))
    return sorted(set(models))


def pull_ollama_model(
    model_tag: str,
    base_url: str = "",
    *,
    progress_callback: Callable[[str, int | None, int | None], None] | None = None,
    timeout: float = 60 * 60,
) -> None:
    """Pull one Ollama model using Ollama's HTTP API.

    The streaming endpoint avoids invoking a shell and also works when Ollama is
    running on the host while MoneyPrinterTurbo runs in a container.
    """

    model_tag = validate_ollama_model_tag(model_tag)
    endpoint = f"{ollama_service_root(base_url)}/api/pull"
    try:
        with requests.post(
            endpoint,
            json={"model": model_tag, "stream": True},
            stream=True,
            timeout=(10, timeout),
        ) as response:
            if not response.ok:
                raise LocalModelError(_error_from_response(response))
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if payload.get("error"):
                    raise LocalModelError(str(payload["error"]))
                status = str(payload.get("status") or "Downloading")
                completed = payload.get("completed")
                total = payload.get("total")
                if progress_callback:
                    progress_callback(status, completed, total)
    except requests.RequestException as exc:
        raise LocalModelError(str(exc)) from exc


def delete_ollama_model(model_tag: str, base_url: str = "", *, timeout: float = 30) -> None:
    model_tag = validate_ollama_model_tag(model_tag)
    endpoint = f"{ollama_service_root(base_url)}/api/delete"
    try:
        response = requests.delete(endpoint, json={"model": model_tag}, timeout=timeout)
    except requests.RequestException as exc:
        raise LocalModelError(str(exc)) from exc
    if not response.ok:
        raise LocalModelError(_error_from_response(response))


def download_whisper_model(model_size: str) -> Path:
    allowed = {spec.id for spec in WHISPER_MODELS}
    if model_size not in allowed:
        raise ValueError(f"unsupported Whisper model: {model_size}")
    try:
        from faster_whisper import download_model
    except ImportError as exc:
        raise LocalModelError(
            "faster-whisper is not installed. Install MoneyPrinterTurbo dependencies first."
        ) from exc

    destination = whisper_model_dir(model_size)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        resolved = download_model(model_size, output_dir=str(destination))
    except Exception as exc:
        raise LocalModelError(str(exc)) from exc

    if not (destination / "model.bin").is_file():
        resolved_path = Path(str(resolved)).resolve() if resolved else destination
        if (resolved_path / "model.bin").is_file() and resolved_path != destination:
            # Defensive fallback for older faster-whisper releases.  Normally
            # output_dir already writes directly to destination.
            for child in resolved_path.iterdir():
                target = destination / child.name
                if child.is_file():
                    shutil.copy2(child, target)
    if not (destination / "model.bin").is_file():
        raise LocalModelError("download finished but model.bin is missing")
    return destination


def localai_auth_headers(api_key: str = "") -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def list_localai_models(
    base_url: str = "", api_key: str = "", *, timeout: float = 4.0
) -> list[str]:
    root = localai_service_root(base_url)
    response = requests.get(
        f"{root}/v1/models",
        headers=localai_auth_headers(api_key),
        timeout=timeout,
    )
    if not response.ok:
        raise LocalModelError(_error_from_response(response))
    payload = response.json()
    models = []
    for item in payload.get("data", []) if isinstance(payload, dict) else []:
        model_id = item.get("id") if isinstance(item, dict) else None
        if model_id:
            models.append(str(model_id))
    return sorted(set(models))


def install_localai_gallery_model(
    model_id: str,
    base_url: str = "",
    api_key: str = "",
    *,
    timeout: float = 120.0,
) -> dict:
    allowed = {spec.id for spec in LOCALAI_IMAGE_MODELS}
    if model_id not in allowed:
        raise ValueError(f"unsupported LocalAI gallery model: {model_id}")
    root = localai_service_root(base_url)
    try:
        response = requests.post(
            f"{root}/models/apply",
            headers=localai_auth_headers(api_key),
            json={"id": model_id, "name": model_id},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise LocalModelError(str(exc)) from exc
    if not response.ok:
        raise LocalModelError(_error_from_response(response))
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text.strip() or "installation requested"}
    return payload if isinstance(payload, dict) else {"result": payload}


def get_localai_model_job(
    job_uuid: str,
    base_url: str = "",
    api_key: str = "",
    *,
    timeout: float = 10.0,
) -> dict:
    """Read a LocalAI model-install job returned by ``/models/apply``."""

    job_id = str(job_uuid or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", job_id):
        raise ValueError("invalid LocalAI model job id")
    root = localai_service_root(base_url)
    try:
        response = requests.get(
            f"{root}/models/jobs/{job_id}",
            headers=localai_auth_headers(api_key),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise LocalModelError(str(exc)) from exc
    if not response.ok:
        raise LocalModelError(_error_from_response(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise LocalModelError("LocalAI returned a non-JSON job response") from exc
    return payload if isinstance(payload, dict) else {"result": payload}


def clone_or_update_chatterbox() -> Path:
    destination = chatterbox_install_dir()
    git = shutil.which("git")
    if not git:
        raise LocalModelError("git is not installed or not on PATH")

    try:
        if (destination / ".git").is_dir():
            subprocess.run(
                [git, "-C", str(destination), "pull", "--ff-only"],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        elif destination.exists() and any(destination.iterdir()):
            raise LocalModelError(
                f"destination exists and is not a git checkout: {destination}"
            )
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [git, "clone", "--depth", "1", CHATTERBOX_REPO_URL, str(destination)],
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or exc.stdout or str(exc)).strip()
        raise LocalModelError(error) from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalModelError("Chatterbox repository operation timed out") from exc
    return destination


def install_chatterbox_dependencies() -> Path:
    # >>> MPT LOCAL AUTOMATIC v0.2.0 >>>
    # MPT-LOCAL-AUTO-LABEL: verified Chatterbox Windows CUDA installer
    destination = chatterbox_install_dir()
    if not (destination / "pyproject.toml").is_file():
        raise LocalModelError("download the Chatterbox server first")
    uv = shutil.which("uv")
    if not uv:
        raise LocalModelError("uv is not installed or not on PATH. Install uv, then retry.")
    try:
        subprocess.run(
            [uv, "sync"], cwd=str(destination), check=True,
            capture_output=True, text=True, timeout=60 * 30,
        )
        if os.name == "nt":
            python_exe = destination / ".venv" / "Scripts" / "python.exe"
            if not python_exe.is_file():
                raise LocalModelError("Chatterbox .venv Python was not created")
            subprocess.run(
                [uv, "pip", "uninstall", "--python", str(python_exe), "torchvision"],
                cwd=str(destination), check=False, capture_output=True, text=True,
                timeout=60 * 10,
            )
            subprocess.run(
                [
                    uv, "pip", "install", "--python", str(python_exe),
                    "--reinstall", "--no-deps",
                    "torch==2.6.0+cu124", "torchaudio==2.6.0+cu124",
                    "--index-url", "https://download.pytorch.org/whl/cu124",
                ],
                cwd=str(destination), check=True, capture_output=True, text=True,
                timeout=60 * 30,
            )
            subprocess.run(
                [
                    uv, "pip", "install", "--python", str(python_exe),
                    "--no-deps", "setuptools==80.9.0",
                ],
                cwd=str(destination), check=True, capture_output=True, text=True,
                timeout=60 * 10,
            )
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or exc.stdout or str(exc)).strip()
        raise LocalModelError(error) from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalModelError("Chatterbox dependency installation timed out") from exc

    env_file = destination / ".env"
    example = destination / ".env.example"
    if not env_file.exists() and example.is_file():
        shutil.copy2(example, env_file)
    required = {
        "DEVICE": "cuda" if os.name == "nt" else "auto",
        "MODEL_CACHE_DIR": "./models",
        "MAX_CHUNK_LENGTH": "200",
        "MEMORY_CLEANUP_INTERVAL": "3",
        "CUDA_CACHE_CLEAR_INTERVAL": "1",
    }
    existing = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    result = []
    replaced = set()
    for line in existing:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in required:
            result.append(f"{key}={required[key]}")
            replaced.add(key)
        else:
            result.append(line)
    for key, value in required.items():
        if key not in replaced:
            result.append(f"{key}={value}")
    env_file.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
    return destination
    # <<< MPT LOCAL AUTOMATIC v0.2.0 <<<


def _chatterbox_pid_file() -> Path:
    return chatterbox_install_dir() / ".mpt-chatterbox.pid"


def _chatterbox_log_file() -> Path:
    return chatterbox_install_dir() / "mpt-chatterbox.log"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # Python's os.kill implementation on Windows maps ordinary signals to
        # TerminateProcess; unlike POSIX, signal 0 is not a portable harmless
        # liveness probe. Query a process handle instead.
        try:
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def chatterbox_managed_process_status() -> tuple[bool, int | None, str]:
    pid_file = _chatterbox_pid_file()
    if not pid_file.is_file():
        return False, None, str(_chatterbox_log_file())
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False, None, str(_chatterbox_log_file())
    return _pid_is_running(pid), pid, str(_chatterbox_log_file())


def start_chatterbox_server() -> int:
    running, pid, _ = chatterbox_managed_process_status()
    if running and pid:
        return pid

    destination = chatterbox_install_dir()
    if not (destination / "pyproject.toml").is_file():
        raise LocalModelError("download the Chatterbox server first")
    # >>> MPT LOCAL AUTOMATIC v0.2.0 >>>
    # MPT-LOCAL-AUTO-LABEL: direct Chatterbox verified launcher
    if os.name == "nt":
        python_exe = destination / ".venv" / "Scripts" / "python.exe"
    else:
        python_exe = destination / ".venv" / "bin" / "python"
    if not python_exe.is_file():
        raise LocalModelError("install Chatterbox dependencies first")
    # <<< MPT LOCAL AUTOMATIC v0.2.0 <<<

    log_path = _chatterbox_log_file()
    log_handle = open(log_path, "ab", buffering=0)
    creationflags = 0
    popen_kwargs: dict = {}
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        # >>> MPT LOCAL AUTOMATIC v0.2.0 >>>
        # MPT-LOCAL-AUTO-LABEL: Chatterbox UTF-8 process environment
        child_env = os.environ.copy()
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env.setdefault("HF_HOME", str(HF_HOME))
        child_env.setdefault("HF_HUB_CACHE", str(HF_HUB_CACHE))
        child_env.pop("HF_HUB_OFFLINE", None)
        process = subprocess.Popen(
            [str(python_exe), "main.py"],
            cwd=str(destination),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=child_env,
            creationflags=creationflags,
            **popen_kwargs,
        )
        # <<< MPT LOCAL AUTOMATIC v0.2.0 <<<
    except Exception as exc:
        log_handle.close()
        raise LocalModelError(str(exc)) from exc
    finally:
        # Popen duplicated the descriptor for the child; the parent does not need
        # to keep it open.
        try:
            log_handle.close()
        except Exception:
            pass

    _chatterbox_pid_file().write_text(str(process.pid), encoding="utf-8")
    return process.pid


def stop_chatterbox_server() -> bool:
    running, pid, _ = chatterbox_managed_process_status()
    if not running or not pid:
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        else:
            os.kill(pid, 15)
            deadline = time.time() + 8
            while time.time() < deadline and _pid_is_running(pid):
                time.sleep(0.2)
            if _pid_is_running(pid):
                os.kill(pid, 9)
    except OSError:
        pass
    try:
        _chatterbox_pid_file().unlink(missing_ok=True)
    except OSError:
        pass
    return True


def warmup_chatterbox_model(
    base_url: str = "", api_key: str = "", *, timeout: float = 60 * 30
) -> int:
    """Trigger Chatterbox's first synthesis, which downloads/loads its model."""

    root = chatterbox_service_root(base_url)
    headers = {"Content-Type": "application/json"}
    if str(api_key or "").strip():
        headers["Authorization"] = f"Bearer {str(api_key).strip()}"
    payload = {
        # >>> MPT LOCAL AUTOMATIC v0.2.0 >>>
        # MPT-LOCAL-AUTO-LABEL: verified Chatterbox warmup request
        "model": "chatterbox-tts-1",
        "voice": "alloy",
        # <<< MPT LOCAL AUTOMATIC v0.2.0 <<<
        "input": "Local model ready.",
        "response_format": "wav",
    }
    try:
        response = requests.post(
            f"{root}/v1/audio/speech", headers=headers, json=payload, timeout=timeout
        )
    except requests.RequestException as exc:
        raise LocalModelError(str(exc)) from exc
    if not response.ok:
        raise LocalModelError(_error_from_response(response))
    return len(response.content)


def runtime_health_snapshot(
    *,
    ollama_base_url: str = "",
    localai_base_url: str = "",
    localai_api_key: str = "",
    chatterbox_base_url: str = "",
) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}

    try:
        ollama_models = list_ollama_models(ollama_base_url)
        snapshot["ollama"] = {
            "ok": True,
            "detail": f"{len(ollama_models)} model(s) installed",
            "models": ollama_models,
        }
    except Exception as exc:
        snapshot["ollama"] = {"ok": False, "detail": str(exc), "models": []}

    try:
        localai_models = list_localai_models(localai_base_url, localai_api_key)
        snapshot["localai"] = {
            "ok": True,
            "detail": f"{len(localai_models)} model(s) exposed",
            "models": localai_models,
        }
    except Exception as exc:
        snapshot["localai"] = {"ok": False, "detail": str(exc), "models": []}

    managed, pid, log_file = chatterbox_managed_process_status()
    try:
        chatterbox_root = chatterbox_service_root(chatterbox_base_url)
        ok, detail = check_http_health(f"{chatterbox_root}/health")
    except Exception as exc:
        ok, detail = False, str(exc)
    snapshot["chatterbox"] = {
        "ok": ok,
        "detail": detail,
        "managed": managed,
        "pid": pid,
        "log_file": log_file,
    }

    snapshot["whisper"] = {
        "ok": any(is_whisper_model_downloaded(spec.id) for spec in WHISPER_MODELS),
        "detail": ", ".join(
            spec.id for spec in WHISPER_MODELS if is_whisper_model_downloaded(spec.id)
        )
        or "no pre-downloaded model",
    }
    snapshot["ffmpeg"] = {
        "ok": bool(shutil.which("ffmpeg")),
        "detail": shutil.which("ffmpeg") or "not found on PATH",
    }
    snapshot["git"] = {
        "ok": bool(shutil.which("git")),
        "detail": shutil.which("git") or "not found on PATH",
    }
    snapshot["uv"] = {
        "ok": bool(shutil.which("uv")),
        "detail": shutil.which("uv") or "not found on PATH",
    }
    snapshot["python"] = {
        "ok": True,
        "detail": sys.executable,
    }
    return snapshot


def tail_file(path: str | Path, *, max_bytes: int = 12_000) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        return ""
    try:
        with file_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
        return data.decode("utf-8", errors="replace")
    except OSError as exc:
        logger.debug(f"failed to read local runtime log {file_path}: {exc}")
        return ""


def get_model_spec(models: Iterable[DownloadableModel], model_id: str) -> DownloadableModel | None:
    return next((item for item in models if item.id == model_id), None)
