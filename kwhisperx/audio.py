"""Microphone capture via sounddevice."""

from __future__ import annotations

import numpy as np
import sounddevice as sd


SAMPLE_RATE = 16000
# Below this RMS level the recording is effectively silent (mic disabled, wrong device, etc.)
MIN_AUDIO_RMS = 1e-4


def has_audio(audio: np.ndarray, threshold: float = MIN_AUDIO_RMS) -> bool:
    """Return True if the recording contains measurable signal."""
    if audio is None or len(audio) == 0:
        return False
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    return rms >= threshold


class AudioRecorder:
    def __init__(self, device: int | None = None, samplerate: int = SAMPLE_RATE) -> None:
        self.device = device
        self.samplerate = samplerate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            pass
        self._frames.append(indata.copy())

    def start(self) -> None:
        self._frames = []
        self._stream = sd.InputStream(
            device=self.device,
            channels=1,
            samplerate=self.samplerate,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is None:
            return np.array([], dtype=np.float32)
        self._stream.stop()
        self._stream.close()
        self._stream = None
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
