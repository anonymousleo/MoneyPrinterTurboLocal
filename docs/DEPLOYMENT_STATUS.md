# Deployment Status

## Phase 1 — Portable LocalAI core

Status: **PASS**

- Local Automatic runtime
- Ollama/Qwen integration
- Chatterbox integration hooks
- CogVideoX integration
- portable model paths
- attribution/contribution documentation
- source portability and secret audit

## Phase 2 — Windows deployment foundation

Status: **IMPLEMENTED / REQUIRES FRESH-MACHINE VALIDATION**

- `INSTALL.bat`
- `VERIFY.bat`
- `START.bat`
- project-local uv
- uv-managed Python 3.11
- `.venv` synchronization from `uv.lock`
- automatic Windows proxy detection
- FFmpeg install/check
- Ollama install/check
- portable model-root environment

## Remaining before v0.1.0-local

- package Chatterbox reproducibly
- automate Qwen model pull
- automate optional CogVideoX model download
- finalize RTX 8 GB CogVideoX profile
- add GPU hand-off verification
- run clean Windows installation test
- create release ZIP and SHA256
