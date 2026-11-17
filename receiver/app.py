"""Receiver orchestration: headless and GUI entry points."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path
from typing import Any

from shared.config import RECEIVER_DEFAULTS, load_config, save_config, validate_config
from shared.protocol import PacketHeader
from receiver.listener import UdpListener
from receiver.player import AudioPlayer


class ReceiverService:
    def __init__(self, cfg: dict[str, Any], on_status=None, on_error=None) -> None:
        self.cfg = cfg
        self.on_status = on_status
        self.on_error = on_error
        self.player = AudioPlayer(
            sample_rate=int(cfg["sample_rate"]),
            channels=int(cfg["channels"]),
            jitter_ms=int(cfg["jitter_ms"]),
            volume=float(cfg["volume"]),
            output_device_id=cfg.get("output_device_id"),
            on_status=on_status,
            on_error=on_error,
        )
        self.listener = UdpListener(
            listen_host=str(cfg["listen_host"]),
            listen_port=int(cfg["listen_port"]),
            transmitter_host=str(cfg.get("transmitter_host") or ""),
            on_packet=self._on_packet,
            on_status=on_status,
            on_error=on_error,
        )
        self.running = False

    def _on_packet(self, header: PacketHeader, pcm: bytes, addr: tuple[str, int]) -> None:
        self.player.push_packet(header, pcm)

    def start(self) -> None:
        if self.running:
            return
        self.player.start()
        self.listener.start()
        self.running = True

    def stop(self) -> None:
        self.running = False
        self.listener.stop()
        self.player.stop()

    def apply_volume(self, volume: float) -> None:
        self.player.set_volume(volume)
        self.cfg["volume"] = float(volume)


def run_headless(cfg: dict[str, Any]) -> int:
    def log(msg: str) -> None:
        print(msg, flush=True)

    svc = ReceiverService(cfg, on_status=log, on_error=log)
    stop = False

    def _handle_signal(signum, frame) -> None:  # noqa: ANN001, ARG001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    try:
        svc.start()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Press Ctrl+C to stop.", flush=True)
    try:
        while not stop and svc.running:
            time.sleep(0.5)
            lis = svc.listener
            buf = svc.player.buffer
            print(
                f"\rpkts={lis.packets_received} bytes={lis.bytes_received} "
                f"depth={buf.depth} underruns={buf.underruns} late={buf.late_drops}",
                end="",
                flush=True,
            )
    finally:
        print()
        svc.stop()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LAN Audio Receiver")
    parser.add_argument("--config", "-c", type=str, default="", help="Path to receiver JSON config")
    parser.add_argument("--headless", action="store_true", help="Run without GUI")
    parser.add_argument(
        "--save-defaults",
        type=str,
        metavar="PATH",
        help="Write default config JSON to PATH and exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.save_defaults:
        save_config(args.save_defaults, dict(RECEIVER_DEFAULTS), "receiver")
        print(f"Wrote {args.save_defaults}")
        return 0

    if args.config:
        cfg = load_config(args.config, "receiver")
    else:
        cfg = dict(RECEIVER_DEFAULTS)
        validate_config(cfg, "receiver")

    if args.headless:
        if not args.config:
            print("Warning: running headless with built-in defaults", file=sys.stderr)
        return run_headless(cfg)

    from receiver.gui import run_gui

    config_path = Path(args.config) if args.config else None
    return run_gui(cfg, config_path=config_path)
