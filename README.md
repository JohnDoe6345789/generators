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

## SimplyRetro D8 OpenSCAD generator

The `src/generators/simplyretro_d8_generator.py` module reads
`assets/simplyRetro D8.step`, tessellates the mesh with
[`cadquery`](https://cadquery.readthedocs.io/), and emits OpenSCAD code using
the shared framework that powers the jigsaw and teapot generators. Install
CadQuery and export the die with:

```bash
pip install cadquery
PYTHONPATH=src python -m generators.simplyretro_d8_generator --output simplyretro_d8.scad
```

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
