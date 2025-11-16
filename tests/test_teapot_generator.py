"""Tests covering the procedural teapot generator."""

from generators.teapot_generator import TeapotDimensions, TeapotGenerator


def test_teapot_generator_renders_modules() -> None:
    dims = TeapotDimensions(body_radius=25.0, body_height=35.0)
    generator = TeapotGenerator(dimensions=dims, segments=32)
    scad = generator.generate_scad()

    assert "module teapot_body()" in scad
    assert "module teapot_handle()" in scad
    assert "module teapot()" in scad
    assert scad.count("rotate_extrude") >= 2
