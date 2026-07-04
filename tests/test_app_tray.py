"""Regression tests for tray icon state (KDE missing-icon flash, blank idle on startup)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kwhisperx.app import DictationApp, build_tray_icons, warm_tray_icons
from kwhisperx.config import Config


@pytest.fixture
def dictation_app(qapp):
    app = DictationApp(Config())
    app._tray = MagicMock()
    app._tray_icons = build_tray_icons(qapp)
    warm_tray_icons(app._tray_icons)
    app._tray_icon_state = None
    return app


class TestTrayIconKey:
    """Processing uses listening icon; errors fall back to idle icon key."""

    def test_processing_maps_to_listening(self, dictation_app) -> None:
        assert dictation_app._tray_icon_key("processing") == "listening"

    def test_error_maps_to_idle(self, dictation_app) -> None:
        assert dictation_app._tray_icon_key("error") == "idle"


class TestTrayIconUpdate:
    """Initial idle icon must be set ( _tray_icon_state starts None )."""

    def test_first_idle_update_sets_icon(self, dictation_app) -> None:
        dictation_app._update_icon("idle")
        dictation_app._tray.setIcon.assert_called_once()
        assert dictation_app._tray_icon_state == "idle"

    def test_duplicate_idle_update_skips_set_icon(self, dictation_app) -> None:
        dictation_app._update_icon("idle")
        dictation_app._tray.setIcon.reset_mock()
        dictation_app._update_icon("idle")
        dictation_app._tray.setIcon.assert_not_called()

    def test_listening_changes_icon(self, dictation_app) -> None:
        dictation_app._update_icon("idle")
        dictation_app._tray.setIcon.reset_mock()
        dictation_app._update_icon("listening")
        dictation_app._tray.setIcon.assert_called_once()
        assert dictation_app._tray_icon_state == "listening"

    def test_processing_does_not_change_icon_key(self, dictation_app) -> None:
        dictation_app._update_icon("listening")
        dictation_app._tray.setIcon.reset_mock()
        dictation_app._update_icon("processing")
        dictation_app._tray.setIcon.assert_not_called()
        assert dictation_app._tray_icon_state == "listening"


class TestBuildTrayIcons:
    def test_icons_are_valid(self, qapp) -> None:
        icons = build_tray_icons(qapp)
        assert set(icons) >= {"idle", "listening", "processing", "error"}
        for name, icon in icons.items():
            assert not icon.isNull(), f"{name} icon should not be null"
