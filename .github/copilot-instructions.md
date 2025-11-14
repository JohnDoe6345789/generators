# Copilot Instructions for generators

## Project Overview

This repository contains **code generator scripts** that scaffold complete project structures for specific domains. Each generator is a standalone Python module that creates files from embedded triple-quoted string templates, avoiding external dependencies.

### Key Generators
- **`bspconvert.py`**: Converts Half-Life 2 BSP geometry to STL mesh format with structured logging
- **`classicgui.py`**: Generates Windows PyQt6 GUI project for opening classic Control Panels
- **`vibecodingapplem4max.py`**: macOS setup wizard (Tkinter GUI) for Ollama + VS Code + Continue.dev integration
- **`compresscodegen.py`**: Generates Qt6 QML compression app with plugin architecture
- **`mac_app_installer.py`**: Tkinter app for installing Homebrew packages on macOS
- **`bootstrapmacsetup.sh`**: Bash bootstrap script that ensures Python+Tkinter before running installer

## Architecture Patterns

### Generator Structure
Each generator follows this pattern:
1. **Constants section**: Define file paths using `_p(*parts)` helper for relative path construction
2. **Template strings**: Store complete file contents (code, config, docs) as module-level triple-quoted strings
3. **Write helper**: Use `_w(path, text)` to create directories and write files with confirmation
4. **Main generation**: Call write operations to scaffold the full project

**Example** (`classicgui.py`):
```python
ROOT = Path("win-netpanel-launcher")
def _p(*parts: str) -> Path:
    return ROOT.joinpath(*parts)
def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"✓ Wrote {path}")

REQUIREMENTS = """PyQt6>=6.6,<7"""
MAIN_SCRIPT = """...full Python code here..."""
```

### Data Classes and Structured Parsing
Use `@dataclass` for structured data (e.g., `BSPHeader`, `Face`, `LumpInfo` in `bspconvert.py`). This clarifies binary parsing intent and makes fields self-documenting.

### GUI-First Approach
**Prefer interactive GUIs over pure CLI tools.** Use:
- **Qt6 QML/PyQt6** (preferred): Rich, modern UIs with QML for complex layouts (see `compresscodegen.py` for plugin architecture example)
- **Tkinter** (minimum): Lightweight fallback for macOS/Windows when Qt6 isn't available; excellent for setup wizards (see `vibecodingapplem4max.py`, `mac_app_installer.py`)
- **Progress UI**: Embed progress bars in GUI windows, not just stderr text bars

### Subprocess & System Integration
- **Logging**: Use Python's `logging` module with INFO/DEBUG levels; enable debug with `--debug` flag
- **Subprocess handling**: Capture and log stdout/stderr; use `check=True` carefully to avoid hiding errors
- **Privilege elevation**: On macOS/Windows, use system mechanisms (AppleScript for macOS, UAC for Windows)
- **Thread-safe logging**: Use `threading.Queue` to pipe subprocess output to GUI without blocking UI

## Code Style & Conventions

Follow `STYLE.md` requirements:
- **Line length**: Keep ≤79 characters
- **Functions**: Limit to ~10 lines when practical; single responsibility
- **Docstrings**: Every module and function must have a docstring describing behavior, inputs, outputs
- **Naming**: Descriptive variable/function/class names; private helpers use leading underscore (e.g., `_w`, `_p`, `_print_progress`)

### Logging Pattern
```python
import logging
logger = logging.getLogger(__name__)
logger.info("High-level step")
logger.debug("Detailed diagnostic info")
```

### GUI Tool Pattern (Tkinter/PyQt6)

**Tkinter** (lightweight, macOS-bundled):
- Use `threading.Queue` for thread-safe logging from background tasks
- Implement `_poll_log_queue()` to update UI with log messages in real-time
- Show `ttk.Progressbar` for long operations; update status labels
- Gracefully handle exceptions with `messagebox` error dialogs
- Example: `vibecodingapplem4max.py` installs Ollama/VS Code with live logs

**PyQt6** (modern, feature-rich):
- Use QML for layout when possible; `PyQt6.QtWidgets` for traditional designs
- Implement `QThread` workers for background tasks
- Emit `pyqtSignal` to update progress and logs from worker threads
- Show `QProgressBar` with percentage completion
- Apply stylesheets (QSS) for dark/light themes
- Example: `classicgui.py` uses custom QSS for modern dark theme

## Project Layout

Maintain **minimal directory structure** unless justified:
```
generators/
├── {generator}.py           # Standalone generator script
├── {generator}_patch.diff   # (Optional) patches if regenerated
├── bootstrap{platform}.sh   # Bootstrap scripts for setup
├── STYLE.md                 # Coding conventions (source of truth)
├── AGENTS.md                # Agent-specific instructions (this repo)
├── README.md                # Project overview
└── LICENSE                  # License info
```

**Do not create** arbitrary new top-level directories; generators scaffold projects in output folders (e.g., `win-netpanel-launcher/`, `gpu_compress_project/`).

## Integration Points & External Dependencies

### System Commands
- **Homebrew** (`mac_app_installer.py`): Check with `which()` before running; gracefully degrade if missing
- **Bash** (`bootstrapmacsetup.sh`): Use `set -euo pipefail` for safety; source shells carefully
- **AppleScript** (`vibecodingapplem4max.py`): Use `osascript` for privilege elevation on macOS
- **PowerShell** (`classicgui.py`): Handle execution policies; support `.bat` fallbacks for compatibility

### Python Packages
- **PyQt6**: Use for GUI apps; ensure imported before execution
- **Tkinter**: Bundled with Python; verify during bootstrap (often requires separate `python-tk` package via Homebrew)
- **Standard library**: Prefer `subprocess`, `pathlib`, `logging`, `dataclasses` over third-party equivalents

## Testing & Verification

### Running Generators
Generators are **executable scripts**; typically run as:
```bash
python3 {generator}.py
```

Most generators **open interactive GUIs** (preferred) rather than running headless CLI. Examples:
- `classicgui.py` → PyQt6 GUI scaffolds Windows panel launcher
- `vibecodingapplem4max.py` → Tkinter GUI installs macOS dev environment
- `compresscodegen.py` → Tkinter GUI lets user pick output folder
- `mac_app_installer.py` → Tkinter GUI for Homebrew package installation

Pure CLI generators (file geometry conversion) still log progress to stderr.

### Test Pattern
When generators scaffold test files, use unit tests with `unittest`. Record test output in a dedicated Markdown file if sharing results (see `STYLE.md`).

**Example test** (generated by `classicgui.py`):
```python
import unittest
class TestSmoke(unittest.TestCase):
    def test_functions_exist(self):
        self.assertTrue(callable(open_ncpa))
```

## Key Developer Workflows

### Adding a New Generator
1. Create `{name}.py` with module docstring describing the scaffolded project
2. **Plan for a GUI**: Use PyQt6 QML if possible; Tkinter as minimum fallback
3. Define `ROOT = Path("{output_project_name}")`
4. Define helper functions `_p()` and `_w()` 
5. Write template constants as triple-quoted strings (for each file)
6. Implement entry point that calls `_w()` for each generated file
7. For GUI generators: use `threading.Queue` + `_poll_log_queue()` for live progress
8. Keep synchronized with this structure if the file will be regenerated from a bootstrap

### Modifying Existing Generators
- **Keep templates in strings**: Don't externalize; maintain regenerability from single file
- **Update docstring**: If behavior changes, update module docstring to reflect new features
- **Test output**: Verify generated files are syntactically correct and complete
- **Preserve `_p()` and `_w()` helpers**: These ensure consistent file writing and directory creation

### Bootstrap/Regeneration Workflow
Some generators may be regenerated from a single Python bootstrap file. If modifying, ensure:
- Triple-quoted strings remain as the source of truth (templates inside the .py file)
- Checked-in scaffolded projects remain in sync via patches (see `generators_patch.diff`)
- Any `.diff` file documents manual changes made after scaffold generation

## Common Pitfalls to Avoid

1. **Line length violations**: Generators produce code; ensure generated templates respect 79-char limit where applicable
2. **Hardcoded absolute paths**: Use `Path.joinpath()` and relative paths; avoid system-specific assumptions
3. **Unhandled subprocess failures**: Always capture and log stderr; use `check=True` judiciously
4. **Missing Tkinter**: macOS users often hit import errors; `bootstrapmacsetup.sh` shows how to ensure it
5. **Platform-specific code without guards**: Use `os.name`, `platform.system()`, `shutil.which()` to detect availability

## Documentation References

- **Coding Style**: See `STYLE.md` for line length, docstrings, testing, and minimal directory structure
- **Agent Instructions**: This file and `AGENTS.md` define repo conventions
- **Generator Examples**: Read `classicgui.py` and `vibecodingapplem4max.py` for typical patterns
