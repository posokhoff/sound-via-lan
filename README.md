# Sound via LAN

Cross-platform LAN audio streaming: **Transmitter** captures system sound or a microphone and sends PCM over UDP; **Receiver** plays it on the local audio output.

Typical setup: Transmitter on **Windows**, Receiver on **Ubuntu**. Both apps also run on the other OS.

**Готовые пакеты:** см. [Releases](https://github.com/posokhoff/sound-via-lan/releases) и краткую инструкцию в [DISTRIBUTION.md](DISTRIBUTION.md).

## Features

- Source selection: system loopback or input device / microphone
- GUI (PySide6) and headless mode via JSON config
- Configurable IPs, ports, sample rate, channels, jitter buffer, volume
- Receiver can filter packets by transmitter IP

## Requirements

- Python **3.11+**
- Dependencies: `sounddevice`, `soundcard`, `numpy`, `PySide6-Essentials`

### Windows

```powershell
cd D:\Projects\sound_via_lan
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Ubuntu

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip portaudio19-dev libgl1 libpulse-dev
cd ~/sound_via_lan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Allow UDP on the receiver (example port `5005`):

```bash
sudo ufw allow 5005/udp
```

On Windows, allow outbound UDP to the receiver (or create an inbound rule on the Linux host firewall).

## Quick start

1. Copy examples and edit IPs:

```bash
cp configs/transmitter.example.json configs/transmitter.json
cp configs/receiver.example.json configs/receiver.json
```

2. On the **receiver** (Linux): set `transmitter_host` to the Windows PC IP (or leave empty to accept any). Start first:

```bash
python -m receiver --config configs/receiver.json
# or headless:
python -m receiver --config configs/receiver.json --headless
```

3. On the **transmitter** (Windows): set `receiver_host` to the Linux IP. Start:

```powershell
python -m transmitter --config configs\transmitter.json
# or headless:
python -m transmitter --config configs\transmitter.json --headless
```

Without `--config`, the GUI opens with built-in defaults. Use **Save config** to write a JSON file.

## Config reference

### Transmitter

| Field | Description |
| --- | --- |
| `receiver_host` | IP/hostname of the receiver |
| `receiver_port` | UDP port (default `5005`) |
| `source` | `"loopback"` (system audio) or `"device"` (mic / input) |
| `device_id` | Device index, name substring, or `null` for default |
| `sample_rate` | e.g. `48000` |
| `channels` | e.g. `2` |
| `blocksize` | Frames per callback (~960 ≈ 20 ms at 48 kHz) |
| `bind_local_ip` | Optional local bind address |

### Receiver

| Field | Description |
| --- | --- |
| `listen_host` | Bind address (`0.0.0.0` = all interfaces) |
| `listen_port` | UDP port |
| `transmitter_host` | Accept only this IP; empty = any |
| `output_device_id` | Output device index/name or `null` |
| `sample_rate` / `channels` | Initial format (auto-adapts to stream) |
| `jitter_ms` | Jitter buffer target depth |
| `volume` | `0.0`–`2.0` |

Generate defaults:

```bash
python -m transmitter --save-defaults configs/transmitter.json
python -m receiver --save-defaults configs/receiver.json
```

## Loopback notes

- **Windows:** system sound is captured via **soundcard** WASAPI loopback of the default (or selected) playback device.
- **Linux:** uses PulseAudio/PipeWire loopback/monitor devices exposed by soundcard. If none appear, set `source` to `device` and pick a monitor/input manually.

Keep `sample_rate` and `channels` the same on both sides for the lowest latency/startup friction (receiver still reconfigures if the stream format changes).

## Protocol

UDP packets: 16-byte header + PCM s16le interleaved samples.

```
magic(4)="SVLN" | seq(u32) | sample_rate(u32) | channels(u16) | flags(u16) | pcm...
```

## Project layout

```
shared/         protocol, config, device helpers
transmitter/    capture + UDP send + GUI
receiver/       UDP listen + jitter buffer + playback + GUI
configs/        example JSON configs
packaging/      PyInstaller specs and build scripts
```

## Build binary packages

```powershell
.\packaging\build_windows.ps1
```

```bash
bash packaging/build_linux.sh
```

CI builds ZIP artifacts on version tags (`v*`). Details: [DISTRIBUTION.md](DISTRIBUTION.md).
