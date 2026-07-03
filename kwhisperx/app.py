"""Main tray application and state machine."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QClipboard, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from kwhisperx.audio import AudioRecorder, has_audio
from kwhisperx.config import Config
from kwhisperx.dbus_service import DbusService
from kwhisperx.hotkey import HotkeyManager
from kwhisperx.inject import get_focused_window_id, inject_text
from kwhisperx.settings import SettingsDialog
from kwhisperx.transcribe import configure_offline_mode, transcribe

log = logging.getLogger(__name__)


class TranscribeWorker(QThread):
    finished_text = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        audio: np.ndarray,
        model_size: str,
        device: str,
        language: str,
        models_path: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.audio = audio
        self.model_size = model_size
        self.device = device
        self.language = language
        self.models_path = models_path

    def run(self) -> None:
        try:
            text = transcribe(
                self.audio,
                model_size=self.model_size,
                device=self.device,
                language=self.language,
                models_path=self.models_path,
            )
            self.finished_text.emit(text)
        except Exception as exc:
            log.exception("transcription failed")
            self.failed.emit(str(exc))


class DictationApp(QObject):
    state_changed = pyqtSignal(str)
    _hotkey_toggle = pyqtSignal()
    _hotkey_hold_start = pyqtSignal()
    _hotkey_hold_stop = pyqtSignal()

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.state = "idle"
        self._target_window: str | None = None
        self._recorder = AudioRecorder(device=config.microphone)
        self._worker: TranscribeWorker | None = None
        self._hotkeys: HotkeyManager | None = None
        self._tray: QSystemTrayIcon | None = None
        self._dbus = DbusService(self, parent=self)
        self._hotkey_toggle.connect(self.toggle_listening)
        self._hotkey_hold_start.connect(self.start_listening)
        self._hotkey_hold_stop.connect(self.stop_listening)

    def setup_tray(self, app: QApplication) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.error("System tray not available")
            sys.exit(1)

        self._tray = QSystemTrayIcon(self)
        self._update_icon()
        self._tray.setToolTip("KWhisperX — idle")

        menu = QMenu()
        listen_action = QAction("Start listening", menu)
        listen_action.triggered.connect(self.toggle_listening)
        menu.addAction(listen_action)
        menu.addSeparator()

        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(lambda: self.open_settings(app))
        menu.addAction(settings_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(app.quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self._hotkeys = HotkeyManager(
            hotkey=self.config.hotkey,
            mode=self.config.hotkey_mode,
            on_toggle=self._hotkey_toggle.emit,
            on_hold_start=self._hotkey_hold_start.emit,
            on_hold_stop=self._hotkey_hold_stop.emit,
        )
        self._hotkeys.start()
        if not self._dbus.register():
            log.info("D-Bus control unavailable; tray and hotkey still work")

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_listening()

    def _set_state(self, state: str, message: str = "") -> None:
        self.state = state
        self.state_changed.emit(state)
        if self._tray:
            self._update_icon()
            tip = f"KWhisperX — {state}"
            self._tray.setToolTip(tip)
            if message:
                self._tray.showMessage("KWhisperX", message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def _update_icon(self) -> None:
        if not self._tray:
            return
        theme_map = {
            "idle": "microphone-sensitivity-muted",
            "listening": "audio-input-microphone",
            "processing": "system-run",
            "error": "dialog-warning",
        }
        name = theme_map.get(self.state, "audio-input-microphone")
        icon = QIcon.fromTheme(name)
        if icon.isNull():
            icon = QIcon.fromTheme("audio-input-microphone")
        self._tray.setIcon(icon)

    def toggle_listening(self) -> None:
        if self.state == "listening":
            self.stop_listening()
        elif self.state == "idle":
            self.start_listening()

    def start_listening(self) -> None:
        if self.state != "idle":
            return
        self._target_window = get_focused_window_id()
        if not self._target_window:
            self._set_state("error", "Could not detect focused window")
            self._set_state("idle")
            return
        try:
            self._recorder = AudioRecorder(device=self.config.microphone)
            self._recorder.start()
        except Exception as exc:
            log.exception("failed to start audio")
            self._set_state("error", f"Microphone error: {exc}")
            self._set_state("idle")
            return
        self._set_state("listening", "Listening…")

    def stop_listening(self) -> None:
        if self.state != "listening":
            return
        audio = self._recorder.stop()
        if not has_audio(audio):
            self._set_state("idle", "No audio detected")
            return
        self._set_state("processing")
        self._worker = TranscribeWorker(
            audio=audio,
            model_size=self.config.model_size,
            device=self.config.device,
            language=self.config.language,
            models_path=self.config.models_dir,
        )
        self._worker.finished_text.connect(self._on_transcribed)
        self._worker.failed.connect(self._on_transcribe_failed)
        self._worker.start()

    def _on_transcribed(self, text: str) -> None:
        if not text.strip():
            self._set_state("idle", "No speech detected")
            return
        app = QApplication.instance()
        if app:
            clipboard: QClipboard = app.clipboard()
            clipboard.setText(text)
        ok = inject_text(text, self._target_window, self.config.injection_method)
        if ok:
            words = len(text.split())
            self._set_state("idle", f"Inserted {words} word(s)")
        else:
            self._set_state("error", "Failed to inject text — copied to clipboard")
            self._set_state("idle")

    def _on_transcribe_failed(self, message: str) -> None:
        self._set_state("error", f"Transcription failed: {message}")
        self._set_state("idle")

    def open_settings(self, app: QApplication) -> None:
        if self.state != "idle":
            if self._tray:
                self._tray.showMessage(
                    "KWhisperX",
                    "Stop listening before opening Settings",
                    QSystemTrayIcon.MessageIcon.Warning,
                    3000,
                )
            return
        if self._worker and self._worker.isRunning():
            self._worker.wait(30000)

        old_device = self.config.device
        old_model = self.config.model_size
        dlg = SettingsDialog(self.config)
        if dlg.exec():
            dlg.apply_to(self.config)
            if self._hotkeys:
                self._hotkeys.update(self.config.hotkey, self.config.hotkey_mode)
            if self.config.device != old_device or self.config.model_size != old_model:
                self._restart_for_model_change(app)

    def _restart_for_model_change(self, app: QApplication) -> None:
        """GPU backend and model loads cannot safely switch in-process (ROCm/CUDA)."""
        run_sh = Path(self.config.install_path) / "run.sh"
        if not run_sh.is_file():
            self._set_state("error", "Restart manually to apply model/compute changes")
            self._set_state("idle")
            return
        self._set_state("idle", "Restarting to apply model/compute changes…")
        subprocess.Popen(
            [str(run_sh.resolve())],
            cwd=str(run_sh.parent),
            start_new_session=True,
        )
        app.quit()

    def shutdown(self) -> None:
        if self._hotkeys:
            self._hotkeys.stop()
        if self.state == "listening":
            self._recorder.stop()
        if self._worker and self._worker.isRunning():
            self._worker.wait(5000)


def _require_x11() -> None:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session and session != "x11":
        log.error("KWhisperX requires an X11 session (XDG_SESSION_TYPE=%s)", session)
        sys.exit(1)


def run_app() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    configure_offline_mode()
    _require_x11()
    app = QApplication(sys.argv)
    app.setApplicationName("KWhisperX")
    app.setQuitOnLastWindowClosed(False)

    config = Config.load()
    dictation = DictationApp(config)
    dictation.setup_tray(app)
    app.aboutToQuit.connect(dictation.shutdown)
    sys.exit(app.exec())
