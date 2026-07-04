"""Microphone capture via sounddevice."""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# Fallback order when the device rejects 16 kHz (common on ALSA hardware).
_COMMON_INPUT_RATES = (48000, 44100, 32000, 22050, 16000, 8000)
# Below this RMS level the recording is effectively silent (mic disabled, wrong device, etc.)
MIN_AUDIO_RMS = 1e-4
# Minimum RMS to treat as intentional speech (above typical idle mic noise).
MIN_SPEECH_RMS = 3e-4
DEFAULT_MIN_SPEECH_SEC = 0.4
# Analysis window for pause detection (seconds).
VAD_WINDOW_SEC = 0.05
DEFAULT_PAUSE_NOISE_FLOOR = 0.50
PAUSE_NOISE_FLOOR_MIN = 0.5
PAUSE_NOISE_FLOOR_MAX = 8.0


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


def resample_audio(
    audio: np.ndarray,
    from_rate: int,
    to_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Linear resample to Whisper's expected 16 kHz mono float32."""
    if from_rate == to_rate or len(audio) == 0:
        return audio
    target_len = int(round(len(audio) * to_rate / from_rate))
    if target_len <= 0:
        return np.array([], dtype=np.float32)
    indices = np.linspace(0, len(audio) - 1, target_len)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


_PREFERRED_HOST_DEVICES = ("pulse", "pipewire", "default")


def resolve_input_device(device: int | None) -> int | None:
    """Prefer the desktop audio server when no mic is configured (Linux/ALSA)."""
    if device is not None:
        return device
    for needle in _PREFERRED_HOST_DEVICES:
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
                log.info("Using microphone %r (index %d)", dev["name"], idx)
                return idx
    log.info("Using PortAudio system default microphone")
    return None


def input_device_name(device: int | None) -> str:
    try:
        return str(sd.query_devices(device, kind="input").get("name", device))
    except sd.PortAudioError:
        return str(device)


def prepare_for_transcription(audio: np.ndarray) -> np.ndarray:
    """Boost very quiet captures so Whisper can pick up speech."""
    if audio is None or len(audio) == 0:
        return audio
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    if audio_rms(audio) < MIN_SPEECH_RMS:
        return audio
    peak = float(np.max(np.abs(audio)))
    if 1e-8 < peak < 0.12:
        audio = audio * (0.95 / peak)
    return audio


def resolve_input_samplerate(device: int | None) -> int:
    """Return a sample rate the chosen input device can open."""
    dev_info = sd.query_devices(device, kind="input")
    default_rate = int(dev_info["default_samplerate"])
    seen: set[int] = set()
    candidates: list[int] = []
    for rate in (SAMPLE_RATE, default_rate, *_COMMON_INPUT_RATES):
        if rate not in seen:
            seen.add(rate)
            candidates.append(rate)

    for rate in candidates:
        try:
            sd.check_input_settings(
                device=device,
                channels=1,
                dtype="float32",
                samplerate=rate,
            )
            if rate != SAMPLE_RATE:
                log.info(
                    "Microphone opened at %d Hz (resampled to %d Hz for Whisper)",
                    rate,
                    SAMPLE_RATE,
                )
            return rate
        except sd.PortAudioError:
            continue

    name = dev_info.get("name", device)
    raise sd.PortAudioError(f"No supported input sample rate for device {name!r}")


def _estimate_noise_floor(levels: list[float]) -> float:
    """Estimate room noise from the quietest windows in the buffer."""
    if not levels:
        return MIN_AUDIO_RMS
    sorted_levels = sorted(levels)
    quiet = sorted_levels[: max(1, len(sorted_levels) // 4)]
    return max(MIN_AUDIO_RMS, sum(quiet) / len(quiet))


def pause_noise_floor_from_slider(slider: int) -> float:
    """Map slider 0–100 to drop ratio 0.10–0.90 (legacy field name kept in config)."""
    clamped = max(0, min(100, slider))
    return 0.10 + (clamped / 100.0) * 0.80


def pause_noise_slider_from_floor(floor: float) -> int:
    """Map drop ratio (or legacy multiplier) back to slider 0–100."""
    ratio = effective_pause_drop_ratio(floor)
    return round((ratio - 0.10) / 0.80 * 100)


def effective_pause_drop_ratio(pause_noise_floor: float) -> float:
    """Return pause drop ratio; accept legacy multiplier values from older configs."""
    if pause_noise_floor <= 1.0:
        return max(0.10, min(0.95, pause_noise_floor))
    # Legacy noise-floor multiplier (0.5–8.0) from earlier releases.
    span = PAUSE_NOISE_FLOOR_MAX - PAUSE_NOISE_FLOOR_MIN
    return 0.12 + (pause_noise_floor - PAUSE_NOISE_FLOOR_MIN) / span * 0.78


def _pause_silence_threshold(peak: float, pause_noise_floor: float) -> float:
    """Pause windows must fall below this fraction of the loudest recent speech."""
    drop_ratio = effective_pause_drop_ratio(pause_noise_floor)
    return max(MIN_AUDIO_RMS * 2, peak * drop_ratio)


class PauseTracker:
    """Stateful pause detector for streaming; tracks session speech peak across pauses."""

    def __init__(
        self,
        *,
        silence_sec: float = 1.5,
        min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
        pause_noise_floor: float = DEFAULT_PAUSE_NOISE_FLOOR,
        poll_sec: float = 0.2,
    ) -> None:
        self.silence_sec = silence_sec
        self.min_speech_sec = min_speech_sec
        self.drop_ratio = effective_pause_drop_ratio(pause_noise_floor)
        self.poll_sec = poll_sec
        self._session_peak = 0.0
        self._speech_sec = 0.0
        self._quiet_sec = 0.0

    def reset(self) -> None:
        self._session_peak = 0.0
        self._speech_sec = 0.0
        self._quiet_sec = 0.0

    @property
    def session_peak(self) -> float:
        return self._session_peak

    @property
    def quiet_sec(self) -> float:
        return self._quiet_sec

    @property
    def speech_sec(self) -> float:
        return self._speech_sec

    def threshold(self) -> float:
        return _pause_silence_threshold(self._session_peak, self.drop_ratio)

    def update(self, recent_rms: float, speech_level: float) -> bool:
        """Advance state from recent audio; return True when pause ends speech."""
        if speech_level > MIN_SPEECH_RMS:
            if speech_level >= self._session_peak * 0.15:
                self._session_peak = max(self._session_peak * 0.92, speech_level)

        threshold = self.threshold()
        if self._session_peak < MIN_SPEECH_RMS:
            return False

        level = max(recent_rms, speech_level)
        if level > threshold:
            self._speech_sec += self.poll_sec
            self._quiet_sec = 0.0
            return False

        if self._speech_sec < self.min_speech_sec:
            return False

        self._quiet_sec += self.poll_sec
        return self._quiet_sec >= self.silence_sec


def find_utterance_boundary(
    audio: np.ndarray,
    *,
    silence_sec: float = 1.5,
    min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    samplerate: int = SAMPLE_RATE,
    pause_noise_floor: float = DEFAULT_PAUSE_NOISE_FLOOR,
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
    pre = levels[:-silence_windows]
    tail = levels[-silence_windows:]
    peak = max(pre)
    noise_floor = _estimate_noise_floor(levels)
    if peak < max(MIN_SPEECH_RMS, noise_floor * 2.5):
        return None

    silence_threshold = _pause_silence_threshold(peak, pause_noise_floor)

    if any(level > silence_threshold for level in tail):
        return None

    speech_windows = sum(1 for level in pre if level > silence_threshold)
    if speech_windows * window < min_speech_samples:
        return None

    speech_end = (n_windows - silence_windows) * window
    if audio_rms(audio[:speech_end]) < MIN_SPEECH_RMS:
        return None

    return speech_end


def has_speech(
    audio: np.ndarray,
    *,
    min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    samplerate: int = SAMPLE_RATE,
    pause_noise_floor: float = DEFAULT_PAUSE_NOISE_FLOOR,
) -> bool:
    """True when the buffer contains enough active speech (not just mic noise or trailing silence)."""
    if audio is None or len(audio) == 0:
        return False

    window = max(1, int(VAD_WINDOW_SEC * samplerate))
    min_speech_samples = int(min_speech_sec * samplerate)
    if len(audio) < min_speech_samples:
        return False

    n_windows = len(audio) // window
    if n_windows < 1:
        return False

    levels = [audio_rms(audio[i * window : (i + 1) * window]) for i in range(n_windows)]
    peak = max(levels)
    noise_floor = _estimate_noise_floor(levels)
    threshold = _pause_silence_threshold(peak, pause_noise_floor)
    speech_samples = sum(window for level in levels if level > threshold)
    if speech_samples >= min_speech_samples:
        return True
    return False


class AudioRecorder:
    def __init__(
        self,
        device: int | None = None,
        samplerate: int = SAMPLE_RATE,
        pause_noise_floor: float = DEFAULT_PAUSE_NOISE_FLOOR,
    ) -> None:
        self.device = device
        self.samplerate = samplerate
        self.pause_noise_floor = pause_noise_floor
        self._input_device: int | None = device
        self._capture_samplerate = samplerate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._chunk_start_frame = 0
        self._last_vad_log = 0.0
        self._pause_tracker: PauseTracker | None = None

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
        self._pause_tracker = PauseTracker(pause_noise_floor=self.pause_noise_floor)
        self._input_device = resolve_input_device(self.device)
        self._capture_samplerate = resolve_input_samplerate(self._input_device)
        log.info(
            "Opening microphone %r at %d Hz",
            input_device_name(self._input_device),
            self._capture_samplerate,
        )
        self._stream = sd.InputStream(
            device=self._input_device,
            channels=1,
            samplerate=self._capture_samplerate,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def _concat_from(self, start_frame: int) -> np.ndarray:
        if start_frame >= len(self._frames):
            return np.array([], dtype=np.float32)
        return np.concatenate(self._frames[start_frame:], axis=0).flatten()

    def _to_whisper_rate(self, audio: np.ndarray) -> np.ndarray:
        return resample_audio(audio, self._capture_samplerate, self.samplerate)

    def _current_audio(self) -> np.ndarray:
        with self._lock:
            return self._to_whisper_rate(self._concat_from(self._chunk_start_frame))

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
            pause_noise_floor=self.pause_noise_floor,
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

        recent = audio[-max(1, int(0.2 * self.samplerate)) :]
        recent_rms = audio_rms(recent)
        speech_level = self._speech_level(audio)
        tracker = self._pause_tracker
        if tracker is None:
            return

        log.info(
            "Pause check: %.1fs buffered, recent=%.5f speech_level=%.5f session_peak=%.5f "
            "threshold=%.5f drop=%.0f%% speech=%.1fs quiet=%.1fs/%.1fs",
            len(audio) / self.samplerate,
            recent_rms,
            speech_level,
            tracker.session_peak,
            tracker.threshold(),
            tracker.drop_ratio * 100,
            tracker.speech_sec,
            tracker.quiet_sec,
            silence_sec,
        )

    def _recent_rms(self, audio: np.ndarray) -> float:
        window = max(1, int(0.2 * self.samplerate))
        if len(audio) < window:
            return audio_rms(audio)
        return audio_rms(audio[-window:])

    def _speech_level(self, audio: np.ndarray) -> float:
        """Loudest 50 ms window in the last second (for peak tracking)."""
        window = max(1, int(VAD_WINDOW_SEC * self.samplerate))
        tail = audio[-int(self.samplerate) :]
        if len(tail) < window:
            return audio_rms(tail)
        return max(audio_rms(tail[i : i + window]) for i in range(0, len(tail) - window + 1, window))

    def try_extract_chunk(
        self,
        silence_sec: float = 1.5,
        min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    ) -> np.ndarray:
        """Atomically detect a pause and return speech up to it, or an empty array."""
        tracker = self._pause_tracker
        if tracker is None:
            return np.array([], dtype=np.float32)

        if (
            tracker.silence_sec != silence_sec
            or tracker.min_speech_sec != min_speech_sec
        ):
            tracker.silence_sec = silence_sec
            tracker.min_speech_sec = min_speech_sec

        with self._lock:
            audio = self._to_whisper_rate(self._concat_from(self._chunk_start_frame))
            if len(audio) < int(min_speech_sec * self.samplerate):
                return np.array([], dtype=np.float32)

            if not tracker.update(self._recent_rms(audio), self._speech_level(audio)):
                return np.array([], dtype=np.float32)

            silence_samples = int(silence_sec * self.samplerate)
            if len(audio) <= silence_samples:
                tracker.reset()
                return np.array([], dtype=np.float32)

            chunk = audio[:-silence_samples]
            if len(chunk) < int(min_speech_sec * self.samplerate):
                tracker.reset()
                return np.array([], dtype=np.float32)

            self._chunk_start_frame = len(self._frames)
            self._trim_processed_frames()
            tracker.reset()
        return chunk

    def _trim_processed_frames(self) -> None:
        """Drop captured frames that have already been chunked."""
        if self._chunk_start_frame <= 0:
            return
        if self._chunk_start_frame >= len(self._frames):
            self._frames = []
        else:
            self._frames = self._frames[self._chunk_start_frame :]
        self._chunk_start_frame = 0

    def extract_chunk(
        self,
        silence_sec: float = 1.5,
        min_speech_sec: float = DEFAULT_MIN_SPEECH_SEC,
    ) -> np.ndarray:
        """Extract speech up to the detected pause and advance the chunk cursor."""
        with self._lock:
            audio = self._to_whisper_rate(self._concat_from(self._chunk_start_frame))
            boundary = find_utterance_boundary(
                audio,
                silence_sec=silence_sec,
                min_speech_sec=min_speech_sec,
                samplerate=self.samplerate,
                pause_noise_floor=self.pause_noise_floor,
            )
            if boundary is None:
                return np.array([], dtype=np.float32)
            chunk = audio[:boundary]
            self._chunk_start_frame = len(self._frames)
            self._trim_processed_frames()
        return chunk

    def extract_remainder(self) -> np.ndarray:
        """Extract all audio since the last chunk boundary."""
        with self._lock:
            audio = self._to_whisper_rate(self._concat_from(self._chunk_start_frame))
            self._chunk_start_frame = len(self._frames)
            self._trim_processed_frames()
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
                return self._to_whisper_rate(np.concatenate(self._frames, axis=0).flatten())
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._frames:
                return np.array([], dtype=np.float32)
            return self._to_whisper_rate(np.concatenate(self._frames, axis=0).flatten())

    @staticmethod
    def list_input_devices() -> list[tuple[int, str]]:
        devices: list[tuple[int, str]] = []
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append((i, dev["name"]))
        return devices
