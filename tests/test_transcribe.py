"""Regression tests for transcription helpers (no GPU model load)."""

from __future__ import annotations

import numpy as np

from kwhisperx.transcribe import configure_offline_mode, transcribe


class TestTranscribeEmpty:
    """Empty or missing audio must return empty string without invoking the model."""

    def test_empty_array(self) -> None:
        assert transcribe(np.array([], dtype=np.float32)) == ""

    def test_none_guard_via_empty(self) -> None:
        assert transcribe(np.array([], dtype=np.float32), language="en") == ""


class TestOfflineMode:
    def test_sets_hf_offline_env(self, monkeypatch) -> None:
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        configure_offline_mode()
        import os

        assert os.environ.get("HF_HUB_OFFLINE") == "1"
