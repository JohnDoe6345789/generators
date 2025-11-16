"""Tests for the pure-Python STEP backend."""

from __future__ import annotations

from pathlib import Path

from generators.step_backend import StepBackend


def test_step_backend_loads_and_tessellates() -> None:
    backend = StepBackend()
    step_path = Path("assets") / "simplyRetro D8.step"

    solids = backend.load_solids(step_path)
    assert solids, "No solids were parsed from the STEP file."
    assert all(solid.Volume() > 0 for solid in solids)

    compound = backend.make_compound(solids)
    vertices, faces = backend.tessellate(compound, angular_tolerance=0.2, linear_tolerance=0.5)

    assert vertices and faces
    max_index = len(vertices) - 1
    assert max_index >= 0
    for face in faces:
        assert len(face) == 3
        for index in face:
            assert 0 <= index <= max_index
