# KWhisperX

Voice dictation tray app for **Kubuntu on X11**. Press a global hotkey to start/stop listening; when you stop, faster-whisper transcribes locally and the text is pasted into whatever window had focus.

**Version:** 0.3.6 — see [CHANGELOG.md](CHANGELOG.md) for release history.

## Requirements

- **X11** session (`XDG_SESSION_TYPE=x11`) — Wayland is not supported
- **xdotool** — required to paste transcribed text into the focused window
- Python 3.10+ with venv, PortAudio (`libportaudio2`) for the microphone

System packages (Kubuntu):

```bash
sudo apt install python3-venv python3-dev xdotool libportaudio2
```

Without `xdotool`, the app can record and transcribe but **cannot inject text**.

## Install

```bash
git clone <repo-url> kwhisperx
cd kwhisperx
./setup.sh
```

## Run

```bash
./run.sh
```

The app appears in the system tray. Default hotkey: **Ctrl+Alt+Space** (toggle mode).

## Tests

Unit tests cover regressions (silence detection, streaming chunks, injection modes, tray icons, single-instance lock). No microphone or GPU required:

```bash
./run_tests.sh
```

Install dev dependencies first if needed: `.venv/bin/pip install pytest` or `.venv/bin/pip install -e ".[dev]"`.

## Usage

1. Click into any text field (browser, editor, terminal, etc.)
2. Press the hotkey to start listening (tray icon changes)
3. Speak
4. Press the hotkey again (toggle) or release the key (hold mode) to stop
5. Transcribed text is pasted into the field that had focus when you started

Right-click the tray icon for **Settings** (hotkey, mode, model, microphone, injection method, autostart).

## Hotkey modes

- **Toggle** — press once to start, again to stop and insert
- **Hold** — hold key while speaking, release to stop and insert

## Settings

| Setting | Default |
|---|---|
| Hotkey | Ctrl+Alt+Space |
| Mode | toggle |
| Model | base |
| Compute | auto (CUDA if available), or cpu / cuda / amd |

### AMD GPU (ROCm)

CUDA settings are unchanged for NVIDIA. For AMD, choose **amd** in Settings → Compute.

Requirements (one-time, outside the app):

1. Install [ROCm](https://rocm.docs.amd.com/) on your system
2. Install the **ROCm build of CTranslate2** (from the [CTranslate2 v4.7.1+ release](https://github.com/OpenNMT/CTranslate2/releases)) — the default pip wheel is NVIDIA-only
3. Reinstall faster-whisper in the venv if needed: `.venv/bin/pip install faster-whisper`

CTranslate2 still uses `device="cuda"` internally for ROCm. KWhisperX sets `CT2_CUDA_ALLOCATOR=cub_caching` when **amd** is selected (helps many RDNA2 cards).
| Language | en |
| Injection | auto (clipboard → terminal → keystrokes) |
| Streaming | off (optional; keystrokes / terminal only) |

Config file: `~/.config/kwhisperx/config.json`

### Streaming (optional)

For **keystrokes** or **terminal** injection, enable **Inject on pauses (streaming)** in Settings. While listening, KWhisperX transcribes and types each phrase after you pause (default 1.5 s). Release the hotkey to flush any remaining speech.

Streaming uses more CPU/GPU than batch mode. Leave it off for the default record-then-insert workflow.

## Autostart

Enable **Start at login** in Settings. This writes `~/.config/autostart/kwhisperx.desktop` pointing to `./run.sh`.

## D-Bus (optional)

If running, external tools can call:

- `org.kwhisperx.App` / `/App` — methods `toggle`, `start`, `stop`

## Local / offline operation

**All dictation runs on your machine.** No audio or text is sent to any cloud service.

The only network use is a **one-time model download** during `./setup.sh`. After that, `./run.sh` sets `HF_HUB_OFFLINE=1` and loads models from:

`~/.local/share/kwhisperx/models`

To download another model (e.g. after changing model in Settings):

```bash
.venv/bin/python -m kwhisperx.download_models base.en
```

## Troubleshooting

- **Requires X11** — check with `echo $XDG_SESSION_TYPE` (should print `x11`)
- **xdotool missing** — `sudo apt install xdotool`
- **No microphone** — check Settings → Microphone; verify with `arecord -l`
- **Model not installed** — run `.venv/bin/python -m kwhisperx.download_models <model>` (see above)
- **Hotkey conflicts** — change hotkey in Settings if it clashes with KDE shortcuts
- **Terminal paste** — set Injection to `terminal` for Konsole (`Ctrl+Shift+V`)

## License

KWhisperX is free software licensed under the [GNU General Public License v3.0 or later](LICENSE).

Runtime dependencies (PyQt6, faster-whisper, pynput, etc.) are governed by their own licenses. Whisper models downloaded during setup are subject to separate terms on Hugging Face.

## Development

See [agent.md](agent.md) and [plan.md](plan.md).
