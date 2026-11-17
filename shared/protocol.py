"""Binary UDP packet format for PCM audio streaming."""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"SVLN"
HEADER_FORMAT = "!4sIIHH"  # magic, seq, sample_rate, channels, flags
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

FLAG_NONE = 0


@dataclass(frozen=True)
class PacketHeader:
    seq: int
    sample_rate: int
    channels: int
    flags: int = FLAG_NONE


def pack_packet(
    seq: int,
    sample_rate: int,
    channels: int,
    pcm: bytes,
    flags: int = FLAG_NONE,
) -> bytes:
    header = struct.pack(HEADER_FORMAT, MAGIC, seq & 0xFFFFFFFF, sample_rate, channels, flags)
    return header + pcm


def unpack_packet(data: bytes) -> tuple[PacketHeader, bytes] | None:
    if len(data) < HEADER_SIZE:
        return None
    magic, seq, sample_rate, channels, flags = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if magic != MAGIC:
        return None
    if channels < 1 or channels > 8:
        return None
    if sample_rate < 8000 or sample_rate > 192000:
        return None
    return PacketHeader(seq=seq, sample_rate=sample_rate, channels=channels, flags=flags), data[HEADER_SIZE:]
