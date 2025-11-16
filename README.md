# generators

Utility scripts and quick-start tooling for experiments that pair GUI helpers
with automation-friendly generators. The repository now follows a simple
directory structure so each component is easy to discover:

```
docs/        – Style guidance and collected test results.
scripts/     – Shell helpers for bootstrapping development environments.
src/         – Python-based generators and supporting modules.
assets/      – Shared artwork and other binary resources.
patches/     – Historical diffs or scaffolding assets.
tests/       – Unit tests that exercise the Python generators.
```

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
