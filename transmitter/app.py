"""Transmitter orchestration: headless and GUI entry points."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path
from typing import Any

from shared.config import TRANSMITTER_DEFAULTS, load_config, save_config, validate_config
from transmitter.capture import AudioCapture
from transmitter.sender import UdpSender


def build_capture(cfg: dict[str, Any], on_status=None, on_error=None) -> AudioCapture:
    sender = UdpSender(
        host=cfg["receiver_host"].strip(),
        port=int(cfg["receiver_port"]),
        bind_local_ip=str(cfg.get("bind_local_ip") or ""),
        on_error=on_error,
    )
    return AudioCapture(
        sender=sender,
        source=cfg["source"],
        device_id=cfg.get("device_id"),
        sample_rate=int(cfg["sample_rate"]),
        channels=int(cfg["channels"]),
        blocksize=int(cfg["blocksize"]),
        on_status=on_status,
        on_error=on_error,
    )


def run_headless(cfg: dict[str, Any]) -> int:
    def log(msg: str) -> None:
        print(msg, flush=True)

    capture = build_capture(cfg, on_status=log, on_error=log)
    stop = False

    def _handle_signal(signum, frame) -> None:  # noqa: ANN001, ARG001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    try:
        capture.start()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Press Ctrl+C to stop.", flush=True)
    try:
        while not stop and capture.running:
            time.sleep(0.5)
            sender = capture.sender
            print(
                f"\rpackets={sender.packets_sent} bytes={sender.bytes_sent} seq={sender.seq}",
                end="",
                flush=True,
            )
    finally:
        print()
        capture.stop()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LAN Audio Transmitter")
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default="",
        help="Path to transmitter JSON config",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without GUI (requires --config or defaults)",
    )
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
        save_config(args.save_defaults, dict(TRANSMITTER_DEFAULTS), "transmitter")
        print(f"Wrote {args.save_defaults}")
        return 0

    if args.config:
        cfg = load_config(args.config, "transmitter")
    else:
        cfg = dict(TRANSMITTER_DEFAULTS)
        validate_config(cfg, "transmitter")

    if args.headless:
        if not args.config:
            print("Warning: running headless with built-in defaults", file=sys.stderr)
        return run_headless(cfg)

    from transmitter.gui import run_gui

    config_path = Path(args.config) if args.config else None
    return run_gui(cfg, config_path=config_path)
