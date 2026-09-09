# Contributions in MoneyPrinterTurbo-LocalAI

This repository is based on the upstream
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) project.

LocalAI fork maintainer: **Muhammad Salman (@anonymousleo)**

## Contributions added by this fork

- Local Automatic runtime orchestration for local model/service lifecycle.
- Ollama / Qwen local LLM integration for script and term generation.
- Local Chatterbox TTS integration with automatic CUDA startup/shutdown.
- Screenplay-aware narration extraction so TTS speaks voice-over text instead
  of camera, visual, audio, and production directions.
- CogVideoX1.5-5B local text-to-video backend integrated into the existing
  MoneyPrinterTurbo material pipeline and WebUI.
- Low-VRAM CogVideoX execution path validated on an RTX 4060 Laptop 8 GB,
  including CPU-side T5 prompt encoding, T5 release before denoising,
  TorchAO INT8, and sequential CPU offload.
- Automatic GPU hand-off between local LLM, TTS, and video generation stages.
- Portable model-path handling so end users are not tied to development-machine
  drive letters.
- Windows end-user deployment tooling and verification for `v0.1.0-local`
  (in active development).

## Attribution boundary

Features inherited unchanged from upstream MoneyPrinterTurbo are not claimed
as work of this fork. See the upstream repository and its Git history for
original authorship.
