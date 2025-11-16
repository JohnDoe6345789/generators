"""Unit tests for the reusable OpenSCAD helpers."""

from generators.openscad_framework import OpenSCAD


def test_rotate_extrude_renders_parameters() -> None:
    profile = OpenSCAD.square([2, 2])
    rotated = profile.rotate_extrude(angle=180, convexity=4, segments=48)
    assert "rotate_extrude(angle=180, convexity=4, $fn=48)" in rotated.code


def test_sphere_serialization() -> None:
    primitive = OpenSCAD.sphere(5, fn=32)
    assert primitive.code == "sphere(r=5, $fn=32);"
