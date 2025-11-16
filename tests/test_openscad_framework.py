"""Unit tests for the reusable OpenSCAD helpers."""

import pytest

from generators.openscad_framework import OpenSCAD, Vector


def test_rotate_extrude_renders_parameters() -> None:
    profile = OpenSCAD.square([2, 2])
    rotated = profile.rotate_extrude(angle=180, convexity=4, segments=48)
    assert "rotate_extrude(angle=180, convexity=4, $fn=48)" in rotated.code


def test_sphere_serialization() -> None:
    primitive = OpenSCAD.sphere(5, fn=32)
    assert primitive.code == "sphere(r=5, $fn=32);"


def test_vector_arithmetic_and_length() -> None:
    left = Vector(1, 2, 3)
    right = Vector([3, -2, 0])
    summed = left + right
    assert summed.to_tuple() == (4.0, 0.0, 3.0)
    assert (left - right).to_tuple() == (-2.0, 4.0, 3.0)
    assert summed.length == (4.0 ** 2 + 0.0 ** 2 + 3.0 ** 2) ** 0.5


def test_vector_dot_cross_and_normalize() -> None:
    a = Vector(1, 0, 0)
    b = Vector(0, 1, 0)
    assert a.dot(b) == 0.0
    assert a.cross(b) == Vector(0, 0, 1)
    normalized = Vector([10, 0, 0]).normalized()
    assert normalized == a
    assert normalized.angle_to(b) == pytest.approx(1.57079632679)
