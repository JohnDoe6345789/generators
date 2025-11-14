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
from tkinter import messagebox, ttk


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
    operation: str = ""


Reporter = Callable[[InstallEvent], None]

_PROGRESS_HINTS: Tuple[Tuple[str, float], ...] = (
    ("downloading", 0.3),
    ("fetching", 0.3),
    ("pouring", 0.55),
    ("installing", 0.7),
    ("linking", 0.85),
    ("cleanup", 0.92),
    ("finishing", 0.95),
)


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


def _stream_brew(args: Sequence[str],
                 line_callback: Callable[[str], None] | None = None) -> bool:
    """Run brew while streaming output to ``line_callback``."""

    if not _have_cmd("brew"):
        if line_callback:
            line_callback("Homebrew is not available on PATH.")
        return False
    cmd = ["brew", *args]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:  # pragma: no cover - system dependent
        if line_callback:
            line_callback(f"Failed to run brew: {exc}")
        return False
    assert proc.stdout is not None
    for line in proc.stdout:
        if line_callback and line:
            line_callback(line.rstrip())
    proc.wait()
    return proc.returncode == 0


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


def _detail_progress(current: float, line: str) -> float:
    """Heuristically advance in-progress value based on brew output."""

    if not line:
        return current
    lowered = line.lower()
    for token, threshold in _PROGRESS_HINTS:
        if token in lowered:
            return max(current, threshold)
    return min(current + 0.02, 0.9)


def _process_selected(apps: Sequence[AppSpec],
                      indices: Iterable[int],
                      *,
                      action: str,
                      reporter: Reporter | None = None) -> Tuple[int, int]:
    """Execute install/uninstall behavior for the selected apps."""

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
        _report(
            InstallEvent(
                "progress",
                current=pos - 1,
                total=total,
                operation=action,
            )
        )
        app = apps[idx]
        _report(
            InstallEvent(
                "log",
                message=f"{action.title()} {app.label}…",
                operation=action,
            )
        )
        installed = (
            app.kind == "formula" and app.brew_name in formulas
            or app.kind == "cask" and app.brew_name in casks
        )
        target_set = formulas if app.kind == "formula" else casks
        base_progress = pos - 1
        if action == "install" and installed:
            ok_count += 1
            _report(
                InstallEvent(
                    "log",
                    message=f"{app.label} already installed.",
                    operation=action,
                )
            )
            _report(
                InstallEvent(
                    "progress",
                    current=pos,
                    total=total,
                    operation=action,
                )
            )
            continue
        if action == "uninstall" and not installed:
            _report(
                InstallEvent(
                    "log",
                    message=f"{app.label} not installed; skipping.",
                    operation=action,
                )
            )
            _report(
                InstallEvent(
                    "progress",
                    current=pos,
                    total=total,
                    operation=action,
                )
            )
            continue
        if app.kind == "cask":
            args = [action, "--cask", app.brew_name]
        else:
            args = [action, app.brew_name]
        verb = "brew " + " ".join(args)
        _report(
            InstallEvent(
                "log",
                message=f"Running: {verb}",
                operation=action,
            )
        )
        detail = 0.05

        def _line_callback(line: str) -> None:
            nonlocal detail
            _report(
                InstallEvent(
                    "log",
                    message=line,
                    operation=action,
                )
            )
            detail = _detail_progress(detail, line)
            _report(
                InstallEvent(
                    "progress_detail",
                    current=min(base_progress + detail, pos),
                    total=total,
                    operation=action,
                )
            )

        success = _stream_brew(args, line_callback=_line_callback)
        if success:
            ok_count += 1
            if action == "install":
                target_set.add(app.brew_name)
            else:
                target_set.discard(app.brew_name)
            _report(
                InstallEvent(
                    "log",
                    message=f"{action.title()} complete for {app.label}.",
                    operation=action,
                )
            )
        else:
            fail_count += 1
            _report(
                InstallEvent(
                    "log",
                    message=f"{action.title()} failed for {app.label}.",
                    operation=action,
                )
            )
        _report(
            InstallEvent(
                "progress",
                current=pos,
                total=total,
                operation=action,
            )
        )
    _report(
        InstallEvent(
            "progress",
            current=total,
            total=total,
            operation=action,
        )
    )
    return ok_count, fail_count


def install_selected(apps: Sequence[AppSpec],
                     indices: Iterable[int],
                     reporter: Reporter | None = None) -> Tuple[int, int]:
    """Install the selected apps with progress reporting."""

    return _process_selected(
        apps,
        indices,
        action="install",
        reporter=reporter,
    )


def uninstall_selected(apps: Sequence[AppSpec],
                       indices: Iterable[int],
                       reporter: Reporter | None = None) -> Tuple[int, int]:
    """Uninstall the selected apps with progress reporting."""

    return _process_selected(
        apps,
        indices,
        action="uninstall",
        reporter=reporter,
    )


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
        self.current_action: str | None = None
        self.listbox: tk.Listbox
        self.install_button: ttk.Button
        self.uninstall_button: ttk.Button
        self.progress: ttk.Progressbar
        self.log_widget: tk.Text
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
        style.configure(
            "Primary.TButton",
            background="#2f6fed",
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=1,
            focuscolor="#5ad7ff",
            padding=8,
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#244fb7"), ("disabled", "#3f4f7b")],
            foreground=[("disabled", "#b2b8cc")],
        )
        style.configure(
            "Secondary.TButton",
            background="#272d3f",
            foreground="#ffffff",
            borderwidth=0,
            padding=8,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#1d2333"), ("disabled", "#333b52")],
            foreground=[("disabled", "#9aa1ba")],
        )
        style.configure(
            "Danger.TButton",
            background="#c23b3b",
            foreground="#ffffff",
            borderwidth=0,
            padding=8,
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#992f2f"), ("disabled", "#6a3939")],
            foreground=[("disabled", "#d8a0a0")],
        )
        style.configure(
            "Dark.Vertical.TScrollbar",
            troughcolor="#161b28",
            background="#2b3248",
            bordercolor="#161b28",
            lightcolor="#2b3248",
            darkcolor="#2b3248",
            arrowcolor="#b2b8cc",
            gripcount=0,
            relief="flat",
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#4d5674"), ("pressed", "#5ad7ff")],
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
        sb = ttk.Scrollbar(
            list_frame,
            command=self.listbox.yview,
            style="Dark.Vertical.TScrollbar",
        )
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

        log_container = tk.Frame(console_frame, bg="#10131a")
        log_container.pack(fill="both", expand=True)
        self.log_widget = tk.Text(
            log_container,
            height=18,
            bg="#0f121c",
            fg="#d1d6e5",
            insertbackground="#ffffff",
            relief="flat",
            font=("Menlo", 11),
            state="disabled",
            wrap="word",
        )
        log_sb = ttk.Scrollbar(
            log_container,
            command=self.log_widget.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self.log_widget.configure(yscrollcommand=log_sb.set)
        self.log_widget.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

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
        self.install_button = ttk.Button(
            actions,
            text="Install Selected",
            command=lambda: self._start_action("install"),
            style="Primary.TButton",
        )
        self.install_button.pack(side="left")
        self.uninstall_button = ttk.Button(
            actions,
            text="Uninstall Selected",
            command=lambda: self._start_action("uninstall"),
            style="Danger.TButton",
        )
        self.uninstall_button.pack(side="left", padx=(12, 0))
        quit_btn = ttk.Button(
            actions,
            text="Quit",
            command=self._on_close,
            style="Secondary.TButton",
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

    def _start_action(self, action: str) -> None:
        """Start install/uninstall workflow on a worker thread."""

        selection = list(self.listbox.curselection())
        if not selection:
            messagebox.showinfo("No selection", "Select at least one app.")
            return
        if self.active_thread and self.active_thread.is_alive():
            messagebox.showinfo(
                "Busy",
                "An operation is already running. Please wait.",
            )
            return
        self.current_action = action
        self._toggle_inputs(enabled=False)
        self.progress["value"] = 0
        self.progress["maximum"] = max(len(selection), 1)
        names = ", ".join(self.apps[idx].label for idx in selection)
        verb = "Installing" if action == "install" else "Uninstalling"
        self.status_var.set(f"{verb} selected applications…")
        self._append_log(f"{verb} the following: {names}")
        self.active_thread = threading.Thread(
            target=self._run_action,
            args=(selection, action),
            daemon=True,
        )
        self.active_thread.start()

    def _run_action(self, selection: List[int], action: str) -> None:
        """Execute the requested brew action without blocking Tk."""

        handler = install_selected if action == "install" else uninstall_selected
        ok, fail = handler(
            self.apps,
            selection,
            reporter=self.log_queue.put,
        )
        self.log_queue.put(
            InstallEvent(
                "done",
                succeeded=ok,
                failed=fail,
                total=len(selection),
                operation=action,
            )
        )

    def _toggle_inputs(self, *, enabled: bool) -> None:
        """Enable or disable the primary controls."""

        list_state = tk.NORMAL if enabled else tk.DISABLED
        btn_state = "normal" if enabled else "disabled"
        self.install_button.configure(state=btn_state)
        self.uninstall_button.configure(state=btn_state)
        self.listbox.config(state=list_state)

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
            label = event.operation.title() if event.operation else "Processing"
            if event.total:
                self.status_var.set(
                    f"{label}: {event.current}/{event.total} steps completed"
                )
            else:
                self.status_var.set(f"{label}…")
        elif event.kind == "progress_detail":
            maximum = max(event.total, 1)
            self.progress["maximum"] = maximum
            self.progress["value"] = min(event.current, maximum)
            label = event.operation.title() if event.operation else "Processing"
            if event.total:
                self.status_var.set(
                    f"{label}: {event.current:.1f}/{event.total} steps in progress"
                )
            else:
                self.status_var.set(f"{label}…")
        elif event.kind == "done":
            action_label = {
                "install": "Installation",
                "uninstall": "Uninstallation",
            }.get(event.operation, "Operation")
            summary = (
                f"{action_label} finished. Success: {event.succeeded}, "
                f"failed: {event.failed}."
            )
            self._append_log(summary)
            messagebox.showinfo(
                f"{action_label} complete",
                f"Completed: {event.succeeded}\nFailed: {event.failed}",
            )
            self._toggle_inputs(enabled=True)
            self.status_var.set("Select more tools or quit.")
            self.progress["value"] = 0
            self.active_thread = None
            self.current_action = None

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
