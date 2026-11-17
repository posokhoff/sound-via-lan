#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT="$ROOT/packages/linux"
WORK="$ROOT/build/pyinstaller"
DIST="$ROOT/build/dist"

python3 -m pip install -r requirements-build.txt

rm -rf "$WORK" "$DIST" "$OUT"
mkdir -p "$OUT"

python3 -m PyInstaller packaging/transmitter.spec --noconfirm --clean --distpath "$DIST" --workpath "$WORK"
python3 -m PyInstaller packaging/receiver.spec --noconfirm --clean --distpath "$DIST" --workpath "$WORK"

cp -a "$DIST/sound-transmitter" "$OUT/"
cp -a "$DIST/sound-receiver" "$OUT/"
mkdir -p "$OUT/configs"
cp configs/transmitter.example.json configs/receiver.example.json "$OUT/configs/"
cp README.md DISTRIBUTION.md "$OUT/" 2>/dev/null || true

# Ensure executables are marked executable
chmod +x "$OUT/sound-transmitter/sound-transmitter" "$OUT/sound-receiver/sound-receiver"

ZIP="$ROOT/packages/sound-via-lan-linux-x64.zip"
rm -f "$ZIP"
(cd "$OUT" && zip -r "$ZIP" .)

echo "Linux package ready:"
echo "  folder: $OUT"
echo "  zip:    $ZIP"
