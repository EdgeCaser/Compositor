#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --quiet --disable-pip-version-check pyinstaller pyyaml
python -m PyInstaller packaging/compositor.spec --noconfirm --clean
echo
echo "Built: $(pwd)/dist/compositor"
