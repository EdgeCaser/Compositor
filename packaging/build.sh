#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --quiet --disable-pip-version-check pyinstaller pyyaml
python -m PyInstaller packaging/compositor.spec --noconfirm --clean

case "$(uname -s)" in
    Darwin) OUT="dist/compositor";;
    Linux)  OUT="dist/compositor";;
    *)      OUT="dist/compositor.exe";;
esac

echo
echo "Built: $(pwd)/$OUT"
echo "Size:  $(wc -c < "$OUT") bytes"

echo
echo "Computing SHA256..."
if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$OUT" | tee "$OUT.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$OUT" | tee "$OUT.sha256"
else
    echo "no shasum/sha256sum found, skipping hash"
fi
