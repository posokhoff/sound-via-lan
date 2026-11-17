"""Audio capture: soundcard (WASAPI/Pulse loopback) or sounddevice (mic/input)."""

from __future__ import annotations

import sys
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

from shared.audio_devices import resolve_input_device
from transmitter.sender import UdpSender


StatusCallback = Callable[[str], None]


class AudioCapture:
    def __init__(
        self,
        sender: UdpSender,
        source: str = "loopback",
        device_id: int | str | None = None,
        sample_rate: int = 48000,
        channels: int = 2,
        blocksize: int = 960,
        on_status: StatusCallback | None = None,
        on_error: StatusCallback | None = None,
    ) -> None:
        self.sender = sender
        self.source = source
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.on_status = on_status
        self.on_error = on_error
        self._stream: sd.InputStream | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.running = False
        self.frames_captured = 0
        self._backend = ""

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

        device, extra = resolve_input_device(self.source, self.device_id)
        self.sender.open()
        self._stop.clear()

        try:
            if device == "soundcard":
                self._start_soundcard(extra["microphone"])
            else:
                self._start_sounddevice(device, extra)
        except Exception:
            self.sender.close()
            self.running = False
            raise

    def _send_float_block(self, indata: np.ndarray) -> None:
        if indata.ndim == 1:
            indata = indata.reshape(-1, 1)
        # Match configured channel count
        if indata.shape[1] > self.channels:
            indata = indata[:, : self.channels]
        elif indata.shape[1] < self.channels:
            padded = np.zeros((indata.shape[0], self.channels), dtype=np.float32)
            padded[:, : indata.shape[1]] = indata
            indata = padded
        clipped = np.clip(indata, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16).tobytes()
        self.sender.send_pcm(self.sample_rate, self.channels, pcm)
        self.frames_captured += indata.shape[0]

    def _start_soundcard(self, microphone) -> None:
        self._backend = "soundcard"
        # Prefer mic's native channel count when user left stereo default
        mic_ch = int(getattr(microphone, "channels", self.channels) or self.channels)
        channels = self.channels if self.channels > 0 else mic_ch

        def worker() -> None:
            # WASAPI/COM must be initialized per thread on Windows
            coinitialized = False
            if sys.platform == "win32":
                try:
                    import ctypes

                    ctypes.windll.ole32.CoInitialize(None)
                    coinitialized = True
                except Exception:  # noqa: BLE001
                    pass
            try:
                with microphone.recorder(
                    samplerate=self.sample_rate,
                    channels=min(channels, mic_ch) if mic_ch > 0 else channels,
                ) as rec:
                    self.running = True
                    self._emit(
                        f"Streaming loopback via soundcard ({microphone.name}) "
                        f"@ {self.sample_rate} Hz / {self.channels} ch "
                        f"→ {self.sender.host}:{self.sender.port}"
                    )
                    while not self._stop.is_set():
                        data = rec.record(numframes=self.blocksize)
                        if data is None or len(data) == 0:
                            continue
                        try:
                            self._send_float_block(np.asarray(data, dtype=np.float32))
                        except Exception as exc:  # noqa: BLE001
                            self._err(f"Send failed: {exc}")
                            break
            except Exception as exc:  # noqa: BLE001
                self._err(f"Loopback capture failed: {exc}")
            finally:
                self.running = False
                if coinitialized:
                    try:
                        import ctypes

                        ctypes.windll.ole32.CoUninitialize()
                    except Exception:  # noqa: BLE001
                        pass

        self._thread = threading.Thread(target=worker, name="loopback-capture", daemon=True)
        self._thread.start()
        # Wait briefly for recorder open / immediate failure
        for _ in range(40):
            if self.running or not self._thread.is_alive():
                break
            self._stop.wait(0.05)
        if not self._thread.is_alive() and not self.running:
            raise RuntimeError("Loopback capture thread exited immediately")
        self.running = True

    def _start_sounddevice(self, device, extra: dict) -> None:
        self._backend = "sounddevice"

        def callback(indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
            if status:
                self._emit(f"Capture warning: {status}")
            try:
                self._send_float_block(indata)
            except Exception as exc:  # noqa: BLE001
                self._err(f"Send failed: {exc}")

        kwargs: dict = {
            "samplerate": self.sample_rate,
            "channels": self.channels,
            "dtype": "float32",
            "blocksize": self.blocksize,
            "callback": callback,
            "device": device,
        }
        if "extra_settings" in extra:
            kwargs["extra_settings"] = extra["extra_settings"]

        try:
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
            self.running = True
            self._emit(
                f"Streaming {self.source} @ {self.sample_rate} Hz / {self.channels} ch "
                f"→ {self.sender.host}:{self.sender.port} (device={device})"
            )
        except Exception as exc:
            self._stream = None
            self.running = False
            raise RuntimeError(f"Failed to start capture: {exc}") from exc

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
        self.sender.close()
        self._emit("Stopped")
