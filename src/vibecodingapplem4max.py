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
    * qwen2.5-coder:1.5b
    * qwen2.5-coder:7b
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
import tkinter.simpledialog as simpledialog
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


# List installed Ollama models via the CLI
def list_ollama_models() -> list[dict[str, str]]:
    if not detect_ollama():
        return []
    try:
        proc = subprocess.run(
            ["ollama", "list"],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []

    lines = proc.stdout.splitlines()
    if not lines:
        return []

    models: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        size = "".join(parts[-2:]) if len(parts) >= 2 else ""
        models.append({"name": name, "size": size})
    return models


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

    log.put("[INFO] Pulling qwen2.5-coder:1.5b...\n")
    run_cmd(
        ["ollama", "pull", "qwen2.5-coder:1.5b"],
        log,
        check=False,
    )
    log.put("[INFO] Pulling qwen2.5-coder:7b...\n")
    run_cmd(
        ["ollama", "pull", "qwen2.5-coder:7b"],
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

    models: list[dict[str, Any]] = [
        {
            "title": "QwenCoder2.5 1.5B (local)",
            "provider": "ollama",
            "model": "qwen2.5-coder:1.5b",
            "apiBase": "http://localhost:11434",
        },
        {
            "title": "QwenCoder2.5 7B (local)",
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "apiBase": "http://localhost:11434",
        },
    ]

    mercury_key = os.environ.get("MERCURY_API_KEY")
    if mercury_key:
        models.append(
            {
                "title": "Mercury Coder",
                "provider": "mercury",
                "model": "mercury-coder",
                "apiKey": mercury_key,
            }
        )

    mistral_key = os.environ.get("MISTRAL_API_KEY")
    if mistral_key:
        models.append(
            {
                "title": "Codestral",
                "provider": "mistral",
                "model": "codestral-latest",
                "apiKey": mistral_key,
            }
        )

    base: dict[str, Any] = {
        "models": models,
        "autocompleteModel": "QwenCoder2.5 1.5B (local)",
        "tabAutocompleteModel": "QwenCoder2.5 1.5B (local)",
        "defaultModel": "QwenCoder2.5 7B (local)",
    }

    cfg_data: dict[str, Any]
    if cfg_file.exists():
        try:
            current = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            current = {}
        current["models"] = base["models"]
        current["autocompleteModel"] = base["autocompleteModel"]
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


# Helper for environment status snapshot (non-mutating)
def get_env_status_lines() -> list[str]:
    lines: list[str] = []

    if detect_homebrew():
        lines.append("[OK] Homebrew: installed")
    else:
        lines.append("[MISSING] Homebrew: not installed")

    if detect_ollama():
        lines.append("[OK] Ollama CLI: installed")
        try:
            proc = subprocess.run(
                ["pgrep", "-x", "ollama"],
                text=True,
                capture_output=True,
                check=False,
            )
            if proc.returncode == 0:
                lines.append("[OK] Ollama service: running")
            else:
                lines.append("[WARN] Ollama service: not running")
        except Exception:
            lines.append("[WARN] Ollama service: status unknown (pgrep failed)")
    else:
        lines.append("[MISSING] Ollama CLI: not installed")

    if detect_vscode():
        lines.append("[OK] VS Code: installed")
    else:
        lines.append("[MISSING] VS Code: not installed")

    # Continue extension status
    try:
        tmp_log: Queue[str] = Queue()
        if detect_continue_extension(tmp_log):
            lines.append("[OK] Continue VS Code extension: installed")
        else:
            lines.append("[WARN] Continue VS Code extension: not detected")
    except Exception:
        lines.append(
            "[WARN] Continue VS Code extension: status unknown (check failed)"
        )

    # 'vibe' alias status
    home = Path.home()
    zshrc = home / ".zshrc"
    snippet_start = "# >>> vibe-coding setup >>>"
    snippet_end = "# <<< vibe-coding setup <<<"
    if zshrc.exists():
        try:
            content = zshrc.read_text(encoding="utf-8")
            if snippet_start in content and snippet_end in content:
                lines.append("[OK] 'vibe' shell function: configured in ~/.zshrc")
            else:
                lines.append("[WARN] 'vibe' shell function: not found in ~/.zshrc")
        except Exception:
            lines.append(
                "[WARN] 'vibe' shell function: status unknown (could not read ~/.zshrc)"
            )
    else:
        lines.append("[WARN] 'vibe' shell function: ~/.zshrc file does not exist")

    return lines


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
        self.status_button: ttk.Button
        self.models_button: ttk.Button

        self.status_window: Optional[tk.Toplevel] = None
        self.status_tree: Optional[ttk.Treeview] = None
        self.models_window: Optional[tk.Toplevel] = None
        self.models_tree: Optional[ttk.Treeview] = None
        self.models_status: Optional[ttk.Label] = None

        self._build_ui()
        self._poll_log_queue()

    def _ensure_status_window(self) -> None:
        if (
            self.status_window is not None
            and self.status_window.winfo_exists()
        ):
            if self.status_tree is not None:
                for item in self.status_tree.get_children():
                    self.status_tree.delete(item)
            return

        self.status_window = tk.Toplevel(self.root)
        self.status_window.title("Environment Status")
        self.status_window.geometry("520x260")
        self.status_window.transient(self.root)

        columns = ("component", "status")
        tree = ttk.Treeview(
            self.status_window,
            columns=columns,
            show="headings",
            height=10,
        )
        tree.heading("component", text="Component")
        tree.heading("status", text="Status")
        tree.column("component", width=200, anchor="w")
        tree.column("status", width=300, anchor="w")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(
            self.status_window,
            orient="vertical",
            command=tree.yview,
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)

        self.status_tree = tree

    def _ensure_models_window(self) -> None:
        if (
            self.models_window is not None
            and self.models_window.winfo_exists()
        ):
            if self.models_tree is not None:
                for item in self.models_tree.get_children():
                    self.models_tree.delete(item)
            self._set_models_status("")
            return

        self.models_window = tk.Toplevel(self.root)
        self.models_window.title("Manage Ollama Models")
        self.models_window.geometry("600x320")
        self.models_window.transient(self.root)

        container = ttk.Frame(self.models_window, padding=8)
        container.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "size")
        tree = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            height=10,
        )
        tree.heading("name", text="Model")
        tree.heading("size", text="Size")
        tree.column("name", width=360, anchor="w")
        tree.column("size", width=120, anchor="w")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=tree.yview,
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)

        button_frame = ttk.Frame(self.models_window)
        button_frame.pack(fill=tk.X, pady=(8, 0))

        refresh_btn = ttk.Button(
            button_frame,
            text="Refresh",
            command=self.refresh_models_view,
        )
        refresh_btn.pack(side=tk.LEFT)

        pull_btn = ttk.Button(
            button_frame,
            text="Pull Model...",
            command=lambda: self._run_model_pull(prompt=True),
        )
        pull_btn.pack(side=tk.LEFT, padx=(8, 0))

        delete_btn = ttk.Button(
            button_frame,
            text="Delete Selected",
            command=self._run_model_delete,
        )
        delete_btn.pack(side=tk.LEFT, padx=(8, 0))

        close_btn = ttk.Button(
            button_frame,
            text="Close",
            command=self.models_window.destroy,
        )
        close_btn.pack(side=tk.RIGHT)

        status = ttk.Label(
            self.models_window,
            text="",
            anchor="w",
        )
        status.pack(fill=tk.X, pady=(4, 0))

        self.models_tree = tree
        self.models_status = status

    def refresh_models_view(self) -> None:
        if self.models_tree is None:
            return

        for item in self.models_tree.get_children():
            self.models_tree.delete(item)

        models = list_ollama_models()
        if not models:
            self.models_tree.insert(
                "",
                tk.END,
                values=("No models found", ""),
            )
            self._set_models_status("No models reported by Ollama.")
            return

        for m in models:
            self.models_tree.insert(
                "",
                tk.END,
                values=(m.get("name", ""), m.get("size", "")),
            )
        self._set_models_status(f"Found {len(models)} model(s).")

    def on_models_clicked(self) -> None:
        if not detect_ollama():
            messagebox.showwarning(
                "Ollama not found",
                (
                    "Ollama CLI is not installed or not on PATH.\n"
                    "Install Ollama first, then try again."
                ),
            )
            return
        self._ensure_models_window()
        self.refresh_models_view()

    def _set_models_status(self, text: str) -> None:
        if self.models_status is not None:
            self.models_status.config(text=text)

    def _run_model_pull(self, prompt: bool = False) -> None:
        def worker(name: str) -> None:
            try:
                proc = subprocess.run(
                    ["ollama", "pull", name],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if proc.returncode == 0:
                    msg = f"Pulled model '{name}'."
                else:
                    err = proc.stderr.strip() or proc.stdout.strip()
                    msg = f"Failed to pull '{name}': {err}" if err else (
                        f"Failed to pull '{name}'."
                    )
            except Exception as exc:  # pragma: no cover - OS errors
                msg = f"Error pulling '{name}': {exc}"

            def done() -> None:
                self._set_models_status(msg)
                self.refresh_models_view()
                self._append_log(msg + "\n")

            self.root.after(0, done)

        if prompt:
            name = simpledialog.askstring(
                "Pull Model",
                (
                    "Enter Ollama model name, for example:\n"
                    "qwen2.5-coder:1.5b or qwen2.5-coder:7b"
                ),
                parent=self.models_window,
            )
            if not name:
                return
        else:
            name = "qwen2.5-coder:1.5b"

        self._set_models_status(f"Pulling '{name}'...")
        threading.Thread(target=worker, args=(name,), daemon=True).start()

    def _run_model_delete(self) -> None:
        if self.models_tree is None:
            return
        selection = self.models_tree.selection()
        if not selection:
            messagebox.showinfo(
                "No selection",
                "Select a model to delete first.",
            )
            return
        item_id = selection[0]
        values = self.models_tree.item(item_id, "values")
        if not values:
            return
        name = values[0]
        if not name or name == "No models found":
            return

        confirm = messagebox.askyesno(
            "Delete model",
            f"Are you sure you want to delete '{name}'?",
            parent=self.models_window,
        )
        if not confirm:
            return

        def worker() -> None:
            try:
                proc = subprocess.run(
                    ["ollama", "rm", name],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if proc.returncode == 0:
                    msg = f"Deleted model '{name}'."
                else:
                    err = proc.stderr.strip() or proc.stdout.strip()
                    msg = f"Failed to delete '{name}': {err}" if err else (
                        f"Failed to delete '{name}'."
                    )
            except Exception as exc:  # pragma: no cover
                msg = f"Error deleting '{name}': {exc}"

            def done() -> None:
                self._set_models_status(msg)
                self.refresh_models_view()
                self._append_log(msg + "\n")

            self.root.after(0, done)

        self._set_models_status(f"Deleting '{name}'...")
        threading.Thread(target=worker, daemon=True).start()

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

        self.status_button = ttk.Button(
            button_frame,
            text="Check Status",
            command=self.on_status_clicked,
        )
        self.status_button.pack(side=tk.LEFT, padx=(8, 0))

        self.models_button = ttk.Button(
            button_frame,
            text="Manage Models",
            command=self.on_models_clicked,
        )
        self.models_button.pack(side=tk.LEFT, padx=(8, 0))

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

    def on_status_clicked(self) -> None:
        lines = get_env_status_lines()
        self._ensure_status_window()
        if self.status_tree is None:
            return

        for item in self.status_tree.get_children():
            self.status_tree.delete(item)

        for line in lines:
            try:
                _, rest = line.split("] ", 1)
            except ValueError:
                component = ""
                status = line
            else:
                if ": " in rest:
                    component, status = rest.split(": ", 1)
                else:
                    component = rest
                    status = ""
            self.status_tree.insert("", tk.END, values=(component, status))

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
