"""Download Whisper model files for fully offline runtime."""

from __future__ import annotations

import argparse
import logging
import sys

from kwhisperx.config import Config
from kwhisperx.transcribe import download_model, models_dir


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Download faster-whisper models for offline use (requires network once).",
    )
    parser.add_argument(
        "models",
        nargs="*",
        help="Model names to download (default: from config or base.en)",
    )
    args = parser.parse_args(argv)

    config = Config.load()
    to_fetch = args.models or [config.model_size]
    root = models_dir(config.models_dir or None)

    print(f"Models will be stored in: {root}")
    print("This step contacts huggingface.co once per model. Runtime dictation stays offline.")
    for name in to_fetch:
        download_model(name, root)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
