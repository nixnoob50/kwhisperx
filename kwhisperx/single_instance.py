"""Ensure only one KWhisperX process runs at a time."""

from __future__ import annotations

import logging
import shutil
import subprocess

from PyQt6.QtCore import QLockFile

from kwhisperx.config import CONFIG_DIR

log = logging.getLogger(__name__)

_lock: QLockFile | None = None


def acquire() -> bool:
    """Return True if this process became the sole instance."""
    global _lock
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = CONFIG_DIR / "kwhisperx.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(10_000)
    if not lock.tryLock(100):
        log.error("Another KWhisperX instance is already running")
        return False
    _lock = lock
    return True


def release() -> None:
    global _lock
    if _lock is not None and _lock.isLocked():
        _lock.unlock()
    _lock = None


def notify_already_running() -> None:
    if shutil.which("notify-send"):
        subprocess.run(
            [
                "notify-send",
                "-a",
                "KWhisperX",
                "KWhisperX",
                "Already running in the system tray.",
            ],
            check=False,
        )
