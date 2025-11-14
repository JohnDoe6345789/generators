#!/opt/homebrew/bin/python3
"""
M4 Max Vibe Coding Setup Script (macOS)

Features:
- Tkinter GUI with log window + progress bar
- Fuzzy detection of existing tools (Homebrew, Ollama, VS Code, Continue)
- Installs missing components:
    * Homebrew
    * Ollama
    * VS Code (via Homebrew cask)
    * Continue.dev VS Code extension
- Configures Continue to use local Ollama models:
    * qwen2.5-coder:14b
    * deepseek-r1:14b
- Adds a 'vibe' shell function to ~/.zshrc for quick startup
- Uses AppleScript to request privilege elevation where needed

Run:
    python3 m4_vibe_setup.py
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.ttk as ttk
from queue import Empty, Queue


def is_macos_arm() -> bool:
    return (
        platform.system().lower() == "darwin"
        and platform.machine().lower() in ("arm64", "aarch64")
    )


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def run_cmd(
    cmd: list[str],
    log: Queue[str],
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.stdout:
            log.put(proc.stdout)
        if proc.stderr:
            log.put(proc.stderr)
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({cmd}): {proc.returncode}"
            )
        return proc
    except Exception as exc:
        log.put(f"[ERROR] {cmd}: {exc}\n")
        if check:
            raise
        return subprocess.CompletedProcess(
            cmd, 1, "", f"{exc}"
        )


def run_with_privileges(
    shell_cmd: str,
    log: Queue[str],
    check: bool = False,
) -> None:
    escaped = shell_cmd.replace('\\', '\\\\').replace('"', '\\"')

    osa_script = (
        f'do shell script "{escaped}" '
        'with administrator privileges'
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", osa_script],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.stdout:
            log.put(proc.stdout)
        if proc.stderr:
            log.put(proc.stderr)
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Privileged command failed: {proc.returncode}"
            )
    except Exception as exc:
        log.put(f"[ERROR] privileged cmd: {exc}\n")
        if check:
            raise


def detect_homebrew() -> bool:
    if which("brew") is not None:
        return True
    if Path("/opt/homebrew/bin/brew").exists():
        return True
    return False


def detect_ollama() -> bool:
    return which("ollama") is not None


def detect_vscode() -> bool:
    if which("code") is not None:
        return True
    if Path("/Applications/Visual Studio Code.app").exists():
        return True
    return False


def detect_continue_extension(
    log: Queue[str],
) -> bool:
    code_path = which("code")
    if code_path is None:
        log.put(
            "[WARN] VS Code CLI 'code' not found. "
            "Skipping precise Continue detection.\n"
        )
        return False
    proc = run_cmd(
        [code_path, "--list-extensions"],
        log,
        check=False,
    )
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        if "continue.continue" in line.lower():
            return True
    return False


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def install_homebrew(log: Queue[str]) -> None:
    if detect_homebrew():
        log.put("[OK] Homebrew already installed (fuzzy detected).\n")
        return
    log.put("[INFO] Installing Homebrew...\n")
    cmd = (
        '/bin/bash -c '
        '"$(curl -fsSL https://raw.githubusercontent.com/'
        'Homebrew/install/HEAD/install.sh)"'
    )
    run_with_privileges(cmd, log, check=True)
    log.put(
        "[OK] Homebrew installation attempted. "
        "You may need to restart Terminal.\n"
    )


def install_ollama(log: Queue[str]) -> None:
    if detect_ollama():
        log.put("[OK] Ollama already installed (fuzzy detected).\n")
        return

    log.put("[INFO] Installing Ollama...\n")

    if detect_homebrew():
        brew = which("brew") or "/opt/homebrew/bin/brew"
        run_cmd([
            brew,
            "update",
        ], log, check=False)
        run_cmd([
            brew,
            "install",
            "--cask",
            "ollama",
        ], log, check=False)
        log.put("[OK] Ollama install via Homebrew attempted.\n")
    else:
        log.put(
            "[WARN] Homebrew not found. Opening Ollama download page "
            "in your browser. Please install it manually, then rerun "
            "this setup.\n"
        )
        run_cmd([
            "open",
            "https://ollama.com/download/mac",
        ], log, check=False)


def install_vscode(log: Queue[str]) -> None:
    if detect_vscode():
        log.put("[OK] VS Code already installed (fuzzy detected).\n")
        return
    log.put("[INFO] Installing VS Code via Homebrew cask...\n")
    if not detect_homebrew():
        log.put(
            "[WARN] Homebrew not found after install attempt. "
            "VS Code install may fail.\n"
        )
    brew = which("brew") or "/opt/homebrew/bin/brew"
    run_cmd(
        [brew, "update"],
        log,
        check=False,
    )
    run_cmd(
        [brew, "install", "--cask", "visual-studio-code"],
        log,
        check=False,
    )
    log.put("[OK] VS Code install attempted.\n")


def install_continue(
    log: Queue[str],
) -> None:
    if detect_continue_extension(log):
        log.put("[OK] Continue extension already installed.\n")
        return
    log.put("[INFO] Installing Continue VS Code extension...\n")
    code_path = which("code")
    if code_path is None:
        log.put(
            "[WARN] Cannot find 'code' CLI. "
            "You may need to enable it from VS Code "
            "(Command Palette → 'Shell Command: "
            "Install 'code' command in PATH').\n"
        )
        return
    run_cmd(
        [code_path, "--install-extension", "Continue.continue"],
        log,
        check=False,
    )
    log.put("[OK] Continue extension install attempted.\n")


def ensure_ollama_healthy(log: Queue[str]) -> bool:
    if not detect_ollama():
        log.put(
            "[WARN] Ollama CLI not found. Skipping Ollama service checks.\n"
        )
        return False

    for attempt in range(3):
        proc = run_cmd(["pgrep", "-x", "ollama"], log, check=False)
        if proc.returncode != 0:
            log.put(
                "[INFO] Ollama server not running. Attempting to start it...\n"
            )
            run_cmd([
                "nohup",
                "ollama",
                "serve",
            ], log, check=False)
            time.sleep(2 + attempt * 2)

        health = run_cmd(
            [
                "curl",
                "-sSf",
                "http://127.0.0.1:11434/api/tags",
            ],
            log,
            check=False,
        )
        if health.returncode == 0:
            log.put("[OK] Ollama service is healthy.\n")
            return True

        log.put(
            f"[WARN] Ollama health check failed (attempt {attempt + 1}/3).\n"
        )
        time.sleep(2)

    log.put(
        "[ERROR] Ollama is installed but the service did not become healthy.\n"
    )
    return False


def pull_ollama_models(log: Queue[str]) -> None:
    if not ensure_ollama_healthy(log):
        return

    log.put("[INFO] Pulling qwen2.5-coder:14b...\n")
    run_cmd(
        ["ollama", "pull", "qwen2.5-coder:14b"],
        log,
        check=False,
    )
    log.put("[INFO] Pulling deepseek-r1:14b...\n")
    run_cmd(
        ["ollama", "pull", "deepseek-r1:14b"],
        log,
        check=False,
    )
    log.put("[OK] Model pulls attempted.\n")


def configure_continue(
    log: Queue[str],
) -> None:
    home = Path.home()
    cfg_dir = home / ".continue"
    ensure_dir(cfg_dir)
    cfg_file = cfg_dir / "config.json"

    base: dict[str, Any] = {
        "models": [
            {
                "title": "Qwen Coder 14B (local)",
                "provider": "ollama",
                "model": "qwen2.5-coder:14b",
                "apiBase": "http://localhost:11434",
            },
            {
                "title": "DeepSeek R1 14B (local)",
                "provider": "ollama",
                "model": "deepseek-r1:14b",
                "apiBase": "http://localhost:11434",
            },
        ],
        "tabAutocompleteModel": "Qwen Coder 14B (local)",
        "defaultModel": "Qwen Coder 14B (local)",
    }

    cfg_data: dict[str, Any]
    if cfg_file.exists():
        try:
            current = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            current = {}
        current["models"] = base["models"]
        current["tabAutocompleteModel"] = base["tabAutocompleteModel"]
        current["defaultModel"] = base["defaultModel"]
        cfg_data = current
        log.put(
            "[INFO] Updating existing Continue config with "
            "local Ollama models.\n"
        )
    else:
        cfg_data = base
        log.put(
            "[INFO] Creating new Continue config with "
            "local Ollama models.\n"
        )

    cfg_file.write_text(
        json.dumps(cfg_data, indent=2), encoding="utf-8"
    )
    log.put(f"[OK] Continue config written to {cfg_file}.\n")


def configure_vibe_alias(log: Queue[str]) -> None:
    home = Path.home()
    zshrc = home / ".zshrc"
    snippet_start = "# >>> vibe-coding setup >>>"
    snippet_end = "# <<< vibe-coding setup <<<"

    vibe_block = f"""
{snippet_start}
vibe() {{
    if ! pgrep -x "ollama" >/dev/null 2>&1; then
        nohup ollama serve >/tmp/ollama_serve.log 2>&1 &
        echo "Starting Ollama server..." >&2
        sleep 2
    fi
    if command -v code >/dev/null 2>&1; then
        code "$PWD"
    else
        echo "VS Code 'code' CLI not found. Please enable it." >&2
    fi
}}
{snippet_end}
"""

    if zshrc.exists():
        content = zshrc.read_text(encoding="utf-8")
        if snippet_start in content and snippet_end in content:
            log.put("[OK] 'vibe' function already present in ~/.zshrc.\n")
            return
        new_content = content + "\n" + vibe_block + "\n"
        zshrc.write_text(new_content, encoding="utf-8")
    else:
        zshrc.write_text(vibe_block + "\n", encoding="utf-8")

    log.put("[OK] Added 'vibe' function to ~/.zshrc.\n")


class VibeSetupGUI:
    def __init__(self) -> None:
        self.root: tk.Tk = tk.Tk()
        self.root.title("M4 Max Vibe Coding Setup")
        self.root.geometry("720x480")

        self.log_queue: Queue[str] = Queue()
        self.total_steps: int = 7
        self.completed_steps: int = 0
        self.running: bool = False

        self.progress: ttk.Progressbar
        self.status_label: ttk.Label
        self.log_text: tk.Text
        self.start_button: ttk.Button
        self.repair_button: ttk.Button

        self._build_ui()
        self._poll_log_queue()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            frame,
            text="M4 Max Local Vibe Coding Setup",
            font=("SF Pro", 16, "bold"),
        )
        title.pack(anchor="w", pady=(0, 8))

        desc = ttk.Label(
            frame,
            text=(
                "This will set up Homebrew, Ollama, VS Code, "
                "Continue, local models, and a 'vibe' command.\n"
                "You may be prompted for your macOS password "
                "for installations."
            ),
            wraplength=680,
            justify="left",
        )
        desc.pack(anchor="w", pady=(0, 8))

        self.progress = ttk.Progressbar(
            frame,
            orient="horizontal",
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(fill=tk.X, pady=(0, 8))

        self.status_label = ttk.Label(
            frame,
            text="Idle.",
        )
        self.status_label.pack(anchor="w", pady=(0, 8))

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            text_frame,
            wrap="word",
            height=18,
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(
            text_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=(8, 0))

        self.start_button = ttk.Button(
            button_frame,
            text="Start Setup",
            command=self.on_start_clicked,
        )
        self.start_button.pack(side=tk.LEFT)

        self.repair_button = ttk.Button(
            button_frame,
            text="Repair Environment",
            command=self.on_repair_clicked,
        )
        self.repair_button.pack(side=tk.LEFT, padx=(8, 0))

        quit_button = ttk.Button(
            button_frame,
            text="Quit",
            command=self.root.destroy,
        )
        quit_button.pack(side=tk.RIGHT)

    def on_start_clicked(self) -> None:
        if self.running:
            return
        if not is_macos_arm():
            messagebox.showerror(
                "Unsupported system",
                "This script is intended for macOS ARM (M1/M2/M3/M4).",
            )
            return
        self.running = True
        self.completed_steps = 0
        self.progress["value"] = 0
        self.status_label.config(text="Running setup...")
        self.start_button.config(state=tk.DISABLED)
        self._append_log(
            "[INFO] Starting M4 Max vibe coding setup...\n"
        )

        thread = threading.Thread(
            target=self._run_setup,
            daemon=True,
        )
        thread.start()

    def on_repair_clicked(self) -> None:
        if self.running:
            return
        if not is_macos_arm():
            messagebox.showerror(
                "Unsupported system",
                "This script is intended for macOS ARM (M1/M2/M3/M4).",
            )
            return
        self.running = True
        self.completed_steps = 0
        self.progress["value"] = 0
        self.status_label.config(text="Running repair...")
        self.start_button.config(state=tk.DISABLED)
        self.repair_button.config(state=tk.DISABLED)
        self._append_log(
            "[INFO] Starting environment repair (re-running all steps)...\n"
        )

        thread = threading.Thread(
            target=self._run_setup,
            daemon=True,
        )
        thread.start()

    def _run_setup(self) -> None:
        try:
            self._run_step("Installing Homebrew...", install_homebrew)
            self._run_step("Installing Ollama...", install_ollama)
            self._run_step("Installing VS Code...", install_vscode)
            self._run_step(
                "Installing Continue extension...",
                install_continue,
            )
            self._run_step(
                "Pulling Ollama models...",
                pull_ollama_models,
            )
            self._run_step(
                "Configuring Continue...",
                configure_continue,
            )
            self._run_step(
                "Configuring 'vibe' shell function...",
                configure_vibe_alias,
            )
            self.log_queue.put(
                "[DONE] Setup finished. Open a new terminal and run "
                "`vibe` in a project directory.\n"
            )
            self.log_queue.put("__SETUP_DONE__")
        except Exception as exc:
            self.log_queue.put(f"[FATAL] Setup aborted: {exc}\n")
            self.log_queue.put("__SETUP_FAILED__")

    def _run_step(
        self,
        status_text: str,
        func: Callable[[Queue[str]], None],
    ) -> None:
        self.log_queue.put(f"[STEP] {status_text}\n")
        self.log_queue.put(f"--- {status_text}\n")
        func(self.log_queue)
        self.completed_steps += 1
        self._update_progress()

    def _update_progress(self) -> None:
        pct = int(
            (self.completed_steps / max(1, self.total_steps)) * 100
        )
        self.progress["value"] = pct
        self.status_label.config(
            text=(
                f"Progress: {pct}% "
                f"({self.completed_steps}/{self.total_steps} steps)"
            )
        )

    def _append_log(self, text: str) -> None:
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)

    def _poll_log_queue(self) -> None:
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except Empty:
                break
            if msg == "__SETUP_DONE__":
                self.running = False
                self.status_label.config(
                    text="Completed. You can close this window."
                )
                self.start_button.config(state=tk.NORMAL)
                self.repair_button.config(state=tk.NORMAL)
                messagebox.showinfo(
                    "Setup complete",
                    "Vibe coding setup finished.\n\n"
                    "Open a new terminal and run:\n\n"
                    "    vibe\n\n"
                    "inside a project directory.",
                )
            elif msg == "__SETUP_FAILED__":
                self.running = False
                self.status_label.config(
                    text="Setup failed. See log for details."
                )
                self.start_button.config(state=tk.NORMAL)
                self.repair_button.config(state=tk.NORMAL)
            else:
                self._append_log(msg)
        self.root.after(100, self._poll_log_queue)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    gui = VibeSetupGUI()
    gui.run()


if __name__ == "__main__":
    main()
