#!/usr/bin/env bash
set -euo pipefail

# Script that adds /opt/homebrew/bin/python3 to PATH and aliases `python`.
block_tag="homebrew_python_alias"
block_start="# >>> ${block_tag} >>>"
block_end="# <<< ${block_tag} <<<"
default_py="/opt/homebrew/bin/python3"
default_config="${HOME}/.zshrc"

usage() {
  cat <<'EOF'
Usage: set_default_python.sh [CONFIG_FILE]

Adds a shell snippet that ensures /opt/homebrew/bin/python3 is invoked when
running `python`. Defaults to ~/.zshrc unless CONFIG_FILE is provided.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

config_file="${1:-$default_config}"

if [[ ! -x "$default_py" ]]; then
  echo "[!] ${default_py} is not executable. Install Homebrew Python first." >&2
  exit 1
fi

mkdir -p "$(dirname "$config_file")"
touch "$config_file"

if grep -qF "$block_start" "$config_file"; then
  echo "[*] Alias block already present in ${config_file}."
  exit 0
fi

cat <<EOF >>"$config_file"
$block_start
if [ -x "$default_py" ]; then
  case ":\$PATH:" in
    *":/opt/homebrew/bin:"*) ;;
    *) export PATH="/opt/homebrew/bin:\$PATH" ;;
  esac
  alias python='$default_py'
fi
$block_end
EOF

echo "[*] Alias added to ${config_file}. Reload your shell or run: source ${config_file}"
