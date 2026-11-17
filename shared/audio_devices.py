"""Enumerate audio devices and resolve loopback / input capture."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any

import sounddevice as sd


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    hostapi_name: str
    is_loopback: bool = False
    backend: str = "sounddevice"  # sounddevice | soundcard
    soundcard_id: str | None = None


def list_hostapis() -> list[dict[str, Any]]:
    return list(sd.query_hostapis())


def _hostapi_name(index: int) -> str:
    try:
        return str(sd.query_hostapis(index)["name"])
    except Exception:
        return ""


def list_devices(kind: str | None = None) -> list[DeviceInfo]:
    """Return devices. kind: 'input' | 'output' | 'loopback' | None (all)."""
    result: list[DeviceInfo] = []

    if kind in (None, "loopback", "input"):
        result.extend(_list_soundcard_loopbacks())

    raw = sd.query_devices()
    for i, d in enumerate(raw):
        name = str(d["name"])
        max_in = int(d["max_input_channels"])
        max_out = int(d["max_output_channels"])
        if kind == "input" and max_in <= 0:
            continue
        if kind == "output" and max_out <= 0:
            continue
        if kind == "loopback":
            continue
        host = _hostapi_name(int(d["hostapi"]))
        is_loopback = _looks_like_loopback(name, host)
        if kind == "input" and is_loopback:
            # Prefer soundcard entries for true loopback
            pass
        result.append(
            DeviceInfo(
                index=i,
                name=name,
                max_input_channels=max_in,
                max_output_channels=max_out,
                default_samplerate=float(d["default_samplerate"]),
                hostapi_name=host,
                is_loopback=is_loopback,
                backend="sounddevice",
            )
        )
    return result


def _list_soundcard_loopbacks() -> list[DeviceInfo]:
    try:
        import soundcard as sc
    except ImportError:
        return []

    items: list[DeviceInfo] = []
    # Negative synthetic indices for soundcard loopbacks so they don't clash
    base = -1000
    try:
        mics = sc.all_microphones(include_loopback=True)
    except Exception:
        return []

    for offset, mic in enumerate(mics):
        is_loop = bool(getattr(mic, "isloopback", False))
        if not is_loop:
            continue
        name = str(mic.name)
        channels = int(getattr(mic, "channels", 2) or 2)
        items.append(
            DeviceInfo(
                index=base - offset,
                name=f"Loopback: {name}",
                max_input_channels=channels,
                max_output_channels=0,
                default_samplerate=48000.0,
                hostapi_name="WASAPI/Pulse (soundcard)",
                is_loopback=True,
                backend="soundcard",
                soundcard_id=str(mic.id),
            )
        )
    return items


def _looks_like_loopback(name: str, hostapi: str) -> bool:
    lower = name.lower()
    markers = (
        "loopback",
        "stereo mix",
        "what u hear",
        "wave out mix",
        "monitor of",
        ".monitor",
    )
    return any(m in lower for m in markers)


def find_loopback_device() -> DeviceInfo | None:
    loopbacks = [d for d in list_devices("loopback") if d.is_loopback]
    if loopbacks:
        # Prefer default speaker name match
        try:
            import soundcard as sc

            default_name = str(sc.default_speaker().name).lower()
            for d in loopbacks:
                if default_name and default_name in d.name.lower():
                    return d
        except Exception:
            pass
        return loopbacks[0]

    inputs = list_devices("input")
    for d in inputs:
        if d.is_loopback and d.backend == "sounddevice":
            return d
    return None


def resolve_loopback_microphone(device_id: int | str | None = None):
    """Return a soundcard Microphone object configured for loopback."""
    import soundcard as sc

    if device_id is not None:
        # Match by soundcard synthetic index or name
        for d in _list_soundcard_loopbacks():
            if d.index == device_id or (
                isinstance(device_id, str) and device_id.lower() in d.name.lower()
            ):
                return sc.get_microphone(id=d.soundcard_id, include_loopback=True)

        # Treat string as speaker/mic name
        if isinstance(device_id, str):
            return sc.get_microphone(id=device_id, include_loopback=True)

        # Positive sounddevice index: map output device name → loopback
        if isinstance(device_id, int) and device_id >= 0:
            try:
                name = str(sd.query_devices(device_id)["name"])
                return sc.get_microphone(id=name, include_loopback=True)
            except Exception as exc:
                raise RuntimeError(f"Cannot map device {device_id} to loopback: {exc}") from exc

    speaker = sc.default_speaker()
    return sc.get_microphone(id=str(speaker.name), include_loopback=True)


def resolve_input_device(source: str, device_id: int | str | None) -> tuple[Any, dict[str, Any]]:
    """
    Resolve capture target.

    For source=loopback returns ("soundcard", {"microphone": mic}).
    For source=device returns (device_index, {}) for sounddevice InputStream.
    """
    if source == "loopback":
        mic = resolve_loopback_microphone(device_id)
        return "soundcard", {"microphone": mic}

    if device_id is None:
        return sd.default.device[0], {}
    return _coerce_device_id(device_id), {}


def resolve_output_device(device_id: int | str | None) -> int | None:
    if device_id is None:
        return sd.default.device[1]
    return _coerce_device_id(device_id)


def _coerce_device_id(device_id: int | str) -> int:
    if isinstance(device_id, int):
        if device_id < 0:
            raise ValueError(
                f"Device index {device_id} is a loopback entry; use source=loopback"
            )
        return device_id
    name = str(device_id).strip().lower()
    if name.isdigit():
        return int(name)
    for d in list_devices():
        if d.backend != "sounddevice":
            continue
        if d.name.lower() == name or name in d.name.lower():
            return d.index
    raise ValueError(f"Audio device not found: {device_id!r}")


def platform_loopback_hint() -> str:
    system = platform.system()
    if system == "Windows":
        return (
            "Windows: system sound uses WASAPI loopback via soundcard "
            "(captures the selected/default playback device)."
        )
    if system == "Linux":
        return (
            "Linux: prefers PulseAudio/PipeWire monitor / loopback devices. "
            "If none appear, pick a monitor device manually."
        )
    return "Loopback support depends on the OS audio backend."


def default_channels_for_loopback(device_id: int | str | None = None) -> int:
    try:
        mic = resolve_loopback_microphone(device_id)
        ch = int(getattr(mic, "channels", 2) or 2)
        return max(1, ch)
    except Exception:
        return 2
