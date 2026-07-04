# Changelog

All notable changes to KWhisperX are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
