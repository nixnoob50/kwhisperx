"""Optional D-Bus interface for external toggle control."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kwhisperx.app import DictationApp

try:
    from PyQt6.QtCore import QObject, pyqtSlot
    from PyQt6.QtDBus import QDBusConnection

    _REGISTER_OPTS = (
        QDBusConnection.RegisterOption.ExportScriptableSlots
        | QDBusConnection.RegisterOption.ExportNonScriptableSlots
    )
except ImportError:  # pragma: no cover
    QObject = object  # type: ignore[misc, assignment]
    QDBusConnection = None  # type: ignore[misc, assignment]
    _REGISTER_OPTS = 0

SERVICE = "org.kwhisperx.App"
PATH = "/App"


class DbusService(QObject):
    def __init__(self, app: "DictationApp", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self._registered = False

    def register(self) -> bool:
        if QDBusConnection is None:
            return False
        try:
            bus = QDBusConnection.sessionBus()
            if not bus.registerService(SERVICE):
                log.warning(
                    "Could not register D-Bus service %s (may already be running)",
                    SERVICE,
                )
                return False
            if not bus.registerObject(PATH, self, _REGISTER_OPTS):
                log.warning("Could not register D-Bus object at %s", PATH)
                return False
            self._registered = True
            return True
        except Exception:
            log.exception("D-Bus registration failed")
            return False

    @pyqtSlot()
    def toggle(self) -> None:
        self.app.toggle_listening()

    @pyqtSlot()
    def start(self) -> None:
        self.app.start_listening()

    @pyqtSlot()
    def stop(self) -> None:
        self.app.stop_listening()
