from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest

from app.models.llm_provider import DEFAULT_LLM_PROVIDER_ID
from app.services import cogvideox_local, material, subtitle


ROOT = Path(__file__).resolve().parents[2]


def _example_config():
    return tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))


def test_local_release_defaults_to_ollama_qwen3():
    cfg = _example_config()
    assert cfg["app"]["llm_provider"] == "ollama"
    assert cfg["app"]["ollama_model_name"] == "qwen3:8b"
    assert DEFAULT_LLM_PROVIDER_ID == "ollama"


def test_whisper_default_matches_installed_medium_payload():
    cfg = _example_config()
    assert cfg["whisper"]["model_size"] == "medium"


def test_cogvideox_low_vram_worker_keeps_prompt_embeddings_on_cpu():
    worker = (ROOT / "local_apps" / "cogvideox" / "cogvideox_worker.py").read_text(encoding="utf-8")
    assert "prompt_embeds_cuda" not in worker
    assert "prompt_embeds=prompt_embeds" in worker
    assert "negative_prompt_embeds=negative_prompt_embeds" in worker
    assert "enable_sequential_cpu_offload" in worker


def test_whisper_runtime_selection_invalidates_cached_model(monkeypatch, tmp_path):
    calls = []

    class Info:
        language = "en"
        language_probability = 1.0

    class FakeWhisperModel:
        def __init__(self, model_size_or_path, device, compute_type):
            calls.append((model_size_or_path, device, compute_type))

        def transcribe(self, *args, **kwargs):
            return [], Info()

    monkeypatch.setattr(subtitle, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(subtitle, "model", None)
    monkeypatch.setattr(subtitle, "model_key", None)

    monkeypatch.setitem(subtitle.config.whisper, "model_size", "medium")
    monkeypatch.setitem(subtitle.config.whisper, "device", "cpu")
    monkeypatch.setitem(subtitle.config.whisper, "compute_type", "int8")
    subtitle.create("dummy.wav", str(tmp_path / "medium.srt"))

    monkeypatch.setitem(subtitle.config.whisper, "model_size", "small")
    subtitle.create("dummy.wav", str(tmp_path / "small.srt"))

    assert len(calls) == 2
    assert calls[0][-2:] == ("cpu", "int8")
    assert calls[1][-2:] == ("cpu", "int8")
    assert calls[0][0].endswith("whisper-medium") or calls[0][0] == "medium"
    assert calls[1][0].endswith("whisper-small") or calls[1][0] == "small"

def test_cogvideox_worker_oom_becomes_specific_local_error(monkeypatch, tmp_path):
    python_path = tmp_path / "python.exe"
    worker_path = tmp_path / "cogvideox_worker.py"
    model_dir = tmp_path / "model"
    output_dir = tmp_path / "outputs"

    python_path.write_text("", encoding="utf-8")
    worker_path.write_text("", encoding="utf-8")
    model_dir.mkdir()
    output_dir.mkdir()
    (model_dir / "model_index.json").write_text("{}", encoding="utf-8")

    app_cfg = dict(cogvideox_local.config.app)
    app_cfg.update(
        {
            "cogvideox_python": str(python_path),
            "cogvideox_worker": str(worker_path),
            "cogvideox_model_dir": str(model_dir),
            "cogvideox_timeout_seconds": 60,
        }
    )
    monkeypatch.setattr(cogvideox_local.config, "app", app_cfg)
    monkeypatch.setattr(cogvideox_local, "_release_other_gpu_models", lambda: None)

    failed_worker = SimpleNamespace(
        returncode=1,
        stdout="RuntimeError: CUDA error: out of memory",
    )
    monkeypatch.setattr(
        cogvideox_local.subprocess,
        "run",
        lambda *args, **kwargs: failed_worker,
    )

    with pytest.raises(
        cogvideox_local.CogVideoXLocalError,
        match="CogVideoX CUDA out of memory",
    ):
        cogvideox_local.generate_videos(
            task_id="oom-regression",
            search_terms=["cinematic landscape"],
            video_aspect="16:9",
            audio_duration=4.0,
            max_clip_duration=4,
            material_directory=str(output_dir),
        )


def test_material_propagates_cogvideox_failure_without_cloud_fallback(monkeypatch):
    def fail_generation(**kwargs):
        raise cogvideox_local.CogVideoXLocalError("synthetic local generation failure")

    monkeypatch.setattr(
        material.cogvideox_local,
        "generate_videos",
        fail_generation,
    )

    app_cfg = dict(material.config.app)
    app_cfg["cogvideox_fallback_openai_image"] = False
    app_cfg["material_directory"] = ""
    monkeypatch.setattr(material.config, "app", app_cfg)

    with pytest.raises(
        cogvideox_local.CogVideoXLocalError,
        match="synthetic local generation failure",
    ):
        material.download_videos(
            task_id="propagation-regression",
            search_terms=["cinematic landscape"],
            source="cogvideox_local",
            video_aspect="16:9",
            audio_duration=4.0,
            max_clip_duration=4,
        )


def test_local_release_defaults_to_chatterbox_whisper():
    cfg = _example_config()
    assert cfg["app"]["subtitle_provider"] == "whisper"
    assert cfg["ui"]["tts_server"] == "chatterbox"
    assert cfg["chatterbox"]["model_id"] == "chatterbox-tts-1"
    assert cfg["chatterbox"]["voices"] == ["alloy"]
    assert cfg["ui"]["voice_name"] == "chatterbox:alloy"
    assert cfg["whisper"]["model_size"] == "medium"
    assert cfg["whisper"]["device"] == "cpu"
    assert cfg["whisper"]["compute_type"] == "int8"


def test_webui_missing_tts_setting_falls_back_to_chatterbox():
    source = (ROOT / "webui" / "Main.py").read_text(encoding="utf-8")
    assert source.count('config.ui.get("tts_server", "chatterbox")') >= 2
    assert 'saved_tts_server = "chatterbox"' in source
    assert 'config.ui.get("tts_server", "azure-tts-v1")' not in source
