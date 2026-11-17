# Дистрибуция Sound via LAN

## Готовые пакеты

Скачайте ZIP с [Releases](https://github.com/posokhoff/sound-via-lan/releases):

| Файл | Платформа |
| --- | --- |
| `sound-via-lan-windows-x64.zip` | Windows 10/11 x64 |
| `sound-via-lan-linux-x64.zip` | Ubuntu 22.04+ x64 |

### Windows

1. Распакуйте ZIP.
2. На ПК-источнике запустите `sound-transmitter\sound-transmitter.exe`.
3. Укажите IP Linux-приёмника, источник (loopback / микрофон), Start.
4. На приёмнике — `sound-receiver\sound-receiver.exe`, укажите IP трансмиттера (или оставьте пустым), Start.
5. Разрешите UDP (порт по умолчанию `5005`) в брандмауэре приёмника.

Headless:

```powershell
.\sound-transmitter\sound-transmitter.exe --config configs\transmitter.example.json --headless
.\sound-receiver\sound-receiver.exe --config configs\receiver.example.json --headless
```

### Linux (Ubuntu)

```bash
sudo apt install -y libportaudio2 libpulse0 libgl1
unzip sound-via-lan-linux-x64.zip -d sound-via-lan
cd sound-via-lan
./sound-receiver/sound-receiver --config configs/receiver.example.json
# или
./sound-transmitter/sound-transmitter --config configs/transmitter.example.json
```

Откройте порт: `sudo ufw allow 5005/udp`.

## Сборка пакетов самостоятельно

```powershell
# Windows
.\packaging\build_windows.ps1
```

```bash
# Linux
bash packaging/build_linux.sh
```

Артефакты: `packages/sound-via-lan-windows-x64.zip` / `packages/sound-via-lan-linux-x64.zip`.

CI: workflow `.github/workflows/build-packages.yml` собирает оба ZIP на tag `v*` или вручную (workflow_dispatch).

## Альтернатива: из исходников

```bash
pip install -r requirements.txt
python -m transmitter
python -m receiver
```
