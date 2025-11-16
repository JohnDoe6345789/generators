# generators

Utility scripts and quick-start tooling for experiments that pair GUI helpers
with automation-friendly generators. The repository now follows a simple
directory structure so each component is easy to discover:

```
docs/        – Style guidance and collected test results.
scripts/     – Shell helpers for bootstrapping development environments.
src/         – Python-based generators and supporting modules.
              ├─ converters/ – Format conversion helpers.
              ├─ generators/ – Code generators and supporting logic.
              ├─ gui/        – Desktop helper apps.
              ├─ installers/ – Packaging and installer utilities.
              └─ network/    – Samba discovery tools and GUIs.
assets/      – Shared artwork and other binary resources.
patches/     – Historical diffs or scaffolding assets.
tests/       – Unit tests that exercise the Python generators.
```

## Quick setup and helper scripts

Use the provided shell or batch scripts to get started without hunting for the
right commands:

```bash
./setup.sh          # Create .venv and install requirements on macOS/Linux
./run.sh tests      # Run pytest with src/ on PYTHONPATH
./run.sh generator  # Execute the SimplyRetro D8 generator
./run.sh launcher   # Open the Tk workflow control center
PYTHONPATH=src python -m gui.workflow_launcher  # Launch the Tk control center
```

On Windows, run the matching `.bat` files (`setup.bat` / `run.bat`). All helper
scripts automatically activate the virtual environment, upgrade `pip`, and keep
`src/` on the module search path so the generators can be launched directly.

### Tk workflow launcher

Run `./run.sh launcher` (or `run.bat launcher` on Windows) to open the
Tkinter-based control center without juggling `PYTHONPATH`. You can still invoke
it directly with `python -m gui.workflow_launcher` if desired. The launcher
exposes buttons for setting up the environment, running the pytest suite,
launching the SimplyRetro generator, and invoking any helper script listed in
the `scripts/` directory. Command output is streamed into the GUI so you can
monitor progress without leaving the window. When a script ships with a
`Usage:` section, the launcher parses its positional parameters and renders
matching input fields so you can pass different arguments without touching the
terminal.

> **Homebrew tip:** Recent macOS installs sometimes end up with both `/usr/bin`
> and Homebrew versions of Python. Use `scripts/set_default_python.sh` to append
> an alias block to your shell profile so the helper scripts consistently find
> `/opt/homebrew/bin/python3`.

## SimplyRetro D8 OpenSCAD generator

The `src/generators/simplyretro_d8_generator.py` module reads
`assets/simplyRetro D8.step`, tessellates the mesh via a pure-Python STEP
backend, and emits OpenSCAD code using the shared framework that powers the
jigsaw and teapot generators. The backend translates the relevant OpenCascade
(OCCT) shell-walking routines into Python and leans on
[`steputils`](https://pypi.org/project/steputils/) for the ISO-10303 parser so
no compiled dependencies are required at runtime:

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m generators.simplyretro_d8_generator --output simplyretro_d8.scad
```

Because the tessellator now lives entirely inside this repository it is always
available in virtual environments created via ``setup.sh`` or ``setup.bat`` and
the OpenSCAD framework no longer needs to guard against missing Python bindings
for OCCT.

Advanced options (minimum volume, angular/linear tolerances, and module name)
are exposed as CLI flags so the tessellation quality can be tuned for different
printers or slicers.

## Running tests

All Python tests live in ``tests/`` and assume the ``src/`` directory is on the
module search path. Run them with ``pytest`` or the standard library test
runner:

```bash
python -m pytest tests
# or
python -m unittest discover -s tests
```

## Contributing

Before submitting patches, review ``docs/STYLE.md`` for formatting expectations
and include the output of any validation commands in your change notes.

## Credits

The STEP tessellation helpers were inspired by the excellent
[CadQuery](https://github.com/CadQuery/cadquery) project and borrow heavily
from the algorithms published by [Open Cascade](https://www.opencascade.com/)
within [OCCT](https://github.com/Open-Cascade-SAS/OCCT). Those routines were
reimplemented in Python so this project can stay self-contained.
