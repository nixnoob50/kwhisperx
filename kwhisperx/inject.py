"""X11 text injection via xdotool."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

log = logging.getLogger(__name__)


def get_focused_window_id() -> str | None:
    if not shutil.which("xdotool"):
        return None
    result = subprocess.run(
        ["xdotool", "getwindowfocus"],
        capture_output=True,
        text=True,
        check=False,
    )
    wid = result.stdout.strip()
    if not wid or wid == "0":
        return None
    return wid


def _run_xdotool(args: list[str]) -> bool:
    result = subprocess.run(["xdotool", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        log.debug("xdotool failed: %s stderr=%s", args, result.stderr.strip())
        return False
    return True


def _paste_keys(method: str) -> list[str]:
    if method == "terminal":
        return ["--clearmodifiers", "ctrl+shift+v"]
    if method == "keystrokes":
        return []
    return ["--clearmodifiers", "ctrl+v"]


def uses_clipboard(method: str) -> bool:
    """True when injection may copy text to the system clipboard."""
    return method in ("auto", "clipboard", "terminal")


def supports_chunk_injection(method: str) -> bool:
    """True when pause-based streaming injection is supported."""
    return method in ("keystrokes", "terminal")


def inject_append(
    text: str,
    window_id: str | None,
    method: str,
    *,
    first_chunk: bool,
) -> bool:
    """Append transcribed text during a streaming session (keystrokes / terminal)."""
    if not text.strip():
        return True
    if not supports_chunk_injection(method):
        return False
    if not shutil.which("xdotool"):
        log.error("xdotool not found")
        return False
    if not window_id:
        log.error("No target window id")
        return False
    prefix = "" if first_chunk else " "
    return _inject_keystrokes(prefix + text, window_id)


def inject_text(
    text: str,
    window_id: str | None,
    method: str = "auto",
    *,
    clipboard=None,
) -> bool:
    if not text.strip():
        return True
    if not shutil.which("xdotool"):
        log.error("xdotool not found")
        return False
    if not window_id:
        log.error("No target window id")
        return False

    methods = _methods_to_try(method)
    for m in methods:
        if m == "keystrokes":
            if _inject_keystrokes(text, window_id):
                return True
            continue
        if clipboard is not None:
            clipboard.setText(text)
        if _inject_paste(text, window_id, m):
            return True
    return False


def _methods_to_try(method: str) -> list[str]:
    if method == "auto":
        return ["clipboard", "terminal", "keystrokes"]
    return [method]


def _inject_paste(text: str, window_id: str, method: str) -> bool:
    keys = _paste_keys(method)
    if not keys:
        return False

    current = get_focused_window_id()

    # Try direct window paste first
    if _run_xdotool(["key", "--window", window_id, *keys]):
        return True

    # Focus-swap fallback
    if current and current != window_id:
        if not _run_xdotool(["windowfocus", "--sync", window_id]):
            return False
        time.sleep(0.05)
        ok = _run_xdotool(["key", *keys])
        _run_xdotool(["windowfocus", "--sync", current])
        return ok

    if _run_xdotool(["windowfocus", "--sync", window_id]):
        time.sleep(0.05)
        return _run_xdotool(["key", *keys])
    return False


def _inject_keystrokes(text: str, window_id: str) -> bool:
    # Slow enough for Qt/GTK apps to consume events in order; --file avoids
    # argv parsing issues with commas and other punctuation from Whisper.
    time.sleep(0.1)
    result = subprocess.run(
        [
            "xdotool",
            "type",
            "--window",
            window_id,
            "--delay",
            "15",
            "--clearmodifiers",
            "--file",
            "-",
        ],
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        log.debug("xdotool type failed stderr=%s", result.stderr.strip())
        return False
    return True
