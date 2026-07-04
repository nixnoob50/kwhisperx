"""Application configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "kwhisperx"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    hotkey: str = "Ctrl+Alt+Space"
    hotkey_mode: str = "toggle"  # toggle | hold
    model_size: str = "base"
    device: str = "auto"  # auto | cpu | cuda | amd
    language: str = "en"
    microphone: int | None = None
    injection_method: str = "auto"  # auto | clipboard | terminal | keystrokes
    chunk_injection: bool = False
    silence_seconds: float = 1.5
    pause_noise_floor: float = 0.50  # drop ratio: pause must fall below this fraction of peak speech
    autostart: bool = False
    install_path: str = ""
    models_dir: str = ""  # default: ~/.local/share/kwhisperx/models

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_FILE.exists():
            cfg = cls()
            cfg.install_path = _detect_install_path()
            cfg.save()
            return cfg
        data = json.loads(CONFIG_FILE.read_text())
        cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if not cfg.install_path:
            cfg.install_path = _detect_install_path()
        return cfg

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2) + "\n")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_install_path() -> str:
    return str(Path(__file__).resolve().parent.parent)


def hotkey_to_pynput(hotkey: str) -> str:
    parts = hotkey.replace(" ", "").split("+")
    names = []
    for part in parts:
        key = part.strip().lower()
        if key in ("ctrl", "control"):
            names.append("<ctrl>")
        elif key in ("alt", "option"):
            names.append("<alt>")
        elif key == "shift":
            names.append("<shift>")
        elif key in ("super", "meta", "win"):
            names.append("<cmd>")
        elif len(key) == 1:
            names.append(key)
        else:
            names.append(f"<{key}>")
    return "+".join(names)


def hotkey_key_set(hotkey: str) -> frozenset[str]:
    parts = hotkey.replace(" ", "").split("+")
    result: set[str] = set()
    for part in parts:
        key = part.strip().lower()
        if key in ("ctrl", "control"):
            result.add("ctrl")
        elif key in ("alt", "option"):
            result.add("alt")
        elif key == "shift":
            result.add("shift")
        elif key in ("super", "meta", "win"):
            result.add("super")
        else:
            result.add(key)
    return frozenset(result)
