"""UDP listener that filters packets by transmitter IP."""

from __future__ import annotations

import select
import socket
import threading
from typing import Callable

from shared.protocol import PacketHeader, unpack_packet


PacketHandler = Callable[[PacketHeader, bytes, tuple[str, int]], None]
StatusCallback = Callable[[str], None]


class UdpListener:
    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        transmitter_host: str = "",
        on_packet: PacketHandler | None = None,
        on_status: StatusCallback | None = None,
        on_error: StatusCallback | None = None,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.transmitter_host = (transmitter_host or "").strip()
        self.on_packet = on_packet
        self.on_status = on_status
        self.on_error = on_error
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.packets_received = 0
        self.packets_dropped_filter = 0
        self.packets_bad = 0
        self.bytes_received = 0
        self.last_addr: tuple[str, int] | None = None

    def _emit(self, msg: str) -> None:
        if self.on_status:
            self.on_status(msg)

    def _err(self, msg: str) -> None:
        if self.on_error:
            self.on_error(msg)
        else:
            self._emit(msg)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        except OSError:
            pass
        sock.bind((self.listen_host, self.listen_port))
        sock.setblocking(False)
        self._sock = sock
        self.packets_received = 0
        self.packets_dropped_filter = 0
        self.packets_bad = 0
        self.bytes_received = 0
        self._thread = threading.Thread(target=self._loop, name="udp-listener", daemon=True)
        self._thread.start()
        filter_msg = self.transmitter_host or "any"
        self._emit(f"Listening on {self.listen_host}:{self.listen_port} (TX filter={filter_msg})")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._emit("Listener stopped")

    def _allowed(self, addr: str) -> bool:
        if not self.transmitter_host:
            return True
        return addr == self.transmitter_host

    def _loop(self) -> None:
        assert self._sock is not None
        sock = self._sock
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([sock], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                data, addr = sock.recvfrom(65535)
            except BlockingIOError:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self._err(f"UDP recv error: {exc}")
                break

            host, port = addr[0], addr[1]
            if not self._allowed(host):
                self.packets_dropped_filter += 1
                continue

            parsed = unpack_packet(data)
            if parsed is None:
                self.packets_bad += 1
                continue

            header, payload = parsed
            self.packets_received += 1
            self.bytes_received += len(data)
            self.last_addr = (host, port)
            if self.on_packet:
                try:
                    self.on_packet(header, payload, (host, port))
                except Exception as exc:  # noqa: BLE001
                    self._err(f"Packet handler error: {exc}")
