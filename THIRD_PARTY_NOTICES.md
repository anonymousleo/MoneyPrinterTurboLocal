# Third-Party Notices

## MoneyPrinterTurbo

- Project: https://github.com/harry0703/MoneyPrinterTurbo
- Role: upstream application/workflow base
- License: MIT
- The upstream `LICENSE` file is retained.

## Local model/runtime integrations

This fork contains integration code for local runtimes/models such as Ollama,
Qwen, Chatterbox, Faster-Whisper, LocalAI, and CogVideoX.

Model weights are not intended to be committed to this repository. Each model
and runtime remains subject to its own upstream license and terms.

Before a public release, the exact dependency versions and license links used
by the installer must be recorded here and in the release manifest.

## Phase 3 local runtime components

The release installer may download the following separate runtimes/models:

- **Ollama / Qwen3:8B** — Qwen3:8B is distributed under Apache-2.0 through
  Ollama.
- **Systran/faster-whisper-medium** — MIT.
- **travisvn/chatterbox-tts-api** — current upstream repository identifies the
  API wrapper as AGPL-3.0. It is downloaded as a separate runtime and is not
  vendored into this repository.
- **Chatterbox model/runtime code** — separate upstream licensing applies.
- **zai-org/CogVideoX1.5-5B** — CogVideoX model license.

Model weights and downloaded third-party runtime trees are not committed to
MoneyPrinterTurbo-LocalAI.
