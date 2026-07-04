"""Speech-to-text via faster-whisper (local models only at runtime)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from kwhisperx.audio import prepare_for_transcription

log = logging.getLogger(__name__)

_model = None
_model_key: tuple[str, str, str, str, str] | None = None

DEFAULT_MODELS_DIR = Path.home() / ".local" / "share" / "kwhisperx" / "models"


def configure_offline_mode() -> None:
    """Prevent runtime contact with Hugging Face or other remote hosts."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"


def models_dir(path: str | Path | None = None) -> Path:
    if path is None or str(path).strip() == "":
        return DEFAULT_MODELS_DIR
    return Path(path)


def _detect_device(device: str) -> tuple[str, str]:
    if device == "cpu":
        return "cpu", "int8"
    if device == "cuda":
        return "cuda", "int8_float16"
    if device == "amd":
        # CTranslate2 uses device="cuda" for ROCm/HIP backends as well.
        return "cuda", "int8_float16"
    if shutil.which("nvidia-smi") and _nvidia_available():
        return "cuda", "int8_float16"
    return "cpu", "int8"


def _apply_compute_runtime(device_setting: str) -> None:
    """Apply backend-specific environment before loading the model."""
    if device_setting == "amd":
        # Helps many RDNA2 cards; harmless on other ROCm GPUs.
        os.environ["CT2_CUDA_ALLOCATOR"] = "cub_caching"
    else:
        os.environ.pop("CT2_CUDA_ALLOCATOR", None)


def _nvidia_available() -> bool:
    try:
        subprocess.run(
            ["nvidia-smi"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def model_marker(model_size: str, root: Path) -> Path:
    return root / f".{model_size.replace('/', '_')}.ready"


def is_model_cached(model_size: str, root: Path | None = None) -> bool:
    directory = models_dir(root)
    return model_marker(model_size, directory).is_file()


def download_model(model_size: str, root: Path | None = None) -> Path:
    """Download a Whisper model once (used by setup, not at dictation runtime)."""
    directory = models_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    log.info("Downloading Whisper model %s to %s", model_size, directory)
    from faster_whisper import WhisperModel

    WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        download_root=str(directory),
        local_files_only=False,
    )
    model_marker(model_size, directory).write_text("ok\n")
    log.info("Model %s ready at %s", model_size, directory)
    return directory


def _get_model(model_size: str, device_setting: str, root: Path) -> object:
    global _model, _model_key
    if not is_model_cached(model_size, root):
        raise FileNotFoundError(
            f"Whisper model '{model_size}' is not installed locally. "
            f"Run: ./setup.sh  (or: .venv/bin/python -m kwhisperx.download_models {model_size})"
        )
    dev, compute = _detect_device(device_setting)
    key = (model_size, device_setting, dev, compute, str(root))
    if _model is None or _model_key != key:
        unload_model()
        _apply_compute_runtime(device_setting)
        from faster_whisper import WhisperModel

        backend = "ROCm" if device_setting == "amd" else dev
        log.info("Loading local Whisper model %s on %s from %s", model_size, backend, root)
        _model = WhisperModel(
            model_size,
            device=dev,
            compute_type=compute,
            download_root=str(root),
            local_files_only=True,
        )
        _model_key = key
    return _model


def unload_model() -> None:
    """Release the loaded model and GPU runtime state."""
    global _model, _model_key
    if _model is not None:
        del _model
        _model = None
    _model_key = None
    import gc

    gc.collect()


def reload_model() -> None:
    unload_model()


def transcribe(
    audio: np.ndarray,
    *,
    model_size: str = "base",
    device: str = "auto",
    language: str | None = "en",
    models_path: str | Path | None = None,
) -> str:
    if audio is None or len(audio) == 0:
        return ""
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    audio = prepare_for_transcription(audio)
    root = models_dir(models_path)
    model = _get_model(model_size, device, root)
    lang = None if not language or language.lower() == "auto" else language
    segments, _ = model.transcribe(audio, language=lang)
    return " ".join(s.text for s in segments if s.text).strip()
