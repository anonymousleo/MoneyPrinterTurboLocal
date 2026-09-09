from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import struct
from pathlib import Path

import requests
from faster_whisper import WhisperModel


REPO = Path(__file__).resolve().parents[2]
CHATTER_DIR = REPO / "local_apps" / "chatterbox-tts-api"
CHATTER_PY = CHATTER_DIR / ".venv" / "Scripts" / "python.exe"
WHISPER_DIR = REPO / "models" / "whisper-medium"
OUT_DIR = REPO / ".runtime" / "smoke"
OUT_WAV = OUT_DIR / "core_tts.wav"
CHATTER_LOG = OUT_DIR / "chatterbox-smoke.log"

HEALTH_URL = "http://127.0.0.1:4123/health"
SPEECH_URL = "http://127.0.0.1:4123/v1/audio/speech"
TEST_TEXT = "Money Printer Turbo local AI core smoke test passed."


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def wait_for_health(session: requests.Session, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            r = session.get(HEALTH_URL, timeout=5)
            if r.ok:
                payload = r.json()
                print("CHATTERBOX_HEALTH", json.dumps(payload, ensure_ascii=False))
                status = payload.get("status")
                if status == "healthy":
                    return payload
                if status == "error":
                    fail(
                        "Chatterbox initialization failed: "
                        f"{payload.get('initialization_error')!r}; "
                        f"log={CHATTER_LOG}"
                    )
        except SystemExit:
            raise
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    fail(f"Chatterbox health timeout; last_error={last_error!r}")


def validate_wav(path: Path) -> None:
    # Chatterbox may return WAVE_FORMAT_IEEE_FLOAT (format tag 3).
    # Python 3.11's stdlib wave module rejects that valid WAV encoding,
    # so parse RIFF chunks directly and let faster-whisper/PyAV perform
    # the real audio decode in the next functional stage.
    if not path.is_file():
        fail("TTS output WAV was not created")

    file_size = path.stat().st_size
    if file_size < 10_000:
        fail(f"TTS WAV suspiciously small: {file_size} bytes")

    raw = path.read_bytes()
    if len(raw) < 44:
        fail("TTS WAV is too small to contain a RIFF/WAVE header")
    if raw[0:4] not in (b"RIFF", b"RF64") or raw[8:12] != b"WAVE":
        fail(f"TTS response is not RIFF/WAVE: header={raw[:12]!r}")

    fmt = None
    data_size = None
    offset = 12

    while offset + 8 <= len(raw):
        chunk_id = raw[offset:offset + 4]
        chunk_size = struct.unpack_from("<I", raw, offset + 4)[0]
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size

        if chunk_end > len(raw):
            fail(
                f"Malformed WAV chunk {chunk_id!r}: "
                f"declared={chunk_size} remaining={len(raw) - chunk_start}"
            )

        if chunk_id == b"fmt " and chunk_size >= 16:
            (
                format_tag,
                channels,
                sample_rate,
                byte_rate,
                block_align,
                bits_per_sample,
            ) = struct.unpack_from("<HHIIHH", raw, chunk_start)
            fmt = {
                "format_tag": format_tag,
                "channels": channels,
                "sample_rate": sample_rate,
                "byte_rate": byte_rate,
                "block_align": block_align,
                "bits_per_sample": bits_per_sample,
            }
        elif chunk_id == b"data":
            data_size = chunk_size

        offset = chunk_end + (chunk_size & 1)

    if fmt is None:
        fail("TTS WAV has no fmt chunk")
    if data_size is None:
        fail("TTS WAV has no data chunk")

    if fmt["format_tag"] not in (1, 3, 0xFFFE):
        fail(f"Unsupported WAV format tag: {fmt['format_tag']}")

    if fmt["channels"] < 1 or fmt["sample_rate"] < 8000:
        fail(
            "Invalid WAV stream parameters: "
            f"channels={fmt['channels']} rate={fmt['sample_rate']}"
        )

    byte_rate = fmt["byte_rate"]
    if byte_rate <= 0:
        fail("Invalid WAV byte rate")

    duration = data_size / float(byte_rate)
    if duration < 0.5:
        fail(f"TTS WAV duration too short: {duration:.2f}s")

    format_names = {
        1: "PCM",
        3: "IEEE_FLOAT",
        0xFFFE: "EXTENSIBLE",
    }
    fmt_name = format_names[fmt["format_tag"]]

    print(
        f"TTS_WAV_PASS bytes={file_size} "
        f"format={fmt_name} tag={fmt['format_tag']} "
        f"bits={fmt['bits_per_sample']} "
        f"channels={fmt['channels']} "
        f"rate={fmt['sample_rate']} "
        f"duration={duration:.2f}s"
    )


def transcribe_wav(path: Path) -> str:
    print("WHISPER_LOAD_START device=cpu compute_type=int8")
    model = WhisperModel(
        str(WHISPER_DIR),
        device="cpu",
        compute_type="int8",
    )
    segments, info = model.transcribe(
        str(path),
        language="en",
        beam_size=1,
        vad_filter=False,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    print(f"WHISPER_LANGUAGE={info.language}")
    print(f"WHISPER_TRANSCRIPT={text}")
    if not text:
        fail("Whisper returned an empty transcription")
    print("WHISPER_TRANSCRIBE_PASS")
    return text


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not CHATTER_PY.is_file():
        fail(f"Chatterbox Python missing: {CHATTER_PY}")
    if not (WHISPER_DIR / "model.bin").is_file():
        fail(f"Whisper model missing: {WHISPER_DIR}")

    # Prevent localhost calls from being routed through Clash/system proxies.
    session = requests.Session()
    session.trust_env = False

    already_running = False
    try:
        r = session.get(HEALTH_URL, timeout=2)
        already_running = r.ok
    except Exception:
        already_running = False

    proc = None
    log_fh = None

    try:
        if already_running:
            print("CHATTERBOX_SERVER already running; reusing it")
        else:
            print("CHATTERBOX_SERVER_START")
            log_fh = CHATTER_LOG.open("w", encoding="utf-8")
            env = os.environ.copy()
            env["NO_PROXY"] = "127.0.0.1,localhost"
            env["no_proxy"] = "127.0.0.1,localhost"
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                [
                    str(CHATTER_PY),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "4123",
                ],
                cwd=str(CHATTER_DIR),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0
                ),
            )

        health = wait_for_health(session)
        if health.get("device") not in (None, "cuda"):
            fail(f"Chatterbox health reports unexpected device: {health.get('device')}")
        print("CHATTERBOX_HEALTH_PASS")

        print("CHATTERBOX_TTS_START")
        response = session.post(
            SPEECH_URL,
            json={
                "input": TEST_TEXT,
                "voice": "alloy",
                "response_format": "wav",
            },
            timeout=600,
        )
        print(f"CHATTERBOX_TTS_HTTP={response.status_code}")
        if response.status_code != 200:
            fail(
                "Chatterbox TTS request failed: "
                + response.text[:1000]
            )

        OUT_WAV.write_bytes(response.content)
        validate_wav(OUT_WAV)
        print("CHATTERBOX_TTS_PASS")

        transcribe_wav(OUT_WAV)

        print("")
        print("CORE_FUNCTIONAL_SMOKE_PASS")
        print(f"OUTPUT_WAV={OUT_WAV}")
        print(f"CHATTERBOX_LOG={CHATTER_LOG}")
    finally:
        if proc is not None:
            print("CHATTERBOX_SERVER_STOP")
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        if log_fh is not None:
            log_fh.close()


if __name__ == "__main__":
    main()
