#!/usr/bin/env python3
"""Interactive GUI for provisioning developer tools via Homebrew."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from shutil import which
from typing import Callable, Iterable, List, Sequence, Tuple

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk


@dataclass(frozen=True)
class AppSpec:
    """Metadata describing a selectable Homebrew package."""

    label: str
    brew_name: str
    kind: str  # "formula" or "cask"


@dataclass(frozen=True)
class InstallEvent:
    """Message passed between the worker thread and the Tk loop."""

    kind: str
    message: str = ""
    current: int = 0
    total: int = 0
    succeeded: int = 0
    failed: int = 0


Reporter = Callable[[InstallEvent], None]


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
    """Return True when the executable is available on PATH."""

    return which(name) is not None


def _run_brew(args: Sequence[str]) -> Tuple[bool, str]:
    """Run `brew` with `args` and return a (success, combined_output) tuple."""

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
    """Return sets of installed formulas and casks."""

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
                     indices: Iterable[int],
                     reporter: Reporter | None = None) -> Tuple[int, int]:
    """Install the selected apps, emitting progress events when requested."""

    formulas, casks = _installed_sets()
    ok_count = 0
    fail_count = 0
    selection = list(indices)
    total = len(selection)

    def _report(event: InstallEvent) -> None:
        if reporter is not None:
            reporter(event)

    if not selection:
        return ok_count, fail_count

    for pos, idx in enumerate(selection, start=1):
        _report(InstallEvent("progress", current=pos - 1, total=total))
        app = apps[idx]
        _report(InstallEvent("log", message=f"Processing {app.label}…"))
        already = (
            app.kind == "formula" and app.brew_name in formulas
            or app.kind == "cask" and app.brew_name in casks
        )
        if already:
            ok_count += 1
            _report(InstallEvent("log",
                                 message=f"{app.label} already installed."))
            continue
        if app.kind == "cask":
            args = ["install", "--cask", app.brew_name]
        else:
            args = ["install", app.brew_name]
        _report(InstallEvent("log",
                             message=f"Running: brew {' '.join(args)}"))
        success, output = _run_brew(args)
        if output.strip():
            for line in output.strip().splitlines():
                _report(InstallEvent("log", message=line))
        if success:
            ok_count += 1
            _report(InstallEvent("log",
                                 message=f"Completed {app.label}."))
        else:
            fail_count += 1
            _report(InstallEvent("log",
                                 message=f"Failed {app.label}."))
    _report(InstallEvent("progress", current=total, total=total))
    return ok_count, fail_count


class InstallerGUI:
    """Encapsulates the Tk UI, background worker, and log display."""

    def __init__(self, apps: Sequence[AppSpec]) -> None:
        self.apps = apps
        self.root = tk.Tk()
        self.root.title("Developer Laptop Setup")
        self.root.configure(bg="#10131a")
        self.root.geometry("760x640")
        self.status_var = tk.StringVar(value="Select apps to install.")
        self.log_queue: "queue.Queue[InstallEvent]" = queue.Queue()
        self.active_thread: threading.Thread | None = None
        self.listbox: tk.Listbox
        self.install_button: tk.Button
        self.progress: ttk.Progressbar
        self.log_widget: scrolledtext.ScrolledText
        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._process_queue)

    def run(self) -> None:
        """Start the Tk main loop."""

        self.root.mainloop()

    def _build_layout(self) -> None:
        """Construct the header, listbox, and logging panes."""

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Install.Horizontal.TProgressbar",
            troughcolor="#1f2533",
            background="#5ad7ff",
            bordercolor="#1f2533",
            lightcolor="#5ad7ff",
            darkcolor="#5ad7ff",
        )

        outer = tk.Frame(self.root, bg="#10131a")
        outer.pack(fill="both", expand=True, padx=20, pady=20)

        header = tk.Frame(outer, bg="#10131a")
        header.pack(fill="x", pady=(0, 16))
        logo_canvas = tk.Canvas(
            header,
            width=72,
            height=72,
            highlightthickness=0,
            bg="#10131a",
        )
        logo_canvas.pack(side="left", padx=(0, 16))
        self._draw_logo(logo_canvas)
        title = tk.Label(
            header,
            text="Developer Foundations",
            font=("Helvetica", 18, "bold"),
            fg="#f6f7fb",
            bg="#10131a",
        )
        title.pack(anchor="w")
        subtitle = tk.Label(
            header,
            text="Select the essentials for macOS development, ops, "
                 "and collaboration.",
            font=("Helvetica", 11),
            fg="#b2b8cc",
            bg="#10131a",
            wraplength=520,
            justify="left",
        )
        subtitle.pack(anchor="w")

        content = tk.Frame(outer, bg="#10131a")
        content.pack(fill="both", expand=True)

        list_frame = tk.LabelFrame(
            content,
            text="Applications",
            fg="#f6f7fb",
            bg="#10131a",
            labelanchor="n",
            padx=10,
            pady=10,
        )
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 12))

        self.listbox = tk.Listbox(
            list_frame,
            selectmode=tk.MULTIPLE,
            height=18,
            activestyle="dotbox",
            relief="flat",
            bg="#161b28",
            fg="#f6f7fb",
            highlightbackground="#1f2533",
        )
        for spec in self.apps:
            self.listbox.insert(tk.END, spec.label)
        sb = tk.Scrollbar(list_frame, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        console_frame = tk.LabelFrame(
            content,
            text="Progress & Logs",
            fg="#f6f7fb",
            bg="#10131a",
            padx=10,
            pady=10,
        )
        console_frame.pack(side="right", fill="both", expand=True)

        self.log_widget = scrolledtext.ScrolledText(
            console_frame,
            height=18,
            bg="#0f121c",
            fg="#d1d6e5",
            insertbackground="#ffffff",
            relief="flat",
            font=("Menlo", 11),
            state="disabled",
            wrap="word",
        )
        self.log_widget.pack(fill="both", expand=True)

        self.progress = ttk.Progressbar(
            console_frame,
            orient="horizontal",
            mode="determinate",
            style="Install.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(12, 4))
        status = tk.Label(
            console_frame,
            textvariable=self.status_var,
            fg="#b2b8cc",
            bg="#10131a",
            anchor="w",
        )
        status.pack(fill="x")

        actions = tk.Frame(outer, bg="#10131a")
        actions.pack(fill="x", pady=(16, 0))
        self.install_button = tk.Button(
            actions,
            text="Install Selected",
            command=self._on_install_clicked,
            bg="#2f6fed",
            fg="#ffffff",
            activebackground="#244fb7",
            relief="flat",
            padx=12,
            pady=8,
        )
        self.install_button.pack(side="left")
        quit_btn = tk.Button(
            actions,
            text="Quit",
            command=self._on_close,
            bg="#272d3f",
            fg="#ffffff",
            relief="flat",
            padx=12,
            pady=8,
        )
        quit_btn.pack(side="right")

    def _draw_logo(self, canvas: tk.Canvas) -> None:
        """Render a simple geometric logo on the header canvas."""

        canvas.create_rectangle(0, 0, 72, 72, fill="#132038", outline="")
        canvas.create_polygon(10, 52, 26, 20, 42, 52, fill="#61dafb", outline="")
        canvas.create_oval(
            40,
            16,
            64,
            40,
            outline="#8e94ff",
            width=4,
        )
        canvas.create_rectangle(38, 46, 64, 58, fill="#26c485", outline="")

    def _on_install_clicked(self) -> None:
        """Start the installation workflow on a worker thread."""

        selection = list(self.listbox.curselection())
        if not selection:
            messagebox.showinfo("No selection", "Select at least one app.")
            return
        if self.active_thread and self.active_thread.is_alive():
            messagebox.showinfo(
                "Busy",
                "An installation is already running. Please wait.",
            )
            return
        self._toggle_inputs(enabled=False)
        self.progress["value"] = 0
        self.progress["maximum"] = max(len(selection), 1)
        names = ", ".join(self.apps[idx].label for idx in selection)
        self.status_var.set("Installing selected applications…")
        self._append_log(f"Starting installation for: {names}")
        self.active_thread = threading.Thread(
            target=self._run_installation,
            args=(selection,),
            daemon=True,
        )
        self.active_thread.start()

    def _run_installation(self, selection: List[int]) -> None:
        """Execute `brew install` calls without blocking Tk."""

        ok, fail = install_selected(
            self.apps,
            selection,
            reporter=self.log_queue.put,
        )
        self.log_queue.put(
            InstallEvent("done", succeeded=ok, failed=fail, total=len(selection))
        )

    def _toggle_inputs(self, *, enabled: bool) -> None:
        """Enable or disable the primary controls."""

        state = tk.NORMAL if enabled else tk.DISABLED
        self.install_button.config(state=state)
        self.listbox.config(state=state)

    def _append_log(self, message: str) -> None:
        """Append a single line to the log view."""

        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", message + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _process_queue(self) -> None:
        """Handle log/progress events originating from the worker."""

        while True:
            try:
                event = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)
        self.root.after(100, self._process_queue)

    def _handle_event(self, event: InstallEvent) -> None:
        """Update UI state for the given queued event."""

        if event.kind == "log":
            self._append_log(event.message)
        elif event.kind == "progress":
            maximum = max(event.total, 1)
            self.progress["maximum"] = maximum
            self.progress["value"] = min(event.current, maximum)
            self.status_var.set(
                f"{event.current}/{event.total} steps processed"
                if event.total
                else "Processing…"
            )
        elif event.kind == "done":
            summary = (
                f"Completed installation. Success: {event.succeeded}, "
                f"failed: {event.failed}."
            )
            self._append_log(summary)
            messagebox.showinfo(
                "Install finished",
                f"Installed: {event.succeeded}\nFailed: {event.failed}",
            )
            self._toggle_inputs(enabled=True)
            self.status_var.set("Select more tools or quit.")
            self.progress["value"] = 0
            self.active_thread = None

    def _on_close(self) -> None:
        """Handle the window close action."""

        if self.active_thread and self.active_thread.is_alive():
            if not messagebox.askyesno(
                "Quit?",
                "An installation is still running. Quit anyway?",
            ):
                return
        self.root.destroy()


def build_ui(apps: Sequence[AppSpec]) -> InstallerGUI:
    """Create the GUI wrapper."""

    return InstallerGUI(apps)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for launching the Tk interface."""

    _ = argv  # Reserved for future CLI extensions.
    ui = build_ui(APP_LIST)
    ui.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
