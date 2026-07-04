"""Shared pytest fixtures and audio helpers."""

from __future__ import annotations

import sys

import numpy as np
import pytest

from kwhisperx.audio import SAMPLE_RATE


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for tests that touch Qt (tray icons, locks)."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def make_flat_audio(seconds: float, level: float, *, sr: int = SAMPLE_RATE) -> np.ndarray:
    n = int(seconds * sr)
    return np.full(n, level, dtype=np.float32)


def speech_then_silence(
    speech_sec: float,
    silence_sec: float,
    *,
    speech_level: float = 0.05,
    silence_level: float = 0.0002,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    return np.concatenate(
        [
            make_flat_audio(speech_sec, speech_level, sr=sr),
            make_flat_audio(silence_sec, silence_level, sr=sr),
        ]
    )
