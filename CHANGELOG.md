# Changelog

All notable changes to KWhisperX are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.5] - 2026-07-04

### Added
- Unit test suite (`tests/`, 46 tests) and `./run_tests.sh` runner covering streaming, injection, tray icons, and other regressions

### Fixed
- Streaming stop injecting hallucinated text from silent remainder after a pause chunk was already inserted
- Do not amplify near-silent audio before Whisper transcription

## [0.3.4] - 2026-07-04

### Added
- **Pause sensitivity** slider in Settings (streaming mode) to tune how much quieter a pause must be vs. speech
- `setup.sh` checks for `xdotool` before install; README documents it as a required dependency

### Changed
- Default microphone routes through PulseAudio/PipeWire instead of raw ALSA hardware
- Microphone opens at a device-native sample rate and resamples to 16 kHz for Whisper
- Streaming pause detection uses a stateful tracker (session speech peak) instead of re-scanning the full buffer
- Quiet captures are normalized before transcription

### Fixed
- `PortAudioError: Invalid sample rate` on hardware that rejects 16 kHz capture
- Streaming pause detection failing when mic RMS stays near room-noise level during pauses
- Missing `numpy` import in `transcribe.py` after audio normalization was added

## [0.3.3] - 2026-07-03

### Changed
- Tray icons: white badge (idle) and red badge (listening) using the theme microphone for visibility on dark panels

### Fixed
- Tray icon missing-icon flash on KDE when starting/stopping (status in tooltip; no notification hijack)
- Blank idle tray icon on startup

## [0.3.2] - 2026-07-03

### Fixed
- Streaming pause detection rewritten with 50 ms window scan (finds speech end vs mic noise floor)
- Diagnostic log every ~2 s while listening in streaming mode (`peak`, `tail_avg`, `threshold`)

## [0.3.1] - 2026-07-03

### Fixed
- Streaming mode crash (`QThread destroyed while still running`) by keeping workers alive until the thread exits
- Pause detection too strict on noisy mics; uses adaptive silence threshold relative to speech level

## [0.3.0] - 2026-07-03

### Added
- Optional **Inject on pauses (streaming)** for keystrokes and terminal injection modes
- Configurable pause duration (1.0–3.0 s); text is appended after each pause while listening continues
- Default remains batch transcribe-on-stop (unchanged behavior when streaming is off)

## [0.2.3] - 2026-07-03

### Added
- Single-instance lock prevents multiple copies running at once (KDE notification if already running)

## [0.2.2] - 2026-07-03

### Fixed
- Keystroke injection typing out of order; use slower delay, `--clearmodifiers`, and stdin `--file -`

## [0.2.1] - 2026-07-03

### Fixed
- Keystroke injection no longer copies transcribed text to the clipboard

## [0.2.0] - 2026-07-03

### Added
- `CHANGELOG.md` and versioning workflow documented in `agent.md`
- `.gitignore` for venv, Python artifacts, and local debug files

### Changed
- Version bumped to 0.2.0 across `pyproject.toml` and `kwhisperx/__init__.py`

## [0.1.0] - 2026-07-03

### Added
- Kubuntu/X11 tray dictation app with faster-whisper
- Global hotkey support (toggle and hold modes) via pynput
- System tray UI with idle, listening, processing, and error states
- Settings dialog: hotkey recorder, model, compute, microphone, injection, autostart
- X11 text injection via xdotool (clipboard, terminal, keystroke fallbacks)
- Local offline Whisper models in `~/.local/share/kwhisperx/models`
- `setup.sh` / `run.sh` launcher scripts with project venv
- AMD (ROCm) compute option alongside CUDA and CPU
- Silent-audio detection with “No audio detected” tray notification
- Automatic app restart when Whisper model or compute backend changes
- Optional D-Bus interface (`org.kwhisperx.App`)
- `plan.md` and `agent.md` project documentation
