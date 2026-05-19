#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! python -c "import yaml" >/dev/null 2>&1; then
    echo "Installing PyYAML..."
    python -m pip install --quiet --disable-pip-version-check pyyaml
fi
PYTHONPATH="$PWD/src" python -m compositor --open
