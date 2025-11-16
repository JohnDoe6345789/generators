#!/usr/bin/env bash
# Helper entry point for invoking the most common workflows.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
DEFAULT_TARGET="tests"
TARGET="${1:-$DEFAULT_TARGET}"
if [ "$#" -gt 0 ]; then
  shift
fi

activate_env() {
  if [ -d "$VENV_DIR" ]; then
    # shellcheck disable=SC1090
    source "$VENV_DIR/bin/activate"
  else
    echo "Virtual environment not found at $VENV_DIR" >&2
    echo "Run ./setup.sh first or set VENV_DIR to a valid environment." >&2
    exit 1
  fi
}

run_tests() {
  activate_env
  export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"
  python -m pytest "$ROOT_DIR/tests" "$@"
}

run_generator() {
  activate_env
  export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"
  python -m generators.simplyretro_d8_generator "$@"
}

run_module() {
  activate_env
  export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"
  python "$@"
}

usage() {
  cat <<USAGE
Usage: ./run.sh [command] [args]

Commands:
  tests [pytest-args]        Run the Python test suite (default).
  generator [options]        Execute the SimplyRetro D8 generator.
  module <module> [args]     Run an arbitrary module under src/.
  help                       Print this help text.

Each command automatically activates the .venv virtual environment and
ensures src/ is added to PYTHONPATH.
USAGE
}

case "$TARGET" in
  tests)
    run_tests "$@"
    ;;
  generator)
    run_generator "$@"
    ;;
  module)
    if [ "$#" -eq 0 ]; then
      echo "Please provide a module path, e.g. generators.jigsaw_generator" >&2
      exit 1
    fi
    mod="$1"
    shift
    run_module -m "$mod" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $TARGET" >&2
    usage
    exit 1
    ;;
esac
