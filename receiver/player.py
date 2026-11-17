"""Jitter buffer and sounddevice playback."""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd

from shared.audio_devices import resolve_output_device
from shared.protocol import PacketHeader


StatusCallback = Callable[[str], None]


class JitterBuffer:
    """Order packets by sequence; fill gaps with silence."""

    def __init__(self, jitter_ms: int, sample_rate: int, channels: int, frame_samples: int = 960) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_samples = frame_samples
        self.target_frames = max(1, int((jitter_ms / 1000.0) * sample_rate / max(1, frame_samples)))
        self._lock = threading.Lock()
        self._pending: dict[int, bytes] = {}
        self._next_seq: int | None = None
        self._ready = deque()  # type: deque[bytes]
        self.underruns = 0
        self.late_drops = 0
        self.started = False

    def configure(self, sample_rate: int, channels: int, frame_samples: int, jitter_ms: int) -> None:
        with self._lock:
            self.sample_rate = sample_rate
            self.channels = channels
            self.frame_samples = max(1, frame_samples)
            self.target_frames = max(1, int((jitter_ms / 1000.0) * sample_rate / self.frame_samples))
            self._pending.clear()
            self._ready.clear()
            self._next_seq = None
            self.started = False

    def push(self, header: PacketHeader, pcm: bytes) -> None:
        with self._lock:
            if self._next_seq is None:
                self._next_seq = header.seq
            # Drop very late packets (wrap-aware distance)
            if self._seq_before(header.seq, self._next_seq):
                self.late_drops += 1
                return
            self._pending[header.seq] = pcm
            self._drain_pending_unlocked()

    def _seq_before(self, a: int, b: int) -> bool:
        return ((a - b) & 0xFFFFFFFF) > 0x80000000

    def _silence_frame(self) -> bytes:
        return b"\x00" * (self.frame_samples * self.channels * 2)

    def _drain_pending_unlocked(self) -> None:
        assert self._next_seq is not None
        # Emit contiguous frames; if gap and we already started playback priming, insert silence
        while True:
            if self._next_seq in self._pending:
                self._ready.append(self._pending.pop(self._next_seq))
                self._next_seq = (self._next_seq + 1) & 0xFFFFFFFF
                continue
            # Gap: if we have later packets and buffer already primed, skip with silence
            if self.started and self._pending:
                # Only fill one silence per call cycle to avoid flooding
                farthest = max(self._pending.keys(), key=lambda s: (s - self._next_seq) & 0xFFFFFFFF)
                dist = (farthest - self._next_seq) & 0xFFFFFFFF
                if dist > 0 and dist < 1000:
                    self._ready.append(self._silence_frame())
                    self._next_seq = (self._next_seq + 1) & 0xFFFFFFFF
                    continue
            break

        # Cap pending queue size
        max_pending = self.target_frames * 8 + 16
        if len(self._pending) > max_pending:
            keep = sorted(self._pending.keys(), key=lambda s: (s - self._next_seq) & 0xFFFFFFFF)[
                : max_pending // 2
            ]
            self._pending = {k: self._pending[k] for k in keep}

    def primed(self) -> bool:
        with self._lock:
            return len(self._ready) >= self.target_frames

    def pop_samples(self, frames: int) -> np.ndarray:
        """Return float32 array shape (frames, channels)."""
        need_bytes = frames * self.channels * 2
        with self._lock:
            if not self.started:
                if len(self._ready) < self.target_frames:
                    return np.zeros((frames, self.channels), dtype=np.float32)
                self.started = True

            buf = bytearray()
            while len(buf) < need_bytes:
                if self._ready:
                    buf.extend(self._ready.popleft())
                elif self._next_seq is not None and self._next_seq in self._pending:
                    self._drain_pending_unlocked()
                    if self._ready:
                        buf.extend(self._ready.popleft())
                    else:
                        break
                else:
                    break

            if len(buf) < need_bytes:
                self.underruns += 1
                buf.extend(b"\x00" * (need_bytes - len(buf)))
            else:
                # Keep leftover for next callback if we overshot a frame boundary
                leftover = bytes(buf[need_bytes:])
                buf = buf[:need_bytes]
                if leftover:
                    self._ready.appendleft(leftover)

        pcm = np.frombuffer(bytes(buf), dtype=np.int16)
        audio = pcm.astype(np.float32) / 32767.0
        return audio.reshape(-1, self.channels)

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._ready)


class AudioPlayer:
    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        jitter_ms: int = 60,
        volume: float = 1.0,
        output_device_id: int | str | None = None,
        on_status: StatusCallback | None = None,
        on_error: StatusCallback | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.jitter_ms = jitter_ms
        self.volume = float(volume)
        self.output_device_id = output_device_id
        self.on_status = on_status
        self.on_error = on_error
        self.buffer = JitterBuffer(jitter_ms, sample_rate, channels)
        self._stream: sd.OutputStream | None = None
        self.running = False
        self._frame_samples = 960
        self._lock = threading.Lock()

    def _emit(self, msg: str) -> None:
        if self.on_status:
            self.on_status(msg)

    def _err(self, msg: str) -> None:
        if self.on_error:
            self.on_error(msg)
        else:
            self._emit(msg)

    def start(self) -> None:
        if self.running:
            return
        device = resolve_output_device(self.output_device_id)
        self.buffer.configure(self.sample_rate, self.channels, self._frame_samples, self.jitter_ms)

        def callback(outdata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
            if status:
                self._emit(f"Playback warning: {status}")
            chunk = self.buffer.pop_samples(frames)
            if chunk.shape[0] < frames:
                padded = np.zeros((frames, self.channels), dtype=np.float32)
                padded[: chunk.shape[0]] = chunk
                chunk = padded
            vol = self.volume
            outdata[:] = chunk * vol

        try:
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=device,
                callback=callback,
                blocksize=0,
            )
            self._stream.start()
            self.running = True
            self._emit(
                f"Playback started @ {self.sample_rate} Hz / {self.channels} ch "
                f"(device={device}, jitter={self.jitter_ms} ms)"
            )
        except Exception as exc:
            self._stream = None
            self.running = False
            raise RuntimeError(f"Failed to start playback: {exc}") from exc

    def stop(self) -> None:
        self.running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
        self._emit("Playback stopped")

    def push_packet(self, header: PacketHeader, pcm: bytes) -> None:
        # Adapt format if transmitter changes parameters
        if header.sample_rate != self.sample_rate or header.channels != self.channels:
            self._reconfigure(header.sample_rate, header.channels)

        samples = len(pcm) // (2 * max(1, header.channels))
        if samples > 0:
            with self._lock:
                if samples != self._frame_samples:
                    self._frame_samples = samples
                    self.buffer.configure(
                        self.sample_rate, self.channels, self._frame_samples, self.jitter_ms
                    )
        self.buffer.push(header, pcm)

    def _reconfigure(self, sample_rate: int, channels: int) -> None:
        with self._lock:
            if sample_rate == self.sample_rate and channels == self.channels:
                return
            self._emit(f"Format change: {sample_rate} Hz / {channels} ch — restarting output")
            was_running = self.running
            self.stop()
            self.sample_rate = sample_rate
            self.channels = channels
            if was_running:
                try:
                    self.start()
                except Exception as exc:  # noqa: BLE001
                    self._err(str(exc))

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(2.0, float(volume)))
