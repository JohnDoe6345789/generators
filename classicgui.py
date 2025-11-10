#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codegen for a PyQt6 GUI that opens classic Windows Control Panels.
Auto-installs Chocolatey if missing, handles UAC elevation, ensures Python 3.12,
uninstalls older versions, and builds + tests + runs the GUI.
Generates ./win-netpanel-launcher with:
  - app/main.py                (PyQt6 GUI)
  - assets/icon.svg            (window icon)
  - scripts/run_gui.bat/.sh    (launch GUI)
  - scripts/run_setup.ps1/.bat (bootstrap installer)
  - scripts/run_tests.ps1/.bat (unit tests)
  - requirements.txt, README.md, tests/test_smoke.py
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path("win-netpanel-launcher")


def _p(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"✓ Wrote {path}")


# ----------------------------- File contents ------------------------------ #

REQUIREMENTS = """PyQt6>=6.6,<7
"""

README = """# Win NetPanel Launcher

PyQt6 app with a fancy dark/light GUI for opening classic Windows panels.
Includes automatic setup (UAC + Chocolatey + Python 3.12).

```powershell
scripts\run_setup.bat    # Full setup + run GUI (admin required)
```
"""

SVG_ICON = """<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'>
  <defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
    <stop offset='0' stop-color='#4f46e5'/><stop offset='1' stop-color='#06b6d4'/>
  </linearGradient></defs>
  <rect rx='24' ry='24' width='128' height='128' fill='url(#g)'/>
  <g fill='#fff' opacity='0.95'>
    <circle cx='40' cy='40' r='8'/><circle cx='88' cy='64' r='8'/><circle cx='56' cy='88' r='8'/>
    <path d='M46 44 L80 60 M60 80 L82 68' stroke='#fff' stroke-width='6' stroke-linecap='round'/>
  </g>
</svg>
"""

MAIN_SCRIPT = """# -*- coding: utf-8 -*-
from __future__ import annotations
import os, sys, ctypes
from pathlib import Path
from typing import Callable, List, Tuple
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QApplication, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget, QGridLayout, QMenuBar, QGraphicsDropShadowEffect)

def is_windows() -> bool: return os.name == 'nt'

def shell_open(target: str, args: str | None = None) -> None:
    if not is_windows(): raise OSError('Windows only')
    ctypes.windll.shell32.ShellExecuteW(0, 'open', target, args, None, 1)

def open_ncpa() -> None: shell_open('ncpa.cpl')

def open_named(name: str) -> None: shell_open('control.exe', f' /name {name}')

def open_tool(path: str) -> None: shell_open(path)

def _dark_qss() -> str:
    return ('QWidget{background:#0b1221;color:#e6edf3;} QLabel#title{color:white;font-size:28px;font-weight:700;} QLabel#subtitle{color:#a3b1c6;font-size:14px;} QPushButton{border:none;padding:14px 28px;color:white;font-size:18px;font-weight:600;border-radius:14px;background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #4f46e5,stop:1 #06b6d4);} QPushButton:hover{opacity:.92;} QPushButton:pressed{margin-top:2px;}')

def _light_qss() -> str:
    return ('QWidget{background:#f7f8fa;color:#111;} QLabel#title{color:#0b1221;font-size:28px;font-weight:700;} QLabel#subtitle{color:#445;font-size:14px;} QPushButton{border:none;padding:14px 28px;color:white;font-size:18px;font-weight:600;border-radius:14px;background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #2563eb,stop:1 #06b6d4);} QPushButton:hover{opacity:.96;} QPushButton:pressed{margin-top:2px;}')

def apply_theme(app: QApplication, dark: bool) -> None:
    app.setStyleSheet(_dark_qss() if dark else _light_qss())

def make_button(text: str, callback: Callable[[], None]) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumSize(QSize(260, 56))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(24); shadow.setOffset(0, 6)
    button.setGraphicsEffect(shadow)
    button.clicked.connect(lambda: _safe_call(callback))
    return button

def _safe_call(func: Callable[[], None]) -> None:
    try: func()
    except Exception as exc: _show_error(str(exc))

def _show_error(msg: str) -> None:
    box = QMessageBox(); box.setIcon(QMessageBox.Icon.Critical); box.setWindowTitle('Error'); box.setText(msg); box.exec()

PANELS: List[Tuple[str, Callable[[], None]]] = [
    ('Network Connections', open_ncpa),
    ('Sharing Center', lambda: open_named('Microsoft.NetworkAndSharingCenter')),
    ('Internet Options', lambda: shell_open('inetcpl.cpl')),
    ('Windows Firewall', lambda: shell_open('firewall.cpl')),
    ('Advanced Firewall', lambda: open_tool('wf.msc')),
    ('Device Manager', lambda: open_tool('devmgmt.msc')),
    ('Programs & Features', lambda: shell_open('appwiz.cpl')),
    ('System Properties', lambda: shell_open('sysdm.cpl')),
]

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Classic Network Panels')
        self.setMinimumSize(QSize(760, 460))
        self._set_icon(); self._build_ui()
    def _set_icon(self) -> None:
        icon_path = Path(__file__).resolve().parents[1] / 'assets' / 'icon.svg'
        self.setWindowIcon(QIcon(str(icon_path)))
    def _title_block(self, layout: QVBoxLayout) -> None:
        title = QLabel('Open Classic Network/Control Panels', self)
        title.setObjectName('title')
        subtitle = QLabel('Windows 11 • vintage CPL/MSCs', self)
        subtitle.setObjectName('subtitle')
        layout.addWidget(title); layout.addWidget(subtitle)
    def _build_ui(self) -> None:
        root = QWidget(self); layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 24, 32, 24); layout.setSpacing(12)
        self._title_block(layout); grid = QGridLayout()
        for i, (name, fn) in enumerate(PANELS): grid.addWidget(make_button(name, fn), i // 2, i % 2)
        layout.addStretch(1); layout.addLayout(grid); layout.addStretch(2)
        self._add_menubar(); self.setCentralWidget(root)
    def _add_menubar(self) -> None:
        bar = QMenuBar(self); theme_menu = bar.addMenu('Theme')
        dark = theme_menu.addAction('Dark'); light = theme_menu.addAction('Light')
        app = QApplication.instance()
        dark.triggered.connect(lambda: apply_theme(app, True))
        light.triggered.connect(lambda: apply_theme(app, False))
        self.setMenuBar(bar)

def main() -> int:
    if not is_windows(): print('Windows only.'); return 1
    app = QApplication(sys.argv); apply_theme(app, True)
    win = MainWindow(); win.show(); return app.exec()

if __name__ == '__main__': raise SystemExit(main())
"""

TEST_SCRIPT = '''# -*- coding: utf-8 -*-
from __future__ import annotations
import unittest, types
module: types.ModuleType = __import__('app.main', fromlist=['*'])
MainWindow = getattr(module, 'MainWindow')
open_ncpa = getattr(module, 'open_ncpa')
apply_theme = getattr(module, 'apply_theme')
class TestSmoke(unittest.TestCase):
    def test_functions_exist(self):
        self.assertTrue(callable(open_ncpa)); self.assertTrue(callable(apply_theme))
    def test_window_title(self):
        window = MainWindow(); self.assertIn('Network', window.windowTitle())
if __name__ == '__main__': unittest.main()
'''

RUN_SETUP_PS1 = r"""$ErrorActionPreference = 'Stop'
function Is-Admin {
  $p=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  return $p.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}
if (-not (Is-Admin)) {
  $argsList = @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"")
  Start-Process -FilePath 'powershell' -Verb RunAs -ArgumentList $argsList
  exit
}
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
  Set-ExecutionPolicy Bypass -Scope Process -Force
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-Expression ((New-Object Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
}
$env:Path += ';C:\\ProgramData\\chocolatey\\bin'
$pyVers = @('python310','python311','python313','python314')
foreach ($p in $pyVers) { if (Get-Command $p -ErrorAction SilentlyContinue) { choco uninstall $p -y --no-progress 2>$null | Out-Null } }
choco install python312 -y --no-progress
if (Test-Path .venv) { Remove-Item -Recurse -Force .venv }
py -3.12 -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r requirements.txt
python -m unittest -q
python app\main.py
Read-Host 'Press Enter to exit'
"""

RUN_SETUP_BAT = r"""@echo off
setlocal
cd /d %~dp0..
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_setup.ps1"
pause
"""

RUN_TESTS_BAT = r"""@echo off
setlocal
cd /d %~dp0..
if not exist .venv (py -3.12 -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r requirements.txt
python -m unittest -v
pause
"""

RUN_TESTS_PS1 = r"""$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)\..
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r requirements.txt
python -m unittest -v
Read-Host 'Press Enter to exit'
"""

RUN_GUI_BAT = r"""@echo off
setlocal
cd /d %~dp0..
if exist .venv (call .venv\Scripts\activate.bat) else (echo Run setup first & pause & exit /b 1)
python app\main.py
pause
"""

RUN_GUI_SH = """#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || { echo 'Run setup first'; exit 1; }
source .venv/bin/activate
python3 app/main.py
"""

def emit_all() -> None:
    _w(_p('requirements.txt'), REQUIREMENTS)
    _w(_p('README.md'), README)
    _w(_p('assets', 'icon.svg'), SVG_ICON)
    _w(_p('app', 'main.py'), MAIN_SCRIPT)
    _w(_p('tests', 'test_smoke.py'), TEST_SCRIPT)
    _w(_p('scripts', 'run_setup.ps1'), RUN_SETUP_PS1)
    _w(_p('scripts', 'run_setup.bat'), RUN_SETUP_BAT)
    _w(_p('scripts', 'run_tests.ps1'), RUN_TESTS_PS1)
    _w(_p('scripts', 'run_tests.bat'), RUN_TESTS_BAT)
    _w(_p('scripts', 'run_gui.bat'), RUN_GUI_BAT)
    _w(_p('scripts', 'run_gui.sh'), RUN_GUI_SH)


def main() -> None:
    emit_all()


if __name__ == '__main__':
    main()
