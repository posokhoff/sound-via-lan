"""PySide6 GUI for the LAN audio receiver."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
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
)

from shared.audio_devices import list_devices
from shared.config import save_config, validate_config
from receiver.app import ReceiverService


class StatusBridge(QObject):
    message = Signal(str)
    error = Signal(str)


class ReceiverWindow(QMainWindow):
    def __init__(self, cfg: dict[str, Any], config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("LAN Audio Receiver")
        self.resize(520, 440)
        self.cfg = dict(cfg)
        self.config_path = config_path
        self.service: ReceiverService | None = None
        self.bridge = StatusBridge()
        self.bridge.message.connect(self._on_status)
        self.bridge.error.connect(self._on_error)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        form_box = QGroupBox("Settings")
        form = QFormLayout(form_box)

        self.listen_host = QLineEdit(str(self.cfg.get("listen_host", "0.0.0.0")))
        self.listen_port = QSpinBox()
        self.listen_port.setRange(1, 65535)
        self.listen_port.setValue(int(self.cfg.get("listen_port", 5005)))

        self.tx_host = QLineEdit(str(self.cfg.get("transmitter_host") or ""))
        self.tx_host.setPlaceholderText("empty = accept any")

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

        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(0, 1000)
        self.jitter_spin.setValue(int(self.cfg.get("jitter_ms", 60)))

        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setRange(0.0, 2.0)
        self.volume_spin.setSingleStep(0.05)
        self.volume_spin.setValue(float(self.cfg.get("volume", 1.0)))
        self.volume_spin.valueChanged.connect(self._on_volume_changed)

        form.addRow("Listen IP", self.listen_host)
        form.addRow("Listen port", self.listen_port)
        form.addRow("Transmitter IP", self.tx_host)
        form.addRow("Output device", device_row)
        form.addRow("Sample rate", self.rate_spin)
        form.addRow("Channels", self.channels_spin)
        form.addRow("Jitter (ms)", self.jitter_spin)
        form.addRow("Volume", self.volume_spin)
        layout.addWidget(form_box)

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
        for d in list_devices("output"):
            self.device_combo.addItem(f"[{d.index}] {d.name}", d.index)
        if current is not None:
            idx = self.device_combo.findData(current)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)

    def _select_device_from_cfg(self) -> None:
        device_id = self.cfg.get("output_device_id")
        if device_id is None:
            self.device_combo.setCurrentIndex(0)
            return
        idx = self.device_combo.findData(device_id)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)
        else:
            for i in range(self.device_combo.count()):
                if str(device_id).lower() in self.device_combo.itemText(i).lower():
                    self.device_combo.setCurrentIndex(i)
                    break

    def _collect_cfg(self) -> dict[str, Any]:
        cfg = {
            "listen_host": self.listen_host.text().strip() or "0.0.0.0",
            "listen_port": int(self.listen_port.value()),
            "transmitter_host": self.tx_host.text().strip(),
            "output_device_id": self.device_combo.currentData(),
            "sample_rate": int(self.rate_spin.value()),
            "channels": int(self.channels_spin.value()),
            "jitter_ms": int(self.jitter_spin.value()),
            "volume": float(self.volume_spin.value()),
        }
        validate_config(cfg, "receiver")
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
            self.service = ReceiverService(
                cfg,
                on_status=lambda m: self.bridge.message.emit(m),
                on_error=lambda m: self.bridge.error.emit(m),
            )
            self.service.start()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Start failed", str(exc))
            self.service = None
            return
        self._set_running(True)

    @Slot()
    def stop_stream(self) -> None:
        if self.service is not None:
            self.service.stop()
            self.service = None
        self._set_running(False)
        self.status_label.setText("Stopped")

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.save_btn.setEnabled(not running)
        for w in (
            self.listen_host,
            self.listen_port,
            self.tx_host,
            self.device_combo,
            self.refresh_btn,
            self.rate_spin,
            self.channels_spin,
            self.jitter_spin,
        ):
            w.setEnabled(not running)
        # volume stays editable while running
        if running:
            self.timer.start()
        else:
            self.timer.stop()
            self.stats_label.setText("")

    @Slot(float)
    def _on_volume_changed(self, value: float) -> None:
        if self.service is not None:
            self.service.apply_volume(value)

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
                self, "Save receiver config", "receiver.json", "JSON (*.json)"
            )
            if not chosen:
                return
            path = Path(chosen)
        try:
            save_config(path, cfg, "receiver")
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
        if self.service is None:
            return
        lis = self.service.listener
        buf = self.service.player.buffer
        addr = lis.last_addr
        from_s = f"{addr[0]}:{addr[1]}" if addr else "-"
        self.stats_label.setText(
            f"from={from_s}  pkts={lis.packets_received}  bytes={lis.bytes_received}  "
            f"depth={buf.depth}  underruns={buf.underruns}  late={buf.late_drops}  "
            f"filtered={lis.packets_dropped_filter}"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop_stream()
        super().closeEvent(event)


def run_gui(cfg: dict[str, Any], config_path: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = ReceiverWindow(cfg, config_path=config_path)
    win.show()
    return app.exec()
