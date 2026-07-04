"""Settings dialog."""

from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from kwhisperx.audio import (
    AudioRecorder,
    pause_noise_floor_from_slider,
    pause_noise_slider_from_floor,
)
from kwhisperx.config import Config
from kwhisperx.inject import supports_chunk_injection


class HotkeyRecorder(QLineEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click Record, then press keys…")
        self._recording = False
        self._mods: set[str] = set()

    def start_recording(self) -> None:
        self._recording = True
        self._mods = set()
        self.clear()
        self.setFocus()
        self.grabKeyboard()

    def stop_recording(self) -> None:
        self._recording = False
        self.releaseKeyboard()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self._recording:
            super().keyPressEvent(event)
            return
        key = event.key()
        mods = event.modifiers()
        names: list[str] = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            names.append("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            names.append("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            names.append("Shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            names.append("Super")
        text = event.text().strip()
        if text and text.isprintable() and len(text) == 1:
            names.append(text.upper())
        elif key not in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Meta,
        ):
            names.append(QKeySequence(key).toString() or "")
        combo = "+".join(n for n in names if n)
        if combo:
            self.setText(combo)
            self.stop_recording()
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if self._recording:
            event.accept()
            return
        super().keyReleaseEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("KWhisperX Settings")
        self._config = config
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        hotkey_row = QHBoxLayout()
        self.hotkey_edit = HotkeyRecorder()
        self.hotkey_edit.setText(self._config.hotkey)
        record_btn = QPushButton("Record")
        record_btn.clicked.connect(self.hotkey_edit.start_recording)
        hotkey_row.addWidget(self.hotkey_edit)
        hotkey_row.addWidget(record_btn)
        form.addRow("Hotkey:", hotkey_row)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["toggle", "hold"])
        self.mode_combo.setCurrentText(self._config.hotkey_mode)
        form.addRow("Mode:", self.mode_combo)

        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "tiny.en", "base", "base.en", "small", "small.en"])
        self.model_combo.setCurrentText(self._config.model_size)
        form.addRow("Whisper model:", self.model_combo)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cpu", "cuda", "amd"])
        self.device_combo.setCurrentText(self._config.device)
        form.addRow("Compute:", self.device_combo)

        self._amd_note = QLabel(
            "AMD uses ROCm via CTranslate2. Install ROCm and the CTranslate2 ROCm wheel "
            "(see README). RDNA2 cards may need CT2_CUDA_ALLOCATOR=cub_caching (set automatically). "
            "Changing model or compute restarts the app."
        )
        self._amd_note.setWordWrap(True)
        self._amd_note.setVisible(self._config.device == "amd")
        self.device_combo.currentTextChanged.connect(
            lambda text: self._amd_note.setVisible(text == "amd")
        )
        form.addRow("", self._amd_note)

        self._restart_note = QLabel(
            "Changing Whisper model or Compute restarts KWhisperX (required for GPU backend switches)."
        )
        self._restart_note.setWordWrap(True)
        form.addRow("", self._restart_note)

        self.language_edit = QLineEdit(self._config.language)
        form.addRow("Language:", self.language_edit)

        self.mic_combo = QComboBox()
        self.mic_combo.addItem("System default (PulseAudio)", None)
        for idx, name in AudioRecorder.list_input_devices():
            self.mic_combo.addItem(f"{name} ({idx})", idx)
        if self._config.microphone is not None:
            for i in range(self.mic_combo.count()):
                if self.mic_combo.itemData(i) == self._config.microphone:
                    self.mic_combo.setCurrentIndex(i)
                    break
        form.addRow("Microphone:", self.mic_combo)

        self.inject_combo = QComboBox()
        self.inject_combo.addItems(["auto", "clipboard", "terminal", "keystrokes"])
        self.inject_combo.setCurrentText(self._config.injection_method)
        form.addRow("Injection:", self.inject_combo)

        self.chunk_check = QCheckBox("Inject on pauses (streaming)")
        self.chunk_check.setChecked(self._config.chunk_injection)
        form.addRow("", self.chunk_check)

        self.silence_spin = QDoubleSpinBox()
        self.silence_spin.setRange(1.0, 3.0)
        self.silence_spin.setSingleStep(0.1)
        self.silence_spin.setSuffix(" s")
        self.silence_spin.setValue(self._config.silence_seconds)
        form.addRow("Pause duration:", self.silence_spin)

        pause_noise_row = QHBoxLayout()
        self.pause_noise_slider = QSlider(Qt.Orientation.Horizontal)
        self.pause_noise_slider.setRange(0, 100)
        self.pause_noise_slider.setValue(pause_noise_slider_from_floor(self._config.pause_noise_floor))
        self.pause_noise_slider.setToolTip(
            "How much quieter a pause must be compared with your loudest speech. "
            "Raise if pauses are not detected; lower if speech gets cut off early."
        )
        self.pause_noise_value = QLabel()
        self.pause_noise_slider.valueChanged.connect(self._update_pause_noise_label)
        self._update_pause_noise_label(self.pause_noise_slider.value())
        pause_noise_row.addWidget(self.pause_noise_slider, stretch=1)
        pause_noise_row.addWidget(self.pause_noise_value)
        form.addRow("Pause sensitivity:", pause_noise_row)

        self._streaming_note = QLabel(
            "Streaming inserts text after pauses while you keep listening. "
            "Uses keystroke typing (keystrokes / terminal modes only) and more CPU than batch mode."
        )
        self._streaming_note.setWordWrap(True)
        form.addRow("", self._streaming_note)

        self.inject_combo.currentTextChanged.connect(self._update_streaming_controls)
        self.chunk_check.toggled.connect(self._update_streaming_controls)
        self._update_streaming_controls(self._config.injection_method)

        self.autostart_check = QCheckBox("Start at login")
        self.autostart_check.setChecked(self._config.autostart)
        form.addRow("", self.autostart_check)

        layout.addLayout(form)

        if not shutil.which("xdotool"):
            layout.addWidget(QLabel("Warning: xdotool not found — text injection will not work."))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_streaming_controls(self, _method: str | None = None) -> None:
        method = self.inject_combo.currentText()
        supported = supports_chunk_injection(method)
        self.chunk_check.setEnabled(supported)
        self.silence_spin.setEnabled(supported and self.chunk_check.isChecked())
        self.pause_noise_slider.setEnabled(supported and self.chunk_check.isChecked())
        self.pause_noise_value.setEnabled(supported and self.chunk_check.isChecked())
        if not supported:
            self.chunk_check.setToolTip("Only available for keystrokes or terminal injection")
        else:
            self.chunk_check.setToolTip("")
        self._streaming_note.setVisible(supported)

    def _update_pause_noise_label(self, value: int) -> None:
        ratio = pause_noise_floor_from_slider(value)
        self.pause_noise_value.setText(f"{ratio * 100:.0f}%")

    def apply_to(self, config: Config) -> None:
        config.hotkey = self.hotkey_edit.text().strip() or config.hotkey
        config.hotkey_mode = self.mode_combo.currentText()
        config.model_size = self.model_combo.currentText()
        config.device = self.device_combo.currentText()
        config.language = self.language_edit.text().strip() or "en"
        config.microphone = self.mic_combo.currentData()
        config.injection_method = self.inject_combo.currentText()
        config.chunk_injection = self.chunk_check.isChecked() and supports_chunk_injection(
            config.injection_method
        )
        config.silence_seconds = self.silence_spin.value()
        config.pause_noise_floor = pause_noise_floor_from_slider(self.pause_noise_slider.value())
        config.autostart = self.autostart_check.isChecked()
        config.save()
        _sync_autostart(config)


def _sync_autostart(config: Config) -> None:
    autostart_dir = Path.home() / ".config" / "autostart"
    dest = autostart_dir / "kwhisperx.desktop"
    if config.autostart:
        autostart_dir.mkdir(parents=True, exist_ok=True)
        template = Path(config.install_path) / "autostart" / "kwhisperx.desktop"
        content = template.read_text().replace("INSTALL_PATH", config.install_path)
        dest.write_text(content)
    elif dest.exists():
        dest.unlink()
