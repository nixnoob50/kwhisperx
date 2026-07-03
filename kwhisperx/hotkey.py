"""Global hotkey listener via pynput."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from pynput import keyboard

from kwhisperx.config import hotkey_key_set, hotkey_to_pynput

log = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(
        self,
        hotkey: str,
        mode: str,
        on_toggle: Callable[[], None],
        on_hold_start: Callable[[], None],
        on_hold_stop: Callable[[], None],
    ) -> None:
        self.hotkey = hotkey
        self.mode = mode
        self.on_toggle = on_toggle
        self.on_hold_start = on_hold_start
        self.on_hold_stop = on_hold_stop
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._holding = False
        self._target_keys = hotkey_key_set(hotkey)
        self._pressed: set[str] = set()

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="hotkey")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def update(self, hotkey: str, mode: str) -> None:
        self.hotkey = hotkey
        self.mode = mode
        self._target_keys = hotkey_key_set(hotkey)
        self.start()

    def _run(self) -> None:
        if self.mode == "hold":
            self._run_hold()
        else:
            self._run_toggle()

    def _run_toggle(self) -> None:
        pynput_key = hotkey_to_pynput(self.hotkey)

        def on_activate() -> None:
            try:
                self.on_toggle()
            except Exception:
                log.exception("toggle callback failed")

        hotkeys = keyboard.GlobalHotKeys({pynput_key: on_activate})
        with hotkeys:
            while not self._stop.is_set():
                self._stop.wait(0.2)

    def _run_hold(self) -> None:
        listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        listener.start()
        try:
            while not self._stop.is_set():
                self._stop.wait(0.2)
        finally:
            listener.stop()

    def _on_press(self, key) -> None:
        name = _key_name(key)
        if not name:
            return
        self._pressed.add(name)
        if not self._holding and self._target_keys.issubset(self._pressed):
            self._holding = True
            try:
                self.on_hold_start()
            except Exception:
                log.exception("hold start callback failed")

    def _on_release(self, key) -> None:
        name = _key_name(key)
        if name:
            self._pressed.discard(name)
        if self._holding and not self._target_keys.issubset(self._pressed):
            self._holding = False
            try:
                self.on_hold_stop()
            except Exception:
                log.exception("hold stop callback failed")


def _key_name(key) -> str | None:
    if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
        return "ctrl"
    if key == keyboard.Key.alt_l or key == keyboard.Key.alt_r or key == keyboard.Key.alt_gr:
        return "alt"
    if key == keyboard.Key.shift_l or key == keyboard.Key.shift_r:
        return "shift"
    if key == keyboard.Key.cmd or key == keyboard.Key.cmd_r:
        return "super"
    if hasattr(key, "char") and key.char:
        return key.char.lower()
    if hasattr(key, "name") and key.name:
        return key.name.lower()
    return None
