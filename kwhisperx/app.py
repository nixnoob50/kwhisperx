"""Main tray application and state machine."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QThread, QTimer, Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from kwhisperx.audio import AudioRecorder, has_audio
from kwhisperx.config import Config
from kwhisperx.dbus_service import DbusService
from kwhisperx.hotkey import HotkeyManager
from kwhisperx.inject import (
    get_focused_window_id,
    inject_append,
    inject_text,
    supports_chunk_injection,
    uses_clipboard,
)
from kwhisperx.single_instance import acquire, notify_already_running, release
from kwhisperx.settings import SettingsDialog
from kwhisperx.transcribe import configure_offline_mode, transcribe

log = logging.getLogger(__name__)

_TRAY_ICON_SIZE = 22
_LISTENING_RED = QColor(220, 50, 50)
_LISTENING_BORDER = QColor(180, 40, 40)
_IDLE_WHITE = QColor(245, 245, 245)
_IDLE_BORDER = QColor(190, 190, 190)
_MIC_GLYPH_DARK = QColor(50, 50, 50)


def _mic_pixmap(
    fill: QColor,
    logical_size: int,
    dpr: float,
    *,
    glyph: QColor | None = None,
) -> QPixmap:
    physical = max(logical_size, int(round(logical_size * dpr)))
    pm = QPixmap(physical, physical)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = physical / logical_size
    border = QColor(
        max(0, fill.red() - 40),
        max(0, fill.green() - 40),
        max(0, fill.blue() - 40),
    )
    p.setBrush(fill)
    p.setPen(border)
    margin = 2 * scale
    p.drawEllipse(int(margin), int(margin), int(physical - 2 * margin), int(physical - 2 * margin))
    mic_color = glyph if glyph is not None else (
        QColor(255, 255, 255) if fill.lightness() < 140 else _MIC_GLYPH_DARK
    )
    p.setBrush(mic_color)
    p.setPen(Qt.PenStyle.NoPen)
    cx = physical / 2
    p.drawRoundedRect(int(cx - 3 * scale), int(6 * scale), int(6 * scale), int(9 * scale), int(2 * scale), int(2 * scale))
    p.drawRect(int(cx - 5 * scale), int(14 * scale), int(10 * scale), int(2 * scale))
    p.drawRect(int(cx - 1 * scale), int(16 * scale), int(2 * scale), int(3 * scale))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _theme_pixmap(*names: str, logical_size: int, dpr: float) -> QPixmap | None:
    physical = max(logical_size, int(round(logical_size * dpr)))
    size = QSize(physical, physical)
    for name in names:
        theme = QIcon.fromTheme(name)
        if theme.isNull():
            continue
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
            pix = theme.pixmap(size, mode, QIcon.State.Off)
            if not pix.isNull() and pix.width() > 0:
                pix.setDevicePixelRatio(dpr)
                return pix
    return None


def _compose_badge_pixmap(mic: QPixmap, fill: QColor, border: QColor, dpr: float) -> QPixmap:
    physical = mic.width()
    composed = QPixmap(physical, physical)
    composed.fill(Qt.GlobalColor.transparent)
    p = QPainter(composed)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(fill)
    p.setPen(border)
    p.drawEllipse(1, 1, physical - 2, physical - 2)
    p.drawPixmap(0, 0, mic)
    p.end()
    composed.setDevicePixelRatio(dpr)
    return composed


def _icon_from_pixmap(pix: QPixmap | None, fallback: QPixmap) -> QIcon:
    if pix is not None and not pix.isNull():
        return QIcon(pix)
    return QIcon(fallback)


def build_tray_icons(app: QApplication) -> dict[str, QIcon]:
    """Build tray icons once at the native DPI so KDE never lazy-loads theme assets."""
    dpr = max(1.0, app.devicePixelRatio())
    size = _TRAY_ICON_SIZE

    mic_pix = _theme_pixmap("audio-input-microphone", logical_size=size, dpr=dpr)
    idle_fallback = _mic_pixmap(_IDLE_WHITE, size, dpr, glyph=_MIC_GLYPH_DARK)
    listen_fallback = _mic_pixmap(_LISTENING_RED, size, dpr)

    if mic_pix is not None:
        idle = QIcon(_compose_badge_pixmap(mic_pix, _IDLE_WHITE, _IDLE_BORDER, dpr))
        listening = QIcon(_compose_badge_pixmap(mic_pix, _LISTENING_RED, _LISTENING_BORDER, dpr))
    else:
        idle = QIcon(idle_fallback)
        listening = QIcon(listen_fallback)

    error_pix = _theme_pixmap("dialog-warning", logical_size=size, dpr=dpr)
    error = _icon_from_pixmap(error_pix, idle_fallback)

    return {
        "idle": idle,
        "listening": listening,
        "processing": listening,
        "error": error,
    }


def warm_tray_icons(icons: dict[str, QIcon]) -> None:
    """Force rasterization before the tray is shown."""
    for icon in icons.values():
        if not icon.isNull():
            icon.pixmap(QSize(_TRAY_ICON_SIZE, _TRAY_ICON_SIZE))


class TranscribeWorker(QThread):
    finished_text = pyqtSignal(str, bool)
    failed = pyqtSignal(str)

    def __init__(
        self,
        audio: np.ndarray,
        model_size: str,
        device: str,
        language: str,
        models_path: str,
        *,
        is_final: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.audio = audio
        self.model_size = model_size
        self.device = device
        self.language = language
        self.models_path = models_path
        self.is_final = is_final

    def run(self) -> None:
        try:
            text = transcribe(
                self.audio,
                model_size=self.model_size,
                device=self.device,
                language=self.language,
                models_path=self.models_path,
            )
            self.finished_text.emit(text, self.is_final)
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
        self._tray_icons: dict[str, QIcon] = {}
        self._tray_icon_state: str | None = None
        self._dbus = DbusService(self, parent=self)
        self._chunk_timer: QTimer | None = None
        self._pending_jobs: list[tuple[np.ndarray, bool]] = []
        self._streaming_finishing = False
        self._chunk_count = 0
        self._words_injected = 0
        self._hotkey_toggle.connect(self.toggle_listening)
        self._hotkey_hold_start.connect(self.start_listening)
        self._hotkey_hold_stop.connect(self.stop_listening)

    def _use_streaming(self) -> bool:
        return self.config.chunk_injection and supports_chunk_injection(
            self.config.injection_method
        )

    def setup_tray(self, app: QApplication) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.error("System tray not available")
            sys.exit(1)

        self._tray = QSystemTrayIcon(self)
        self._tray_icons = build_tray_icons(app)
        warm_tray_icons(self._tray_icons)
        self._update_icon("idle")
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

    def _toast(self, message: str, icon: QSystemTrayIcon.MessageIcon | None = None) -> None:
        if not self._tray or not message:
            return
        self._tray.showMessage(
            "KWhisperX",
            message,
            icon or QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def _set_state(self, state: str, message: str = "", *, toast: bool = False) -> None:
        self.state = state
        self.state_changed.emit(state)
        if self._tray:
            self._update_icon(state)
            tip = f"KWhisperX — {state}"
            if message:
                tip = f"{tip}: {message}"
            self._tray.setToolTip(tip)
            if toast and message:
                level = QSystemTrayIcon.MessageIcon.Warning if state == "error" else QSystemTrayIcon.MessageIcon.Information
                self._toast(message, level)

    def _tray_icon_key(self, state: str) -> str:
        if state in ("listening", "processing"):
            return "listening"
        if state == "error":
            return "idle"
        return state if state in self._tray_icons else "idle"

    def _update_icon(self, state: str | None = None) -> None:
        if not self._tray:
            return
        icon_state = self._tray_icon_key(state or self.state)
        if icon_state == self._tray_icon_state:
            return
        icon = self._tray_icons.get(icon_state) or self._tray_icons.get("idle")
        if icon is None or icon.isNull():
            return
        self._tray.setIcon(icon)
        self._tray_icon_state = icon_state

    def toggle_listening(self) -> None:
        if self.state == "listening":
            self.stop_listening()
        elif self.state == "idle":
            self.start_listening()

    def start_listening(self) -> None:
        if self.state != "idle":
            return
        self._wait_for_worker()
        self._target_window = get_focused_window_id()
        if not self._target_window:
            self._toast("Could not detect focused window", QSystemTrayIcon.MessageIcon.Warning)
            return
        self._pending_jobs = []
        self._streaming_finishing = False
        self._chunk_count = 0
        self._words_injected = 0
        try:
            self._recorder = AudioRecorder(device=self.config.microphone)
            self._recorder.start()
        except Exception as exc:
            log.exception("failed to start audio")
            self._toast(f"Microphone error: {exc}", QSystemTrayIcon.MessageIcon.Warning)
            return
        if self._use_streaming():
            self._chunk_timer = QTimer(self)
            self._chunk_timer.setInterval(200)
            self._chunk_timer.timeout.connect(self._poll_for_chunk)
            self._chunk_timer.start()
        self._set_state("listening", "Listening…")

    def _stop_chunk_timer(self) -> None:
        if self._chunk_timer is not None:
            self._chunk_timer.stop()
            self._chunk_timer.deleteLater()
            self._chunk_timer = None

    def _poll_for_chunk(self) -> None:
        if self.state != "listening" or self._streaming_finishing:
            return
        silence = self.config.silence_seconds
        if not self._recorder.poll_utterance_end(silence_sec=silence):
            self._recorder.log_pause_diagnostics(silence_sec=silence)
            return
        chunk = self._recorder.extract_chunk(silence_sec=silence)
        if has_audio(chunk):
            log.info("Streaming chunk ready (%.2fs)", len(chunk) / self._recorder.samplerate)
            self._enqueue_chunk(chunk, is_final=False)

    def _enqueue_chunk(self, audio: np.ndarray, *, is_final: bool) -> None:
        self._pending_jobs.append((audio, is_final))
        while len(self._pending_jobs) > 2:
            audio_a, _final_a = self._pending_jobs.pop(0)
            audio_b, final_b = self._pending_jobs.pop(0)
            merged = np.concatenate([audio_a, audio_b])
            self._pending_jobs.insert(0, (merged, final_b))
        self._maybe_start_worker()

    def _worker_active(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _maybe_start_worker(self) -> None:
        if self._worker_active():
            return
        if not self._pending_jobs:
            if self._streaming_finishing:
                self._finish_streaming_session()
            return
        audio, is_final = self._pending_jobs.pop(0)
        worker = TranscribeWorker(
            audio=audio,
            model_size=self.config.model_size,
            device=self.config.device,
            language=self.config.language,
            models_path=self.config.models_dir,
            is_final=is_final,
            parent=self,
        )
        worker.finished_text.connect(self._on_worker_text)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_thread_finished)
        self._worker = worker
        worker.start()
        if self._use_streaming() and self.state == "listening" and not is_final:
            if self._tray:
                self._tray.setToolTip("KWhisperX — listening (inserting…)")

    def stop_listening(self) -> None:
        if self.state != "listening":
            return
        self._stop_chunk_timer()

        if self._use_streaming():
            remainder = self._recorder.extract_remainder()
            self._recorder.stop_stream()
            self._streaming_finishing = True

            if has_audio(remainder):
                self._enqueue_chunk(remainder, is_final=True)
            elif (
                self._chunk_count == 0
                and not self._pending_jobs
                and not self._worker_active()
            ):
                self._streaming_finishing = False
                self._set_state("idle", "No audio detected")
                return

            if not self._worker_active() and not self._pending_jobs:
                self._finish_streaming_session()
            else:
                self._set_state("listening", "Finishing…")
            return

        audio = self._recorder.stop()
        if not has_audio(audio):
            self._set_state("idle", "No audio detected")
            return
        self._set_state("processing")
        worker = TranscribeWorker(
            audio=audio,
            model_size=self.config.model_size,
            device=self.config.device,
            language=self.config.language,
            models_path=self.config.models_dir,
            parent=self,
        )
        worker.finished_text.connect(self._on_batch_transcribed)
        worker.failed.connect(self._on_transcribe_failed)
        worker.finished.connect(self._on_worker_thread_finished)
        self._worker = worker
        worker.start()

    def _on_worker_text(self, text: str, is_final: bool) -> None:
        if not text.strip():
            return
        method = self.config.injection_method
        ok = inject_append(
            text,
            self._target_window,
            method,
            first_chunk=self._chunk_count == 0,
        )
        if ok:
            self._chunk_count += 1
            self._words_injected += len(text.split())
            log.info("Streaming injected %d word(s)", len(text.split()))
        elif self._tray:
            self._tray.showMessage(
                "KWhisperX",
                "Failed to inject text",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

    def _on_worker_thread_finished(self) -> None:
        worker = self.sender()
        if worker is self._worker:
            self._worker = None
        if isinstance(worker, TranscribeWorker):
            worker.deleteLater()
        self._maybe_start_worker()
        if self.state == "listening" and self._tray and not self._streaming_finishing:
            self._tray.setToolTip("KWhisperX — listening")

    def _finish_streaming_session(self) -> None:
        if not self._streaming_finishing or self._worker_active() or self._pending_jobs:
            return
        self._streaming_finishing = False
        if self._words_injected:
            self._set_state("idle", f"Inserted {self._words_injected} word(s)")
        elif self._chunk_count == 0:
            self._set_state("idle", "No speech detected")
        else:
            self._set_state("idle")

    def _on_worker_failed(self, message: str) -> None:
        log.error("Transcription failed: %s", message)
        if self._tray:
            self._tray.showMessage(
                "KWhisperX",
                f"Transcription failed: {message}",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

    def _on_batch_transcribed(self, text: str, _is_final: bool) -> None:
        if not text.strip():
            self._set_state("idle", "No speech detected")
            return
        app = QApplication.instance()
        clipboard = app.clipboard() if app else None
        method = self.config.injection_method
        ok = inject_text(
            text,
            self._target_window,
            method,
            clipboard=clipboard if uses_clipboard(method) else None,
        )
        if ok:
            words = len(text.split())
            self._set_state("idle", f"Inserted {words} word(s)")
        elif uses_clipboard(method) and clipboard is not None:
            clipboard.setText(text)
            self._set_state("idle", "Failed to inject text — copied to clipboard", toast=True)
        else:
            self._set_state("idle", "Failed to inject text", toast=True)

    def _on_transcribe_failed(self, message: str) -> None:
        self._set_state("idle", f"Transcription failed: {message}", toast=True)

    def _wait_for_worker(self, timeout_ms: int = 30000) -> None:
        if self._worker is None:
            return
        if self._worker.isRunning():
            self._worker.wait(timeout_ms)
        if self._worker is not None and not self._worker.isRunning():
            self._worker.deleteLater()
            self._worker = None

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
        if self._worker_active():
            self._wait_for_worker(30000)

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
            self._set_state("idle", "Restart manually to apply model/compute changes", toast=True)
            return
        self._set_state("idle", "Restarting to apply model/compute changes…")
        release()
        subprocess.Popen(
            [str(run_sh.resolve())],
            cwd=str(run_sh.parent),
            start_new_session=True,
        )
        app.quit()

    def shutdown(self) -> None:
        if self._hotkeys:
            self._hotkeys.stop()
        self._stop_chunk_timer()
        if self.state == "listening":
            self._recorder.stop_stream()
        self._wait_for_worker(60000)


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

    if not acquire():
        notify_already_running()
        sys.exit(0)

    config = Config.load()
    dictation = DictationApp(config)
    dictation.setup_tray(app)
    app.aboutToQuit.connect(dictation.shutdown)
    app.aboutToQuit.connect(release)
    sys.exit(app.exec())
