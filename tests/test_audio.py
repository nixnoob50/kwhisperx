"""Regression tests for microphone capture, VAD, and streaming chunk boundaries."""

from __future__ import annotations

import numpy as np

from kwhisperx.audio import (
    DEFAULT_MIN_SPEECH_SEC,
    SAMPLE_RATE,
    AudioRecorder,
    PauseTracker,
    audio_rms,
    effective_pause_drop_ratio,
    find_utterance_boundary,
    has_audio,
    has_speech,
    pause_noise_floor_from_slider,
    pause_noise_slider_from_floor,
    prepare_for_transcription,
    resample_audio,
)

from tests.conftest import make_flat_audio, speech_then_silence


class TestSilentMicRejection:
    """v0.2.x: disabled mic / silence must not be treated as valid audio."""

    def test_empty_array_has_no_audio(self) -> None:
        assert not has_audio(np.array([], dtype=np.float32))

    def test_zeros_has_no_audio(self) -> None:
        assert not has_audio(make_flat_audio(1.0, 0.0))

    def test_quiet_noise_below_threshold(self) -> None:
        assert not has_audio(make_flat_audio(2.0, 1e-8))


class TestPrepareForTranscription:
    """Streaming stop fix: do not amplify near-silent buffers (Whisper hallucinations)."""

    def test_does_not_boost_silence(self) -> None:
        silence = make_flat_audio(1.0, 0.0002)
        out = prepare_for_transcription(silence)
        assert audio_rms(out) < 0.001

    def test_boosts_quiet_speech(self) -> None:
        quiet = make_flat_audio(1.0, 0.02)
        out = prepare_for_transcription(quiet)
        assert float(np.max(np.abs(out))) > 0.5


class TestHasSpeech:
    """Distinguish speech from mic noise; used to skip silent streaming remainders."""

    def test_detects_speech(self) -> None:
        assert has_speech(make_flat_audio(1.0, 0.05))

    def test_rejects_silence_only(self) -> None:
        assert not has_speech(make_flat_audio(2.0, 0.0002))

    def test_rejects_trailing_silence_after_pause(self) -> None:
        audio = speech_then_silence(1.0, 1.5)
        tail = audio[-int(1.5 * SAMPLE_RATE) :]
        assert not has_speech(tail)


class TestUtteranceBoundary:
    """Pause-based streaming: detect end of speech before injecting a chunk."""

    def test_finds_boundary_after_speech_and_pause(self) -> None:
        audio = speech_then_silence(1.0, 1.6)
        boundary = find_utterance_boundary(audio, silence_sec=1.5)
        assert boundary is not None
        assert abs(boundary - int(1.0 * SAMPLE_RATE)) < SAMPLE_RATE * 0.15

    def test_no_boundary_on_noise_only(self) -> None:
        audio = make_flat_audio(3.0, 0.0002)
        assert find_utterance_boundary(audio, silence_sec=1.5) is None


class TestPauseTracker:
    """Stateful pause detector used while listening in streaming mode."""

    def test_pause_after_speech_and_quiet_period(self) -> None:
        tracker = PauseTracker(silence_sec=1.5, poll_sec=0.2)
        for _ in range(3):
            tracker.update(0.0002, 0.05)
        paused = False
        for _ in range(12):
            if tracker.update(0.0002, 0.0002):
                paused = True
                break
        assert paused

    def test_no_pause_without_prior_speech(self) -> None:
        tracker = PauseTracker(silence_sec=1.5, poll_sec=0.2)
        for _ in range(20):
            assert not tracker.update(0.0002, 0.0002)


class TestPauseSensitivitySlider:
    """Pause sensitivity UI maps to drop ratio (legacy multiplier configs still work)."""

    def test_slider_round_trip(self) -> None:
        for slider in (0, 50, 100):
            floor = pause_noise_floor_from_slider(slider)
            assert pause_noise_slider_from_floor(floor) == slider

    def test_legacy_multiplier_maps_to_ratio(self) -> None:
        assert effective_pause_drop_ratio(0.50) == 0.50
        assert 0.10 < effective_pause_drop_ratio(4.0) < 0.90


class TestResample:
    def test_resample_to_whisper_rate(self) -> None:
        src = make_flat_audio(1.0, 0.1, sr=48000)
        out = resample_audio(src, 48000, SAMPLE_RATE)
        assert len(out) == SAMPLE_RATE


class TestAudioRecorderStreaming:
    """Integration: chunk on pause, silent remainder after stop must not re-transcribe."""

    def _recorder_with_audio(self, audio: np.ndarray) -> AudioRecorder:
        rec = AudioRecorder()
        rec.samplerate = SAMPLE_RATE
        rec._capture_samplerate = SAMPLE_RATE
        rec._pause_tracker = PauseTracker(silence_sec=1.5, poll_sec=0.2)
        rec._frames = [audio.reshape(-1, 1)]
        rec._chunk_start_frame = 0
        return rec

    def test_extract_chunk_on_pause(self) -> None:
        audio = speech_then_silence(1.0, 1.6)
        rec = self._recorder_with_audio(audio)
        chunk = rec.extract_chunk(silence_sec=1.5, min_speech_sec=DEFAULT_MIN_SPEECH_SEC)
        assert len(chunk) > 0
        assert has_speech(chunk)
        assert audio_rms(chunk) > 0.01

    def test_remainder_after_chunk_is_not_speech(self) -> None:
        audio = speech_then_silence(1.0, 1.6)
        rec = self._recorder_with_audio(audio)
        chunk = rec.extract_chunk(silence_sec=1.5)
        assert len(chunk) > 0
        # Mic still open after pause: only trailing silence is captured next.
        extra_silence = make_flat_audio(1.0, 0.0002)
        rec._frames.append(extra_silence.reshape(-1, 1))
        remainder = rec.extract_remainder()
        assert len(remainder) > 0
        assert not has_speech(remainder)

    def test_try_extract_chunk_with_incremental_frames(self) -> None:
        rec = AudioRecorder()
        rec.samplerate = SAMPLE_RATE
        rec._capture_samplerate = SAMPLE_RATE
        rec._pause_tracker = PauseTracker(silence_sec=1.5, poll_sec=0.2)
        rec._frames = []
        rec._chunk_start_frame = 0

        speech = make_flat_audio(1.0, 0.05)
        frame_samples = int(0.2 * SAMPLE_RATE)
        for start in range(0, len(speech), frame_samples):
            rec._frames.append(speech[start : start + frame_samples].reshape(-1, 1))
            rec.try_extract_chunk(silence_sec=1.5)

        silence = make_flat_audio(0.2, 0.0002)
        chunk = np.array([], dtype=np.float32)
        for _ in range(12):
            rec._frames.append(silence.reshape(-1, 1))
            chunk = rec.try_extract_chunk(silence_sec=1.5)
            if len(chunk) > 0:
                break
        assert len(chunk) > 0
        assert has_speech(chunk)
