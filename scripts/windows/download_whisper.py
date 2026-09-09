from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--local-dir", required=True)
    args = ap.parse_args()

    dest = Path(args.local_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    print(f"WHISPER_DOWNLOAD repo={args.repo}")
    print(f"WHISPER_REVISION {args.revision}")
    print(f"WHISPER_DEST {dest}")

    snapshot_download(
        repo_id=args.repo,
        revision=args.revision,
        local_dir=str(dest),
    )

    required = ("model.bin", "config.json", "tokenizer.json")
    missing = [name for name in required if not (dest / name).is_file()]
    if missing:
        raise SystemExit("WHISPER_INCOMPLETE missing=" + ",".join(missing))

    print("WHISPER_SETUP_PASS")


if __name__ == "__main__":
    main()
