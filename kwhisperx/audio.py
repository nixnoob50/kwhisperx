"""Microphone capture via sounddevice."""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# Below this RMS level the recording is effectively silent (mic disabled, wrong device, etc.)
MIN_AUDIO_RMS = 1e-4
# Minimum RMS to treat as intentional speech (above typical idle mic noise).
MIN_SPEECH_RMS = 3e-4
DEFAULT_MIN_SPEECH_SEC = 0.4
# Analysis window for pause detection (seconds).
VAD_WINDOW_SEC = 0.05


def has_audio(audio: np.ndarray, threshold: float = MIN_AUDIO_RMS) -> bool:
    """Return True if the recording contains measurable signal."""
    if audio is None or len(audio) == 0:
        return False
    rms = audio_rms(audio)
    return rms >= threshold


def audio_rms(audio: np.ndarray) -> float:
    if audio is None or len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def find_utterance_boundary(
    audio: np.ndarray,
    *,
    silence_sec: float = 1.5,
    min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    samplerate: int = SAMPLE_RATE,
) -> int | None:
    """Return sample index where speech ends and sustained silence begins, or None."""
    if audio is None or len(audio) == 0:
        return None

    window = max(1, int(VAD_WINDOW_SEC * samplerate))
    min_speech_samples = int(min_speech_sec * samplerate)
    silence_windows = max(1, int(silence_sec / VAD_WINDOW_SEC))

    n_windows = len(audio) // window
    if n_windows < silence_windows + 2:
        return None

    levels = [audio_rms(audio[i * window : (i + 1) * window]) for i in range(n_windows)]

    # Estimate speech level from windows before the trailing silence region.
    probe = levels[: max(1, n_windows - silence_windows)]
    peak = max(probe)
    if peak < MIN_SPEECH_RMS:
        return None

    # Window is "silent" when well below the loudest speech in this utterance.
    threshold = max(MIN_AUDIO_RMS * 2, peak * 0.20)

    silent_run = 0
    for level in reversed(levels):
        if level <= threshold:
            silent_run += 1
        else:
            break

    if silent_run < silence_windows:
        return None

    speech_end = (n_windows - silent_run) * window
    if speech_end < min_speech_samples:
        return None

    speech = audio[:speech_end]
    if audio_rms(speech) < MIN_SPEECH_RMS:
        return None

    return speech_end


class AudioRecorder:
    def __init__(self, device: int | None = None, samplerate: int = SAMPLE_RATE) -> None:
        self.device = device
        self.samplerate = samplerate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._chunk_start_frame = 0
        self._last_vad_log = 0.0

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            pass
        with self._lock:
            self._frames.append(indata.copy())

    def start(self) -> None:
        with self._lock:
            self._frames = []
            self._chunk_start_frame = 0
            self._last_vad_log = 0.0
        self._stream = sd.InputStream(
            device=self.device,
            channels=1,
            samplerate=self.samplerate,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def _concat_from(self, start_frame: int) -> np.ndarray:
        if start_frame >= len(self._frames):
            return np.array([], dtype=np.float32)
        return np.concatenate(self._frames[start_frame:], axis=0).flatten()

    def _current_audio(self) -> np.ndarray:
        with self._lock:
            return self._concat_from(self._chunk_start_frame)

    def _boundary(
        self,
        silence_sec: float = 1.5,
        min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    ) -> int | None:
        audio = self._current_audio()
        return find_utterance_boundary(
            audio,
            silence_sec=silence_sec,
            min_speech_sec=min_speech_sec,
            samplerate=self.samplerate,
        )

    def log_pause_diagnostics(
        self,
        silence_sec: float = 1.5,
        min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    ) -> None:
        """Log VAD levels occasionally to help tune pause detection."""
        import time

        now = time.monotonic()
        if now - self._last_vad_log < 2.0:
            return
        self._last_vad_log = now

        audio = self._current_audio()
        if len(audio) < int(min_speech_sec * self.samplerate):
            return

        window = max(1, int(VAD_WINDOW_SEC * self.samplerate))
        n_windows = len(audio) // window
        if n_windows < 2:
            return

        levels = [audio_rms(audio[i * window : (i + 1) * window]) for i in range(n_windows)]
        silence_windows = max(1, int(silence_sec / VAD_WINDOW_SEC))
        probe = levels[: max(1, n_windows - silence_windows)]
        peak = max(probe)
        threshold = max(MIN_AUDIO_RMS * 2, peak * 0.20)
        tail = levels[-min(silence_windows, len(levels)) :]
        tail_avg = sum(tail) / len(tail) if tail else 0.0

        log.info(
            "Pause check: %.1fs buffered, peak=%.5f tail_avg=%.5f threshold=%.5f",
            len(audio) / self.samplerate,
            peak,
            tail_avg,
            threshold,
        )

    def poll_utterance_end(
        self,
        silence_sec: float = 1.5,
        min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    ) -> bool:
        """Return True when trailing silence follows measurable speech in the current chunk."""
        return self._boundary(silence_sec, min_speech_sec) is not None

    def extract_chunk(
        self,
        silence_sec: float = 1.5,
        min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    ) -> np.ndarray:
        """Extract speech up to the detected pause and advance the chunk cursor."""
        with self._lock:
            audio = self._concat_from(self._chunk_start_frame)
            boundary = find_utterance_boundary(
                audio,
                silence_sec=silence_sec,
                min_speech_sec=min_speech_sec,
                samplerate=self.samplerate,
            )
            if boundary is None:
                return np.array([], dtype=np.float32)
            chunk = audio[:boundary]
            self._chunk_start_frame = len(self._frames)
        return chunk

    def extract_remainder(self) -> np.ndarray:
        """Extract all audio since the last chunk boundary."""
        with self._lock:
            audio = self._concat_from(self._chunk_start_frame)
            self._chunk_start_frame = len(self._frames)
        return audio

    def stop_stream(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None

    def stop(self) -> np.ndarray:
        if self._stream is None:
            with self._lock:
                if not self._frames:
                    return np.array([], dtype=np.float32)
                return np.concatenate(self._frames, axis=0).flatten()
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._frames:
                return np.array([], dtype=np.float32)
            return np.concatenate(self._frames, axis=0).flatten()

    @staticmethod
    def list_input_devices() -> list[tuple[int, str]]:
        devices: list[tuple[int, str]] = []
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append((i, dev["name"]))
        return devices
