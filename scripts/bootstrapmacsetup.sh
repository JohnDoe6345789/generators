#!/usr/bin/env bash
set -euo pipefail

this_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py_script="${this_dir}/mac_app_installer.py"

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

init_brew_env() {
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
}

ensure_homebrew() {
  if have_cmd brew; then
    return 0
  fi
  echo "[*] Homebrew not found, installing…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
}

python_can_import_tk() {
  local py="$1"
  "$py" - << 'PY' >/dev/null 2>&1
import tkinter  # noqa: F401
PY
}

detect_python() {
  local cand
  # Prefer Homebrew Python only; avoid Apple /usr/bin/python3 which can be OS-gated
  for cand in \
    /opt/homebrew/bin/python3 \
    /opt/homebrew/opt/python@3.14/bin/python3 \
    /usr/local/bin/python3
  do
    if [[ -x "$cand" ]] && python_can_import_tk "$cand"; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

ensure_brew_python_with_tk() {
  echo "[*] Ensuring Homebrew Python 3.14 + Tkinter…"
  brew list python@3.14 >/dev/null 2>&1 || brew install python@3.14
  brew list python-tk@3.14 >/dev/null 2>&1 || brew install python-tk@3.14
  # Best effort: make sure Tk bits are visible to that Python
  brew link --force python-tk@3.14 >/dev/null 2>&1 || true
}

main() {
  if [[ ! -f "${py_script}" ]]; then
    echo "[!] Missing Python GUI script: ${py_script}" >&2
    exit 1
  fi

  # First, load Homebrew into PATH if already installed
  init_brew_env

  # Then, install Homebrew if missing
  ensure_homebrew

  # And load the fresh Homebrew environment again
  init_brew_env

  # Make sure Brew Python + Tk is present
  ensure_brew_python_with_tk

  local py_cmd
  if py_cmd="$(detect_python)"; then
    echo "[*] Using Homebrew Python with Tkinter: ${py_cmd}"
  else
    echo "[!] Could not find a Homebrew Python that can import tkinter." >&2
    echo "[!] Check output of: brew info python@3.14 python-tk@3.14" >&2
    exit 1
  fi

  "${py_cmd}" "${py_script}"
}

main "$@"
