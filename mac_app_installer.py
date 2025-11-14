#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from shutil import which
from typing import Iterable, List, Sequence, Tuple

import tkinter as tk
from tkinter import messagebox


@dataclass(frozen=True)
class AppSpec:
    label: str
    brew_name: str
    kind: str  # "formula" or "cask"


APP_LIST: List[AppSpec] = [
    AppSpec("VLC", "vlc", "cask"),
    AppSpec("Firefox", "firefox", "cask"),
    AppSpec("Google Chrome", "google-chrome", "cask"),
    AppSpec("Rectangle", "rectangle", "cask"),
    AppSpec("Visual Studio Code", "visual-studio-code", "cask"),
    AppSpec("iTerm2", "iterm2", "cask"),
    AppSpec("Docker Desktop", "docker", "cask"),
    AppSpec("Slack", "slack", "cask"),
    AppSpec("Zoom", "zoom", "cask"),
    AppSpec("Postman", "postman", "cask"),
    AppSpec("Notion", "notion", "cask"),
    AppSpec("htop", "htop", "formula"),
    AppSpec("git", "git", "formula"),
    AppSpec("Zsh Syntax Highlighting", "zsh-syntax-highlighting", "formula"),
    AppSpec("AWS CLI", "awscli", "formula"),
    AppSpec("Node.js", "node", "formula"),
    AppSpec("Watchman", "watchman", "formula"),
]


def _have_cmd(name: str) -> bool:
    return which(name) is not None


def _run_brew(args: Sequence[str]) -> Tuple[bool, str]:
    if not _have_cmd("brew"):
        return False, "Homebrew is not installed or not in PATH."
    cmd = ["brew", *args]
    try:
        out = subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:  # pragma: no cover - system dependent
        return False, f"Failed to run brew: {exc}"
    success = out.returncode == 0
    output = out.stdout + out.stderr
    return success, output


def _installed_sets() -> Tuple[set, set]:
    ok_f, out_f = _run_brew(["list", "--formula"])
    ok_c, out_c = _run_brew(["list", "--cask"])
    formulas: set = set()
    casks: set = set()
    if ok_f:
        formulas = set(line.strip() for line in out_f.splitlines() if line.strip())
    if ok_c:
        casks = set(line.strip() for line in out_c.splitlines() if line.strip())
    return formulas, casks


def install_selected(apps: Sequence[AppSpec],
                     indices: Iterable[int]) -> Tuple[int, int]:
    formulas, casks = _installed_sets()
    ok_count = 0
    fail_count = 0
    for idx in indices:
        app = apps[idx]
        if app.kind == "formula" and app.brew_name in formulas:
            ok_count += 1
            continue
        if app.kind == "cask" and app.brew_name in casks:
            ok_count += 1
            continue
        if app.kind == "cask":
            args = ["install", "--cask", app.brew_name]
        else:
            args = ["install", app.brew_name]
        success, _ = _run_brew(args)
        if success:
            ok_count += 1
        else:
            fail_count += 1
    return ok_count, fail_count


def on_install_clicked(lb: tk.Listbox) -> None:
    sel = list(lb.curselection())
    if not sel:
        messagebox.showinfo("No selection", "Select at least one app.")
        return
    ok, fail = install_selected(APP_LIST, sel)
    messagebox.showinfo("Done", f"Installed: {ok}\nFailed: {fail}")


def build_ui() -> tk.Tk:
    root = tk.Tk()
    root.title("Mac App Installer")
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10, pady=10)
    lb = tk.Listbox(frame, selectmode=tk.MULTIPLE, height=15)
    sb = tk.Scrollbar(frame, command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    for spec in APP_LIST:
        lb.insert(tk.END, spec.label)
    btn = tk.Button(
        root,
        text="Install Selected",
        command=lambda: on_install_clicked(lb),
    )
    btn.pack(fill="x", padx=10, pady=10)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv  # unused, for future extension
    ui = build_ui()
    ui.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
