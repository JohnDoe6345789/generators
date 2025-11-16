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
import shlex
import subprocess
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Dict, List, Sequence

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
    arg_label: str | None = None


def split_user_args(argument_text: str) -> List[str]:
    """Return ``argument_text`` split into CLI arguments via ``shlex``."""

    text = argument_text.strip()
    if not text:
        return []
    return shlex.split(text)


@dataclass(frozen=True)
class ScriptParameter:
    """Represent a positional argument defined by a helper script."""

    label: str
    required: bool


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
                arg_label="Optional pytest arguments",
            )
        )
        commands.append(
            CommandSpec(
                label="Run Generator",
                command=_command_for_script(run_script, "generator"),
                description="Launch the SimplyRetro D8 generator entry point.",
                arg_label="Generator flags (e.g. --output file.scad)",
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
    if not matches:
        # Fall back to scanning all known suffixes so POSIX scripts remain
        # discoverable even when the GUI executes on Windows (where .bat files
        # may not exist).
        matches = [
            path
            for path in SCRIPTS_DIR.iterdir()
            if path.is_file() and path.suffix in {".sh", ".bat", ".cmd"}
        ]
    return sorted(matches, key=lambda path: path.name.lower())


def parse_usage_parameters(usage_line: str) -> List[ScriptParameter]:
    """Extract positional parameters described on a ``Usage:`` line."""

    usage = usage_line.strip()
    if not usage.lower().startswith("usage:"):
        return []
    _, remainder = usage.split(":", 1)
    parts = remainder.strip().split()
    if len(parts) <= 1:
        return []
    tokens = parts[1:]
    parameters: List[ScriptParameter] = []
    for token in tokens:
        stripped = token.strip()
        if not stripped:
            continue
        optional = stripped.startswith("[") and stripped.endswith("]")
        cleaned = stripped.strip("[]<>")
        if not cleaned or cleaned.startswith("-"):
            continue
        label = cleaned.replace("_", " ").title()
        parameters.append(ScriptParameter(label=label, required=not optional))
    return parameters


def _usage_from_source(script: Path) -> str | None:
    """Extract an inline ``Usage:`` line directly from ``script``."""

    try:
        for line in script.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("usage:"):
                return stripped
    except OSError:
        return None
    return None


def _script_usage_output(script: Path) -> str | None:
    """Return the stdout produced by the script's help flag, if any."""

    help_flags = ("--help", "-h")
    for flag in help_flags:
        try:
            completed = subprocess.run(
                _command_for_script(script, flag),
                cwd=str(ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return _usage_from_source(script)
        if completed.returncode == 0 and completed.stdout:
            return completed.stdout
    return _usage_from_source(script)


def script_parameters(script: Path) -> List[ScriptParameter]:
    """Detect positional parameters for ``script`` via its help output."""

    output = _script_usage_output(script)
    if not output:
        return []
    for line in output.splitlines():
        if line.lower().startswith("usage:"):
            return parse_usage_parameters(line)
    return []


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
        self._command_arg_vars: Dict[CommandSpec, tk.StringVar] = {}
        self._parameter_cache: Dict[Path, List[ScriptParameter]] = {}
        self._param_entries: List[tuple[ScriptParameter, tk.StringVar]] = []
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
            card = ttk.Frame(frame)
            card.pack(fill="x", pady=6)
            btn = ttk.Button(
                card,
                text=spec.label,
                command=lambda current=spec: self._run_command_spec(current),
            )
            btn.pack(fill="x")
            desc = ttk.Label(card, text=spec.description, wraplength=320)
            desc.pack(fill="x", pady=(2, 0))
            if spec.arg_label:
                arg_row = ttk.Frame(card)
                arg_row.pack(fill="x", pady=(6, 0))
                label = ttk.Label(arg_row, text=spec.arg_label)
                label.pack(anchor="w")
                var = tk.StringVar()
                entry = ttk.Entry(arg_row, textvariable=var)
                entry.pack(fill="x")
                self._command_arg_vars[spec] = var

    def _run_command_spec(self, spec: CommandSpec) -> None:
        """Run ``spec`` and append any optional user arguments."""

        extra: List[str] = []
        var = self._command_arg_vars.get(spec)
        if var:
            try:
                extra = split_user_args(var.get())
            except ValueError as exc:
                self.console.write(f"Unable to parse arguments: {exc}\n")
                return
        self.runner.run([*spec.command, *extra])

    def _build_script_panel(self, parent: ttk.Frame) -> None:
        """Add the helper script list and run button."""

        frame = ttk.LabelFrame(parent, text="Helper scripts")
        frame.grid(row=0, column=1, sticky="nsew")
        scripts = discover_helper_scripts()
        self.script_var = tk.StringVar(value=[path.name for path in scripts])
        self._script_lookup = {path.name: path for path in scripts}
        self.listbox = tk.Listbox(frame, listvariable=self.script_var, height=8)
        self.listbox.pack(fill="both", expand=True, pady=(0, 8))
        self.listbox.bind("<<ListboxSelect>>", self._on_script_selected)
        self.param_frame = ttk.LabelFrame(frame, text="Parameters")
        self.param_frame.pack(fill="x", pady=(0, 8))
        self._set_param_message("Select a script to view parameters.")
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
        args: List[str] = []
        for param, var in self._param_entries:
            value = var.get().strip()
            if not value and param.required:
                self.console.write(
                    f"Parameter '{param.label}' is required before running.\n"
                )
                return
            if value:
                args.append(value)
        command = _command_for_script(script, *args)
        self.runner.run(command)

    def _set_param_message(self, message: str) -> None:
        """Display ``message`` in the parameter frame and clear entries."""

        for widget in self.param_frame.winfo_children():
            widget.destroy()
        label = ttk.Label(self.param_frame, text=message, wraplength=320)
        label.pack(fill="x", padx=4, pady=4)
        self._param_entries = []

    def _on_script_selected(self, event: tk.Event[tk.Listbox]) -> None:  # type: ignore[name-defined]
        """Update parameter fields when the selection changes."""

        selection = self.listbox.curselection()
        if not selection:
            self._set_param_message("Select a script to view parameters.")
            return
        name = self.listbox.get(selection[0])
        script = self._script_lookup.get(name)
        if not script:
            self._set_param_message("Script missing on disk.")
            return
        params = self._parameter_cache.get(script)
        if params is None:
            params = script_parameters(script)
            self._parameter_cache[script] = params
        if not params:
            self._set_param_message("No parameters detected for this script.")
            return
        self._populate_param_entries(params)

    def _populate_param_entries(self, params: List[ScriptParameter]) -> None:
        """Create entry widgets for ``params`` and store their variables."""

        for widget in self.param_frame.winfo_children():
            widget.destroy()
        entries: List[tuple[ScriptParameter, tk.StringVar]] = []
        for param in params:
            row = ttk.Frame(self.param_frame)
            row.pack(fill="x", padx=4, pady=4)
            label_text = f"{param.label}"
            if param.required:
                label_text += " *"
            label = ttk.Label(row, text=label_text)
            label.pack(anchor="w")
            var = tk.StringVar()
            entry = ttk.Entry(row, textvariable=var)
            entry.pack(fill="x")
            entries.append((param, var))
        self._param_entries = entries

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
