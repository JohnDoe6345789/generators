"""Tkinter control center for running repository workflows.

The module provides a desktop-friendly front end for the existing helper
scripts such as ``setup.sh`` and ``run.sh``.  Users can bootstrap the virtual
environment, execute the test suite, or launch any helper script from the
``scripts/`` directory without recalling each shell command.  The GUI keeps
command discovery and execution logic separate from the Tk widgets so the
behavior can be unit tested.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import List, Sequence

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT_DIR / "scripts"


def is_windows() -> bool:
    """Return ``True`` when executing on Windows."""

    return os.name == "nt"


@dataclass(frozen=True)
class CommandSpec:
    """Describe a launchable command exposed to the GUI."""

    label: str
    command: List[str]
    description: str


def _platform_suffixes() -> Sequence[str]:
    """Return supported script suffixes for the current platform."""

    return (".bat", ".cmd") if is_windows() else (".sh",)


def _preferred_suffix() -> str:
    """Return the primary suffix for top-level helper scripts."""

    return ".bat" if is_windows() else ".sh"


def _command_for_script(script: Path, *args: str) -> List[str]:
    """Build the process invocation for a shell or batch script."""

    if script.suffix in {".sh", ""}:
        return ["bash", str(script), *args]
    if script.suffix in {".bat", ".cmd"}:
        return ["cmd.exe", "/c", str(script), *args]
    raise ValueError(f"Unsupported script type: {script.suffix}")


def _existing_script(base_name: str) -> Path | None:
    """Return the script matching ``base_name`` for this platform if present."""

    candidate = ROOT_DIR / f"{base_name}{_preferred_suffix()}"
    return candidate if candidate.exists() else None


def base_commands() -> List[CommandSpec]:
    """Return the predefined setup and test commands for the GUI."""

    commands: List[CommandSpec] = []
    setup_script = _existing_script("setup")
    run_script = _existing_script("run")
    if setup_script:
        commands.append(
            CommandSpec(
                label="Setup Environment",
                command=_command_for_script(setup_script),
                description="Create the virtual environment and install dependencies.",
            )
        )
    if run_script:
        commands.append(
            CommandSpec(
                label="Run Tests",
                command=_command_for_script(run_script, "tests"),
                description="Execute pytest with src/ on the module search path.",
            )
        )
        commands.append(
            CommandSpec(
                label="Run Generator",
                command=_command_for_script(run_script, "generator"),
                description="Launch the SimplyRetro D8 generator entry point.",
            )
        )
    return commands


def discover_helper_scripts() -> List[Path]:
    """Return helper scripts inside ``scripts/`` that match the platform."""

    if not SCRIPTS_DIR.exists():
        return []
    suffixes = _platform_suffixes()
    matches = [
        path
        for path in SCRIPTS_DIR.iterdir()
        if path.is_file() and path.suffix in suffixes
    ]
    return sorted(matches, key=lambda path: path.name.lower())


class ConsolePane(ttk.Frame):
    """Thread-safe text output widget for command logs."""

    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.text = tk.Text(self, height=20, wrap="word", state="disabled")
        self.scroll = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.queue: queue.Queue[str] = queue.Queue()
        self.after(100, self._poll_queue)

    def write(self, message: str) -> None:
        """Queue ``message`` to be appended to the widget."""

        self.queue.put(message)

    def clear(self) -> None:
        """Remove the current contents."""

        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.configure(state="disabled")

    def _poll_queue(self) -> None:
        """Flush queued log entries into the text widget."""

        while True:
            try:
                chunk = self.queue.get_nowait()
            except queue.Empty:
                break
            self.text.configure(state="normal")
            self.text.insert(tk.END, chunk)
            self.text.see(tk.END)
            self.text.configure(state="disabled")
        self.after(100, self._poll_queue)


class CommandRunner:
    """Run subprocesses without blocking the Tk main loop."""

    def __init__(self, console: ConsolePane, status_var: tk.StringVar):
        self.console = console
        self.status_var = status_var
        self._active_thread: threading.Thread | None = None

    def run(self, command: Sequence[str]) -> None:
        """Execute ``command`` while streaming the output."""

        if self._active_thread and self._active_thread.is_alive():
            self.console.write("Another command is currently running.\n")
            return
        self.console.write(f"$ {' '.join(command)}\n")
        self.status_var.set("Running ...")
        thread = threading.Thread(
            target=self._execute, args=(list(command),), daemon=True
        )
        self._active_thread = thread
        thread.start()

    def _execute(self, command: List[str]) -> None:
        try:
            with subprocess.Popen(
                command,
                cwd=str(ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ) as proc:
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.console.write(line)
                code = proc.wait()
        except OSError as exc:  # pragma: no cover - exercised via UI
            self.console.write(f"Failed to launch command: {exc}\n")
            code = None
        status = "Completed" if code == 0 else "Failed"
        self.status_var.set(status)
        self.console.write(f"Command finished with status: {status}\n")


class WorkflowLauncher(tk.Tk):
    """Main Tk application window for repository workflows."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Generators Control Center")
        self.geometry("900x640")
        self.resizable(True, True)
        self.status_var = tk.StringVar(value="Idle")
        self.console = ConsolePane(self)
        self.runner = CommandRunner(self.console, self.status_var)
        self._build_layout()

    def _build_layout(self) -> None:
        """Construct the full widget hierarchy."""

        main = ttk.Frame(self, padding=20)
        main.grid(row=0, column=0, sticky="nsew")
        self.console.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(16, 0))
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)
        self._build_command_panel(main)
        self._build_script_panel(main)
        self._build_status_bar()

    def _build_command_panel(self, parent: ttk.Frame) -> None:
        """Add the setup/test command buttons."""

        frame = ttk.LabelFrame(parent, text="Core workflows")
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        for spec in base_commands():
            btn = ttk.Button(
                frame,
                text=spec.label,
                command=lambda cmd=spec.command: self.runner.run(cmd),
            )
            btn.pack(fill="x", pady=6)
            desc = ttk.Label(frame, text=spec.description, wraplength=320)
            desc.pack(fill="x")

    def _build_script_panel(self, parent: ttk.Frame) -> None:
        """Add the helper script list and run button."""

        frame = ttk.LabelFrame(parent, text="Helper scripts")
        frame.grid(row=0, column=1, sticky="nsew")
        scripts = discover_helper_scripts()
        self.script_var = tk.StringVar(value=[path.name for path in scripts])
        self._script_lookup = {path.name: path for path in scripts}
        self.listbox = tk.Listbox(frame, listvariable=self.script_var, height=8)
        self.listbox.pack(fill="both", expand=True, pady=(0, 8))
        run_btn = ttk.Button(frame, text="Run selected", command=self._run_selected)
        run_btn.pack(fill="x")

    def _run_selected(self) -> None:
        """Execute the selected helper script if any."""

        selection = self.listbox.curselection()
        if not selection:
            self.console.write("Select a script to run.\n")
            return
        name = self.listbox.get(selection[0])
        script = self._script_lookup.get(name)
        if not script:
            self.console.write("Script missing on disk.\n")
            return
        command = _command_for_script(script)
        self.runner.run(command)

    def _build_status_bar(self) -> None:
        """Display the current run status."""

        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")
        status_label = ttk.Label(bar, textvariable=self.status_var)
        status_label.pack(anchor="w", padx=16, pady=4)


def main() -> int:
    """Entry point for the Tk workflow launcher."""

    app = WorkflowLauncher()
    app.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover - manual execution only
    raise SystemExit(main())
