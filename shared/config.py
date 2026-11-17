"""Load/save and validate JSON configuration for transmitter and receiver."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

TRANSMITTER_DEFAULTS: dict[str, Any] = {
    "receiver_host": "192.168.1.10",
    "receiver_port": 5005,
    "source": "loopback",  # "loopback" | "device"
    "device_id": None,
    "sample_rate": 48000,
    "channels": 2,
    "blocksize": 960,
    "bind_local_ip": "",
}

RECEIVER_DEFAULTS: dict[str, Any] = {
    "listen_host": "0.0.0.0",
    "listen_port": 5005,
    "transmitter_host": "",
    "output_device_id": None,
    "sample_rate": 48000,
    "channels": 2,
    "jitter_ms": 60,
    "volume": 1.0,
}


def _merge_defaults(defaults: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(defaults)
    for key, value in data.items():
        if key in result:
            result[key] = value
    return result


def load_config(path: str | Path, kind: str) -> dict[str, Any]:
    defaults = TRANSMITTER_DEFAULTS if kind == "transmitter" else RECEIVER_DEFAULTS
    path = Path(path)
    if not path.exists():
        return deepcopy(defaults)
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    cfg = _merge_defaults(defaults, raw)
    validate_config(cfg, kind)
    return cfg


def save_config(path: str | Path, cfg: dict[str, Any], kind: str) -> None:
    validate_config(cfg, kind)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def validate_config(cfg: dict[str, Any], kind: str) -> None:
    if kind == "transmitter":
        _validate_transmitter(cfg)
    elif kind == "receiver":
        _validate_receiver(cfg)
    else:
        raise ValueError(f"Unknown config kind: {kind}")


def _validate_transmitter(cfg: dict[str, Any]) -> None:
    if not isinstance(cfg.get("receiver_host"), str) or not cfg["receiver_host"].strip():
        raise ValueError("receiver_host must be a non-empty string")
    port = cfg.get("receiver_port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError("receiver_port must be an integer 1..65535")
    source = cfg.get("source")
    if source not in ("loopback", "device"):
        raise ValueError('source must be "loopback" or "device"')
    _validate_audio_common(cfg)
    bind = cfg.get("bind_local_ip", "")
    if bind is not None and not isinstance(bind, str):
        raise ValueError("bind_local_ip must be a string")


def _validate_receiver(cfg: dict[str, Any]) -> None:
    host = cfg.get("listen_host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("listen_host must be a non-empty string")
    port = cfg.get("listen_port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError("listen_port must be an integer 1..65535")
    tx = cfg.get("transmitter_host", "")
    if tx is not None and not isinstance(tx, str):
        raise ValueError("transmitter_host must be a string")
    jitter = cfg.get("jitter_ms")
    if not isinstance(jitter, int) or jitter < 0 or jitter > 1000:
        raise ValueError("jitter_ms must be an integer 0..1000")
    volume = cfg.get("volume")
    if not isinstance(volume, (int, float)) or not (0.0 <= float(volume) <= 2.0):
        raise ValueError("volume must be a number 0.0..2.0")
    _validate_audio_common(cfg)


def _validate_audio_common(cfg: dict[str, Any]) -> None:
    rate = cfg.get("sample_rate")
    if not isinstance(rate, int) or rate < 8000 or rate > 192000:
        raise ValueError("sample_rate must be an integer 8000..192000")
    channels = cfg.get("channels")
    if not isinstance(channels, int) or channels < 1 or channels > 8:
        raise ValueError("channels must be an integer 1..8")
    if "blocksize" in cfg:
        block = cfg["blocksize"]
        if not isinstance(block, int) or block < 64 or block > 8192:
            raise ValueError("blocksize must be an integer 64..8192")
