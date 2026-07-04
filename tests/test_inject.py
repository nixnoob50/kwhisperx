"""Regression tests for X11 text injection modes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kwhisperx.inject import (
    get_focused_window_id,
    inject_append,
    inject_text,
    supports_chunk_injection,
    uses_clipboard,
)


class TestInjectionModes:
    """v0.2.1: keystrokes must not use clipboard; streaming limited to keystrokes/terminal."""

    def test_uses_clipboard_for_auto_clipboard_terminal(self) -> None:
        assert uses_clipboard("auto")
        assert uses_clipboard("clipboard")
        assert uses_clipboard("terminal")

    def test_keystrokes_do_not_use_clipboard(self) -> None:
        assert not uses_clipboard("keystrokes")

    def test_streaming_modes(self) -> None:
        assert supports_chunk_injection("keystrokes")
        assert supports_chunk_injection("terminal")
        assert not supports_chunk_injection("auto")
        assert not supports_chunk_injection("clipboard")


class TestGetFocusedWindow:
    """Focused window required for injection; xdotool missing or '0' means failure."""

    def test_no_xdotool(self) -> None:
        with patch("kwhisperx.inject.shutil.which", return_value=None):
            assert get_focused_window_id() is None

    def test_zero_window_id(self) -> None:
        with patch("kwhisperx.inject.shutil.which", return_value="/usr/bin/xdotool"):
            with patch("kwhisperx.inject.subprocess.run") as run:
                run.return_value = MagicMock(stdout="0\n", returncode=0)
                assert get_focused_window_id() is None

    def test_valid_window_id(self) -> None:
        with patch("kwhisperx.inject.shutil.which", return_value="/usr/bin/xdotool"):
            with patch("kwhisperx.inject.subprocess.run") as run:
                run.return_value = MagicMock(stdout="12345678\n", returncode=0)
                assert get_focused_window_id() == "12345678"


class TestInjectAppend:
    """Streaming append: space prefix between chunks, keystrokes only."""

    @patch("kwhisperx.inject._inject_keystrokes", return_value=True)
    @patch("kwhisperx.inject.shutil.which", return_value="/usr/bin/xdotool")
    def test_first_chunk_no_leading_space(self, _which, keystrokes) -> None:
        assert inject_append("hello", "123", "keystrokes", first_chunk=True)
        keystrokes.assert_called_once_with("hello", "123")

    @patch("kwhisperx.inject._inject_keystrokes", return_value=True)
    @patch("kwhisperx.inject.shutil.which", return_value="/usr/bin/xdotool")
    def test_later_chunk_leading_space(self, _which, keystrokes) -> None:
        assert inject_append("world", "123", "keystrokes", first_chunk=False)
        keystrokes.assert_called_once_with(" world", "123")

    def test_clipboard_mode_rejects_append(self) -> None:
        assert not inject_append("hi", "123", "clipboard", first_chunk=True)


class TestInjectTextClipboard:
    """Keystrokes path must not touch clipboard object."""

    @patch("kwhisperx.inject._inject_keystrokes", return_value=True)
    @patch("kwhisperx.inject.shutil.which", return_value="/usr/bin/xdotool")
    def test_keystrokes_skip_clipboard(self, _which, _keys) -> None:
        clipboard = MagicMock()
        assert inject_text("hello", "123", "keystrokes", clipboard=clipboard)
        clipboard.setText.assert_not_called()
