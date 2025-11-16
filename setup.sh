#!/usr/bin/env bash
# Bootstrap a Python virtual environment and install all dependencies.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Unable to find Python interpreter '$PYTHON_BIN'." >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "Reusing existing virtual environment in $VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
if [ -f "$ROOT_DIR/requirements.txt" ]; then
  python -m pip install -r "$ROOT_DIR/requirements.txt"
fi

echo "Environment ready. Activate it with 'source $VENV_DIR/bin/activate'."
