"""Tests for the SimplyRetro D8 STEP-to-OpenSCAD converter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from generators.simplyretro_d8_generator import (
    SimplyRetroD8Generator,
    TessellationSettings,
    main as simplyretro_main,
)


class FakeVector:
    """Simple object emulating cadquery.Vector."""

    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z


class FakeSolid:
    """Test double providing a Volume method."""

    def __init__(self, volume: float) -> None:
        self._volume = volume

    def Volume(self) -> float:  # noqa: N802 - matches cadquery API
        return self._volume


class FakeCadQuery:
    """Minimal cadquery substitute wired into the generator."""

    def __init__(self, solids: List[FakeSolid], vectors, faces) -> None:
        self._solids = solids
        self._vectors = vectors
        self._faces = faces
        self.selected: List[FakeSolid] = []
        self.imported_path: str | None = None
        self.importers = SimpleNamespace(importStep=self._import_step)
        self.Compound = SimpleNamespace(makeCompound=self._make_compound)

    def _import_step(self, path: str):
        self.imported_path = path
        return SimpleNamespace(solids=lambda: self._solids)

    def _make_compound(self, selection: List[FakeSolid]):
        self.selected = selection
        return SimpleNamespace(tessellate=self._tessellate)

    def _tessellate(self, angular: float, linear: float):  # noqa: D401
        """Return the supplied tessellation data."""

        self.tessellate_args = (angular, linear)
        return self._vectors, self._faces


def test_build_polyhedron_data_filters_solids(monkeypatch: pytest.MonkeyPatch) -> None:
    heavy = FakeSolid(volume=150_000)
    tiny = FakeSolid(volume=10)
    vectors = [
        FakeVector(0.12345, 0.0, 0.0),
        FakeVector(0.0, 0.99999, 0.0),
        FakeVector(0.0, 0.0, 0.44444),
    ]
    faces = [(0, 1, 2)]
    backend = FakeCadQuery(solids=[tiny, heavy], vectors=vectors, faces=faces)
    settings = TessellationSettings(min_volume=50_000, precision=3)
    generator = SimplyRetroD8Generator(step_path="/tmp/die.step", settings=settings)

    monkeypatch.setattr(
        SimplyRetroD8Generator,
        "_require_cadquery",
        staticmethod(lambda: backend),
    )

    vertices, face_indices = generator._build_polyhedron_data()

    assert backend.imported_path == "/tmp/die.step"
    assert backend.selected == [heavy]
    assert backend.tessellate_args == (
        settings.angular_tolerance,
        settings.linear_tolerance,
    )
    assert vertices == [
        [0.123, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 0.444],
    ]
    assert face_indices == [[0, 1, 2]]


def test_generate_scad_renders_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = (
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        [[0, 1, 2]],
    )
    monkeypatch.setattr(
        SimplyRetroD8Generator,
        "_build_polyhedron_data",
        lambda self: data,
    )
    step_path = tmp_path / "custom.step"
    step_path.write_text("mock", encoding="utf-8")
    settings = TessellationSettings(module_name="retro_d8")
    generator = SimplyRetroD8Generator(step_path=step_path, settings=settings)

    document = generator.generate_scad()

    assert "module retro_d8()" in document
    assert f"// Source STEP: {step_path}" in document
    assert "polyhedron(points=[[0,0,0],[1,0,0],[0,1,0]], faces=[[0,1,2]], convexity=10);" in document
    assert "retro_d8();" in document.splitlines()[-1]


def test_cli_main_invokes_generator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    output_path = tmp_path / "simplyretro.scad"
    saved = {}

    def fake_save(self, destination: Path | str):
        saved["path"] = Path(destination)
        return Path(destination)

    monkeypatch.setattr(SimplyRetroD8Generator, "save_scad", fake_save, raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "simplyretro_d8_generator",
            "--output",
            str(output_path),
            "--module",
            "cli_module",
        ],
    )

    simplyretro_main()

    captured = capsys.readouterr()
    assert saved["path"] == output_path
    assert f"Saved OpenSCAD file to {output_path}" in captured.out
