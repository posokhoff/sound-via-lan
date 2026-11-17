"""UDP packet sender for PCM frames."""

from __future__ import annotations

import socket
from typing import Callable

from shared.protocol import pack_packet


class UdpSender:
    def __init__(
        self,
        host: str,
        port: int,
        bind_local_ip: str = "",
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.bind_local_ip = (bind_local_ip or "").strip()
        self.on_error = on_error
        self._sock: socket.socket | None = None
        self._seq = 0
        self.bytes_sent = 0
        self.packets_sent = 0

    def open(self) -> None:
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Larger send buffer helps under load
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        except OSError:
            pass
        if self.bind_local_ip:
            sock.bind((self.bind_local_ip, 0))
        self._sock = sock
        self._seq = 0
        self.bytes_sent = 0
        self.packets_sent = 0

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def seq(self) -> int:
        return self._seq

    def send_pcm(self, sample_rate: int, channels: int, pcm: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("UDP sender is not open")
        packet = pack_packet(self._seq, sample_rate, channels, pcm)
        try:
            self._sock.sendto(packet, (self.host, self.port))
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            self.bytes_sent += len(packet)
            self.packets_sent += 1
        except OSError as exc:
            if self.on_error:
                self.on_error(f"UDP send error: {exc}")
            else:
                raise
