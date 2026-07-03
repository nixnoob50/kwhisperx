# Agent guide — KWhisperX

Instructions for AI agents working on this repository.

## Project summary

KWhisperX is a Kubuntu/X11 tray dictation app. It listens for a global hotkey, records audio, transcribes with embedded faster-whisper, and injects text into the previously focused X11 window via xdotool.

See [plan.md](plan.md) for architecture and design rationale.

## Environment

- **Target**: Kubuntu 24.10+ on X11
- **Python**: 3.10+ in project-local `.venv/` (never use system pip for app deps)
- **Launch**: `./run.sh` (after `./setup.sh`)
- **Config**: `~/.config/kwhisperx/config.json`

## System vs venv dependencies

| Source | Packages |
|---|---|
| apt | `python3-venv`, `python3-dev`, `xdotool`, `libportaudio2` |
| pip (venv) | PyQt6, faster-whisper, pynput, sounddevice, numpy |

## Code conventions

- Match existing module boundaries: `config`, `audio`, `transcribe`, `inject`, `hotkey`, `app`, `settings`
- PyQt6 UI runs on the main thread; pynput and transcription use background threads with `pyqtSignal` / `QMetaObject.invokeMethod` for cross-thread calls
- Never call Qt widget methods from pynput or QThread workers directly
- Prefer subprocess + xdotool for X11 injection; keep injection logic in `inject.py`
- Keep faster-whisper lazy-loaded in `transcribe.py`; reload only when model/device settings change
- Config changes that affect hotkey or model require restarting the hotkey listener or reloading the model

## Testing manually

```bash
./setup.sh   # first time only
./run.sh     # starts tray app; check system tray for mic icon
```

Verify on X11: `echo $XDG_SESSION_TYPE` should print `x11`.

## Common pitfalls

- **Focus stealing**: capture window ID at listen *start*, not at inject time
- **Synthetic key rejection**: use clipboard paste first; fall back to focus-swap + keystrokes
- **Hold mode hotkeys**: track modifier keys on press/release; do not use GlobalHotKeys for hold mode
- **Compute**: `auto` detects NVIDIA only; `cuda` for NVIDIA; `amd` for ROCm (requires ROCm CTranslate2 wheel)

## Files to read first

1. [kwhisperx/app.py](kwhisperx/app.py) — state machine and tray
2. [kwhisperx/hotkey.py](kwhisperx/hotkey.py) — toggle vs hold
3. [kwhisperx/inject.py](kwhisperx/inject.py) — X11 text injection
4. [kwhisperx/config.py](kwhisperx/config.py) — settings schema

## Versioning and changelog

**Current version:** see `kwhisperx/__init__.py` (`__version__`) and `pyproject.toml` (`version`). Keep these in sync.

**Whenever you make significant changes**, update all of the following in the same work session:

1. **Bump the version** in both files using [Semantic Versioning](https://semver.org/):
   - **PATCH** (0.2.0 → 0.2.1): bug fixes, minor tweaks
   - **MINOR** (0.2.0 → 0.3.0): new features, backward compatible
   - **MAJOR** (0.2.0 → 1.0.0): breaking changes
2. **Append an entry** to [CHANGELOG.md](CHANGELOG.md) under a new `## [x.y.z] - YYYY-MM-DD` heading with `Added`, `Changed`, `Fixed`, or `Removed` sections as appropriate.

Significant changes include: new user-facing features, behavior changes, bug fixes users would notice, dependency or setup changes, and breaking config/API changes. Trivial edits (typos, comments only) do not require a version bump.

Example changelog entry:

```markdown
## [0.2.1] - 2026-07-04

### Fixed
- Tray icon not updating after failed injection
```

## Do not

- Add Wayland support without explicit request
- Depend on PyKF6/KGlobalAccel Python bindings (not on Kubuntu apt)
- Commit `.venv/` or model cache files
- Create git commits unless the user asks
- Bypass Cursor plan mode by writing code through shell heredocs — ask the user to switch to Agent mode instead

## Cursor workflow

When plan mode is active and implementation is requested, **ask the user to switch to Agent mode** before creating or editing source files. Do not work around editor restrictions via the terminal.
