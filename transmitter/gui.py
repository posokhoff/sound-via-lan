"""PySide6 GUI for the LAN audio transmitter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from shared.audio_devices import list_devices, platform_loopback_hint
from shared.config import save_config, validate_config
from transmitter.app import build_capture
from transmitter.capture import AudioCapture


class StatusBridge(QObject):
    message = Signal(str)
    error = Signal(str)


class TransmitterWindow(QMainWindow):
    def __init__(self, cfg: dict[str, Any], config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("LAN Audio Transmitter")
        self.resize(520, 420)
        self.cfg = dict(cfg)
        self.config_path = config_path
        self.capture: AudioCapture | None = None
        self.bridge = StatusBridge()
        self.bridge.message.connect(self._on_status)
        self.bridge.error.connect(self._on_error)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        form_box = QGroupBox("Settings")
        form = QFormLayout(form_box)

        self.host_edit = QLineEdit(str(self.cfg.get("receiver_host", "")))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(self.cfg.get("receiver_port", 5005)))

        self.source_combo = QComboBox()
        self.source_combo.addItem("System sound (loopback)", "loopback")
        self.source_combo.addItem("Input device / microphone", "device")
        idx = 0 if self.cfg.get("source") == "loopback" else 1
        self.source_combo.setCurrentIndex(idx)

        self.device_combo = QComboBox()
        self.refresh_btn = QPushButton("Refresh devices")
        self.refresh_btn.clicked.connect(self.refresh_devices)

        device_row = QHBoxLayout()
        device_row.addWidget(self.device_combo, stretch=1)
        device_row.addWidget(self.refresh_btn)

        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(8000, 192000)
        self.rate_spin.setSingleStep(1000)
        self.rate_spin.setValue(int(self.cfg.get("sample_rate", 48000)))

        self.channels_spin = QSpinBox()
        self.channels_spin.setRange(1, 8)
        self.channels_spin.setValue(int(self.cfg.get("channels", 2)))

        self.block_spin = QSpinBox()
        self.block_spin.setRange(64, 8192)
        self.block_spin.setValue(int(self.cfg.get("blocksize", 960)))

        self.bind_edit = QLineEdit(str(self.cfg.get("bind_local_ip") or ""))

        form.addRow("Receiver IP", self.host_edit)
        form.addRow("Receiver port", self.port_spin)
        form.addRow("Source", self.source_combo)
        form.addRow("Device", device_row)
        form.addRow("Sample rate", self.rate_spin)
        form.addRow("Channels", self.channels_spin)
        form.addRow("Block size", self.block_spin)
        form.addRow("Bind local IP", self.bind_edit)
        layout.addWidget(form_box)

        self.hint_label = QLabel(platform_loopback_hint())
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.save_btn = QPushButton("Save config")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_stream)
        self.stop_btn.clicked.connect(self.stop_stream)
        self.save_btn.clicked.connect(self.save_config_dialog)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.save_btn)
        layout.addLayout(btns)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.stats_label = QLabel("")
        layout.addWidget(self.stats_label)
        layout.addStretch(1)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._update_stats)

        self.refresh_devices()
        self._select_device_from_cfg()

    def refresh_devices(self) -> None:
        current = self.device_combo.currentData()
        self.device_combo.clear()
        self.device_combo.addItem("(default)", None)
        for d in list_devices("loopback"):
            self.device_combo.addItem(f"{d.name}", d.index if d.soundcard_id is None else d.index)
        for d in list_devices("input"):
            if d.is_loopback and d.backend == "soundcard":
                continue
            label = f"[{d.index}] {d.name}"
            if d.is_loopback:
                label += " [loopback]"
            self.device_combo.addItem(label, d.index)
        for d in list_devices("output"):
            self.device_combo.addItem(f"[{d.index}] {d.name} (output)", d.index)
        if current is not None:
            idx = self.device_combo.findData(current)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)

    def _select_device_from_cfg(self) -> None:
        device_id = self.cfg.get("device_id")
        if device_id is None:
            self.device_combo.setCurrentIndex(0)
            return
        idx = self.device_combo.findData(device_id)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)
        else:
            # try by name string
            for i in range(self.device_combo.count()):
                text = self.device_combo.itemText(i).lower()
                if str(device_id).lower() in text:
                    self.device_combo.setCurrentIndex(i)
                    break

    def _collect_cfg(self) -> dict[str, Any]:
        cfg = {
            "receiver_host": self.host_edit.text().strip(),
            "receiver_port": int(self.port_spin.value()),
            "source": self.source_combo.currentData(),
            "device_id": self.device_combo.currentData(),
            "sample_rate": int(self.rate_spin.value()),
            "channels": int(self.channels_spin.value()),
            "blocksize": int(self.block_spin.value()),
            "bind_local_ip": self.bind_edit.text().strip(),
        }
        validate_config(cfg, "transmitter")
        return cfg

    @Slot()
    def start_stream(self) -> None:
        try:
            cfg = self._collect_cfg()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return
        self.cfg = cfg
        try:
            self.capture = build_capture(
                cfg,
                on_status=lambda m: self.bridge.message.emit(m),
                on_error=lambda m: self.bridge.error.emit(m),
            )
            self.capture.start()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Start failed", str(exc))
            self.capture = None
            return
        self._set_running(True)

    @Slot()
    def stop_stream(self) -> None:
        if self.capture is not None:
            self.capture.stop()
            self.capture = None
        self._set_running(False)
        self.status_label.setText("Stopped")

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.save_btn.setEnabled(not running)
        form_enabled = not running
        for w in (
            self.host_edit,
            self.port_spin,
            self.source_combo,
            self.device_combo,
            self.refresh_btn,
            self.rate_spin,
            self.channels_spin,
            self.block_spin,
            self.bind_edit,
        ):
            w.setEnabled(form_enabled)
        if running:
            self.timer.start()
        else:
            self.timer.stop()
            self.stats_label.setText("")

    @Slot()
    def save_config_dialog(self) -> None:
        try:
            cfg = self._collect_cfg()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return
        path = self.config_path
        if path is None:
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Save transmitter config", "transmitter.json", "JSON (*.json)"
            )
            if not chosen:
                return
            path = Path(chosen)
        try:
            save_config(path, cfg, "transmitter")
            self.config_path = path
            self.cfg = cfg
            self.status_label.setText(f"Saved {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))

    @Slot(str)
    def _on_status(self, msg: str) -> None:
        self.status_label.setText(msg)

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self.status_label.setText(msg)

    @Slot()
    def _update_stats(self) -> None:
        if self.capture is None:
            return
        s = self.capture.sender
        self.stats_label.setText(
            f"packets={s.packets_sent}  bytes={s.bytes_sent}  seq={s.seq}"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop_stream()
        super().closeEvent(event)


def run_gui(cfg: dict[str, Any], config_path: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = TransmitterWindow(cfg, config_path=config_path)
    win.show()
    return app.exec()
