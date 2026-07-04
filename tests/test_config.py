"""Regression tests for configuration defaults and persistence."""

from __future__ import annotations

import json

from kwhisperx.config import Config, hotkey_key_set, hotkey_to_pynput


class TestConfigDefaults:
    """Streaming is opt-in; batch-on-stop remains default."""

    def test_streaming_off_by_default(self) -> None:
        cfg = Config()
        assert cfg.chunk_injection is False
        assert cfg.silence_seconds == 1.5
        assert cfg.pause_noise_floor == 0.50

    def test_load_ignores_unknown_keys(self, tmp_path, monkeypatch) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "hotkey": "Ctrl+Space",
                    "chunk_injection": True,
                    "unknown_future_field": "ignored",
                }
            )
        )
        monkeypatch.setattr("kwhisperx.config.CONFIG_FILE", config_file)
        cfg = Config.load()
        assert cfg.hotkey == "Ctrl+Space"
        assert cfg.chunk_injection is True
        assert not hasattr(cfg, "unknown_future_field") or cfg.to_dict().get("unknown_future_field") is None


class TestHotkeyParsing:
    def test_hotkey_to_pynput(self) -> None:
        assert hotkey_to_pynput("Ctrl+Alt+Space") == "<ctrl>+<alt>+<space>"

    def test_hotkey_key_set(self) -> None:
        assert hotkey_key_set("Ctrl+Alt+Space") == frozenset({"ctrl", "alt", "space"})
