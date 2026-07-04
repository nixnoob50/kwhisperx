"""Regression tests for background transcription worker (streaming crash fix)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from kwhisperx.app import TranscribeWorker


class TestTranscribeWorker:
    """Worker must emit (text, is_final) and accept is_final flag (QThread lifecycle)."""

    @pytest.fixture
    def sample_audio(self):
        return np.zeros(16000, dtype=np.float32)

    def test_emits_is_final_true_by_default(self, qapp, sample_audio) -> None:
        worker = TranscribeWorker(
            sample_audio,
            "base",
            "cpu",
            "en",
            "",
            parent=None,
        )
        results: list[tuple[str, bool]] = []
        worker.finished_text.connect(lambda text, final: results.append((text, final)))
        with patch("kwhisperx.app.transcribe", return_value="hello"):
            worker.run()
        assert results == [("hello", True)]

    def test_emits_is_final_false_for_streaming_chunk(self, qapp, sample_audio) -> None:
        worker = TranscribeWorker(
            sample_audio,
            "base",
            "cpu",
            "en",
            "",
            is_final=False,
            parent=None,
        )
        results: list[tuple[str, bool]] = []
        worker.finished_text.connect(lambda text, final: results.append((text, final)))
        with patch("kwhisperx.app.transcribe", return_value="partial"):
            worker.run()
        assert results == [("partial", False)]
