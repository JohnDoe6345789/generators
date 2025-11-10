#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codegen for a small PyQt6 GUI that opens classic Windows Control Panels.
Creates a new folder ./win-netpanel-launcher with:
  - app/main.py                (PyQt6 GUI, dark/light switch, SVG icon)
  - assets/icon.svg            (window/app icon)
  - scripts/run_gui.bat        (Windows launcher)
  - scripts/run_gui.sh         (Bash launcher)
  - requirements.txt           (PyQt6 + QtSvg)
  - README.md                  (usage)
  - tests/test_smoke.py        (basic unit tests)
Constraints: functions ≤10 lines, 79 cols, mypy-friendly typing.
"""
from __future__ import annotations

from pathlib import Path

# ------------------------------- Utilities -------------------------------- #

ROOT = Path("win-netpanel-launcher")


def _p(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"✓ Wrote {path}")


# ----------------------------- File contents ------------------------------ #

REQ = """PyQt6>=6.6,<7
PyQt6-QtSvg>=6.6,<7
"""

README = """# Win NetPanel Launcher

PyQt6 app with a fancy button (and more) to open classic Windows panels:
- Network Connections (ncpa.cpl)
- Network & Sharing Center
- Internet Options (inetcpl.cpl)
- Windows Firewall (firewall.cpl)
- Advanced Firewall (wf.msc)
- Device Manager (devmgmt.msc)
- Programs & Features (appwiz.cpl)
- System Properties (sysdm.cpl)

## Quick start

```powershell
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python app\\main.py
```

Or use `scripts\\run_gui.bat` (Windows) or `scripts/run_gui.sh` (WSL).
"""

BAT = """@echo off
setlocal
cd /d %~dp0..
if not exist .venv (
  python -m venv .venv
)
call .venv\\Scripts\\activate.bat
pip install -r requirements.txt >nul
python app\\main.py
"""

SH = """#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv || true
source .venv/bin/activate
pip install -r requirements.txt >/dev/null
python3 app/main.py
"""

SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4f46e5"/>
      <stop offset="1" stop-color="#06b6d4"/>
    </linearGradient>
  </defs>
  <rect rx="24" ry="24" width="128" height="128" fill="url(#g)"/>
  <g fill="#fff" opacity="0.95">
    <circle cx="40" cy="40" r="8"/>
    <circle cx="88" cy="64" r="8"/>
    <circle cx="56" cy="88" r="8"/>
    <path d="M46 44 L80 60 M60 80 L82 68" stroke="#fff" stroke-width="6"
          stroke-linecap="round" fill="none"/>
  </g>
</svg>
"""

TEST = '''# -*- coding: utf-8 -*-
"""Smoke tests; import without running the Qt event loop."""
from __future__ import annotations

import types
import unittest

mod: types.ModuleType = __import__("app.main", fromlist=["*"])
MainWindow = getattr(mod, "MainWindow")
open_ncpa = getattr(mod, "open_ncpa")
apply_theme = getattr(mod, "apply_theme")


class TestSmoke(unittest.TestCase):
    def test_funcs_exist(self) -> None:
        self.assertTrue(callable(open_ncpa))
        self.assertTrue(callable(apply_theme))

    def test_window_bits(self) -> None:
        w = MainWindow()
        self.assertIn("Network", w.windowTitle())
        self.assertGreaterEqual(len(w.classic_actions()), 6)


if __name__ == "__main__":
    unittest.main()
'''

MAIN = '''# -*- coding: utf-8 -*-
"""PyQt6 GUI: buttons to open classic panels + dark/light switch."""
from __future__ import annotations

import os
import sys
import ctypes
from pathlib import Path
from typing import Callable, List, Tuple

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QGridLayout,
    QMenuBar,
)

# ------------------------------ Helpers ------------------------------ #


def is_windows() -> bool:
    return os.name == "nt"


def shell_open(target: str, args: str | None = None) -> None:
    if not is_windows():
        raise OSError("Windows only")
    ctypes.windll.shell32.ShellExecuteW(0, "open", target, args, None, 1)


def open_ncpa() -> None:
    shell_open("ncpa.cpl")


def open_named(name: str) -> None:
    shell_open("control.exe", f" /name {name}")


def open_tool(path: str) -> None:
    shell_open(path)


# ------------------------------ Themes -------------------------------- #


def _dark_qss() -> str:
    return (
        "QWidget { background:#0b1221; color:#e6edf3; }"
        " QLabel#title { color:white; font-size:28px; font-weight:700; }"
        " QLabel#subtitle { color:#a3b1c6; font-size:14px; }"
        " QPushButton { border:none; padding:14px 28px; color:white;"
        " font-size:18px; font-weight:600; border-radius:14px;"
        " background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        " stop:0 #4f46e5, stop:1 #06b6d4); }"
        " QPushButton:hover { opacity:0.92; }"
        " QPushButton:pressed { margin-top:2px; }"
    )


def _light_qss() -> str:
    return (
        "QWidget { background:#f7f8fa; color:#111; }"
        " QLabel#title { color:#0b1221; font-size:28px; font-weight:700; }"
        " QLabel#subtitle { color:#445; font-size:14px; }"
        " QPushButton { border:none; padding:14px 28px; color:white;"
        " font-size:18px; font-weight:600; border-radius:14px;"
        " background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        " stop:0 #2563eb, stop:1 #06b6d4); }"
        " QPushButton:hover { opacity:0.96; }"
        " QPushButton:pressed { margin-top:2px; }"
    )


def apply_theme(app: QApplication, dark: bool) -> None:
    app.setStyleSheet(_dark_qss() if dark else _light_qss())


# ------------------------------ UI bits -------------------------------- #


def make_btn(text: str, fn: Callable[[], None]) -> QPushButton:
    b = QPushButton(text)
    b.setMinimumSize(QSize(260, 56))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet("")
    e = QGraphicsDropShadowEffect()
    e.setBlurRadius(24)
    e.setOffset(0, 6)
    b.setGraphicsEffect(e)
    b.clicked.connect(lambda: _safe_call(fn))
    return b


def _error(msg: str) -> None:
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("Error")
    box.setText(msg)
    box.exec()


def _safe_call(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception as exc:
        _error(str(exc))


# ------------------------------ MainWindow ---------------------------- #

PANELS: List[Tuple[str, Callable[[], None]]] = [
    ("Network Connections", open_ncpa),
    ("Sharing Center", lambda: open_named("Microsoft.NetworkAndSharingCenter")),
    ("Internet Options", lambda: shell_open("inetcpl.cpl")),
    ("Windows Firewall", lambda: shell_open("firewall.cpl")),
    ("Advanced Firewall", lambda: open_tool("wf.msc")),
    ("Device Manager", lambda: open_tool("devmgmt.msc")),
    ("Programs & Features", lambda: shell_open("appwiz.cpl")),
    ("System Properties", lambda: shell_open("sysdm.cpl")),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Classic Network Panels")
        self.setMinimumSize(QSize(760, 460))
        self._icon()
        self._build()

    def _icon(self) -> None:
        icon_path = Path(__file__).parent.parent / "assets" / "icon.svg"
        ico = QIcon(str(icon_path))
        self.setWindowIcon(ico)

    def _title_block(self, lay: QVBoxLayout) -> None:
        t = QLabel("Open Classic Network/Control Panels", self)
        t.setObjectName("title")
        s = QLabel("Windows 11 • vintage CPL/MSCs", self)
        s.setObjectName("subtitle")
        lay.addWidget(t)
        lay.addWidget(s)

    def classic_actions(self) -> List[str]:
        return [name for name, _ in PANELS]

    def _build(self) -> None:
        root = QWidget(self)
        v = QVBoxLayout(root)
        v.setContentsMargins(32, 24, 32, 24)
        v.setSpacing(12)
        self._title_block(v)
        grid = QGridLayout()
        for i, (name, fn) in enumerate(PANELS):
            grid.addWidget(make_btn(name, fn), i // 2, i % 2)
        v.addStretch(1)
        v.addLayout(grid)
        v.addStretch(2)
        self._menubar()
        self.setCentralWidget(root)

    def _menubar(self) -> None:
        bar = QMenuBar(self)
        theme = bar.addMenu("Theme")
        dark = theme.addAction("Dark")
        light = theme.addAction("Light")
        app = QApplication.instance()
        assert app is not None
        dark.triggered.connect(lambda: apply_theme(app, True))
        light.triggered.connect(lambda: apply_theme(app, False))
        self.setMenuBar(bar)


# ------------------------------ Entrypoint --------------------------- #


def main() -> int:
    if not is_windows():
        print("This tool requires Windows.")
        return 1
    app = QApplication(sys.argv)
    apply_theme(app, True)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
'''

# ------------------------------- Emission -------------------------------- #


def emit_all() -> None:
    _w(_p("requirements.txt"), REQ)
    _w(_p("README.md"), README)
    _w(_p("scripts", "run_gui.bat"), BAT)
    _w(_p("scripts", "run_gui.sh"), SH)
    _w(_p("assets", "icon.svg"), SVG)
    _w(_p("tests", "test_smoke.py"), TEST)
    _w(_p("app", "main.py"), MAIN)


if __name__ == "__main__":
    emit_all()
    