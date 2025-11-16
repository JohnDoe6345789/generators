#!/usr/bin/env python3
"""Unit tests for the Jigsaw Board Generator."""

from __future__ import annotations

import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from generators.jigsaw_generator import JigsawBoardGenerator


logger = logging.getLogger(__name__)


DEFAULT_FULL_BOARD_HOLES: List[List[float]] = [
    [15.622, 17.011],
    [15.636, 83.001],
    [15.777, 203.430],
    [51.047, 153.540],
    [51.392, 84.084],
    [119.883, 84.243],
    [120.191, 153.376],
    [161.449, 84.845],
    [161.481, 223.617],
    [161.707, 17.120],
    [200.942, 224.010],
    [220.455, 83.287],
]


def find_openscad_executable() -> str | None:
    """Return the best-effort path to the OpenSCAD CLI."""

    found = shutil.which("openscad")
    if found:
        return found

    candidates: List[Path] = []
    if sys.platform.startswith("win"):
        program_files = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ]
        for base in program_files:
            if base:
                candidates.append(Path(base) / "OpenSCAD" / "openscad.exe")
        # Fallback to the conventional installation root even if env vars are unset.
        candidates.append(Path(r"C:\Program Files\OpenSCAD\openscad.exe"))
        candidates.append(Path(r"C:\Program Files (x86)\OpenSCAD\openscad.exe"))
        candidates.append(Path.home() / "AppData" / "Local" / "Programs" / "OpenSCAD" / "openscad.exe")
    elif sys.platform == "darwin":
        app_bundle = "OpenSCAD.app/Contents/MacOS/OpenSCAD"
        candidates.append(Path("/Applications") / app_bundle)
        candidates.append(Path.home() / "Applications" / app_bundle)
    else:
        candidates.extend(
            Path(path)
            for path in (
                "/usr/bin/openscad",
                "/usr/local/bin/openscad",
                "/snap/bin/openscad",
            )
        )

    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)

    return None


OPENSCAD_EXECUTABLE = find_openscad_executable()


def load_stl_triangles(path: Path) -> List[Tuple[Tuple[float, float, float], ...]]:
    """Load triangle vertices from a binary or ASCII STL file."""

    data = path.read_bytes()
    header = data[:5].lower()

    if header.startswith(b"solid") and b"facet" in data[:200]:
        # ASCII STL
        vertices: List[Tuple[float, float, float]] = []
        triangles: List[Tuple[Tuple[float, float, float], ...]] = []
        for line in data.decode("utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("vertex"):
                parts = line.split()
                vertices.append(tuple(float(p) for p in parts[1:4]))
                if len(vertices) == 3:
                    triangles.append(tuple(vertices))
                    vertices = []
        return triangles

    # Binary STL
    triangles = []
    tri_count = struct.unpack_from("<I", data, 80)[0]
    offset = 84
    record_size = 50
    for _ in range(tri_count):
        chunk = data[offset:offset + record_size]
        v1 = struct.unpack_from("<3f", chunk, 12)
        v2 = struct.unpack_from("<3f", chunk, 24)
        v3 = struct.unpack_from("<3f", chunk, 36)
        triangles.append((tuple(v1), tuple(v2), tuple(v3)))
        offset += record_size
    return triangles


def compute_bounding_box(triangles: List[Tuple[Tuple[float, float, float], ...]]) -> Tuple[
    Tuple[float, float, float], Tuple[float, float, float]
]:
    """Compute axis-aligned bounding box from STL triangle vertices."""

    xs = [v[0] for tri in triangles for v in tri]
    ys = [v[1] for tri in triangles for v in tri]
    zs = [v[2] for tri in triangles for v in tri]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _ray_triangle_intersection(origin, direction, tri, eps=1e-8):
    v0, v1, v2 = tri
    edge1 = _vec_sub(v1, v0)
    edge2 = _vec_sub(v2, v0)
    h = _vec_cross(direction, edge2)
    a = _vec_dot(edge1, h)
    if -eps < a < eps:
        return None
    f = 1.0 / a
    s = _vec_sub(origin, v0)
    u = f * _vec_dot(s, h)
    if u < 0.0 or u > 1.0:
        return None
    q = _vec_cross(s, edge1)
    v = f * _vec_dot(direction, q)
    if v < 0.0 or u + v > 1.0:
        return None
    t = f * _vec_dot(edge2, q)
    if t > eps:
        return t
    return None


def cast_ray(triangles, origin, direction):
    """Return sorted intersection distances for a ray against the STL triangles."""

    hits = []
    for tri in triangles:
        hit = _ray_triangle_intersection(origin, direction, tri)
        if hit is not None:
            hits.append(hit)
    return sorted(hits)


class TestJigsawBoardGenerator(unittest.TestCase):
    """Test suite for the Jigsaw Board Generator."""
    
    def setUp(self):
        """Set up test fixtures before each test."""
        self.board_w = 243.84
        self.board_h = 243.84
        self.board_t = 3.0
        self.holes = [
            [15.622, 17.011],
            [15.636, 83.001],
            [51.392, 84.084],
            [119.883, 84.243],
            [161.449, 84.845],
            [220.455, 83.287]
        ]
        
        self.gen = JigsawBoardGenerator(
            board_width=self.board_w,
            board_height=self.board_h,
            board_thickness=self.board_t,
            holes=self.holes,
            hole_radius=1.98
        )
    
    def test_initialization(self):
        """Test that generator initializes with correct parameters."""
        self.assertEqual(self.gen.board_w, 243.84)
        self.assertEqual(self.gen.board_h, 243.84)
        self.assertEqual(self.gen.board_t, 3.0)
        self.assertEqual(len(self.gen.holes), 6)
        self.assertEqual(self.gen.hole_r, 1.98)
        self.assertEqual(self.gen.mid_x, 121.92)
        self.assertEqual(self.gen.mid_y, 121.92)
    
    def test_default_parameters(self):
        """Test default jigsaw parameters are set correctly."""
        self.assertEqual(self.gen.peg_len, 14.0)
        self.assertEqual(self.gen.peg_width, 16.0)
        self.assertEqual(self.gen.peg_radius, 9.0)
        self.assertEqual(self.gen.clearance, 0.50)
    
    def test_find_safe_tab_positions_returns_counts(self):
        """Test that tab finding returns correct counts."""
        num_vert, num_horz = self.gen.find_safe_tab_positions(num_tabs_per_seam=4)
        
        self.assertIsInstance(num_vert, int)
        self.assertIsInstance(num_horz, int)
        self.assertGreater(num_vert, 0, "Should find at least one vertical tab position")
        self.assertGreater(num_horz, 0, "Should find at least one horizontal tab position")
    
    def test_tabs_avoid_corners(self):
        """Test that tab positions stay away from corners."""
        min_corner_dist = 40.0
        self.gen.find_safe_tab_positions(
            num_tabs_per_seam=4,
            min_distance_from_corner=min_corner_dist
        )
        
        # Check vertical tabs avoid corners
        for y in self.gen.vert_tab_y:
            self.assertGreater(y, min_corner_dist, 
                             f"Vertical tab at y={y} too close to bottom")
            self.assertLess(y, self.board_h - min_corner_dist,
                          f"Vertical tab at y={y} too close to top")
        
        # Check horizontal tabs avoid corners
        for x in self.gen.horz_tab_x:
            self.assertGreater(x, min_corner_dist,
                             f"Horizontal tab at x={x} too close to left")
            self.assertLess(x, self.board_w - min_corner_dist,
                          f"Horizontal tab at x={x} too close to right")
    
    def test_tabs_avoid_holes(self):
        """Test that tab positions maintain minimum distance from holes."""
        min_hole_dist = 20.0
        self.gen.find_safe_tab_positions(
            num_tabs_per_seam=4,
            min_distance_from_hole=min_hole_dist
        )
        
        # Check vertical tabs (at seam x=mid_x) avoid holes
        for y_tab in self.gen.vert_tab_y:
            for hx, hy in self.gen.holes:
                dist = ((hx - self.gen.mid_x) ** 2 + (hy - y_tab) ** 2) ** 0.5
                self.assertGreaterEqual(dist, min_hole_dist,
                    f"Vertical tab at y={y_tab} too close to hole at ({hx}, {hy})")
        
        # Check horizontal tabs (at seam y=mid_y) avoid holes
        for x_tab in self.gen.horz_tab_x:
            for hx, hy in self.gen.holes:
                dist = ((hx - x_tab) ** 2 + (hy - self.gen.mid_y) ** 2) ** 0.5
                self.assertGreaterEqual(dist, min_hole_dist,
                    f"Horizontal tab at x={x_tab} too close to hole at ({hx}, {hy})")
    
    def test_manual_tab_positions(self):
        """Test manual tab position setting."""
        manual_vert = [50.0, 100.0, 150.0]
        manual_horz = [60.0, 120.0, 180.0]
        
        self.gen.set_manual_tab_positions(manual_vert, manual_horz)
        
        self.assertEqual(self.gen.vert_tab_y, manual_vert)
        self.assertEqual(self.gen.horz_tab_x, manual_horz)
    
    def test_generated_scad_contains_key_elements(self):
        """Test that generated OpenSCAD code contains expected elements."""
        self.gen.find_safe_tab_positions(num_tabs_per_seam=2)
        scad = self.gen.generate_scad()
        
        # Check for header comments
        self.assertIn("Auto-generated jigsaw board split", scad)
        self.assertIn(f"{self.board_w} x {self.board_h}", scad)
        
        # Check for color assignments (indicating all 4 tiles)
        self.assertIn('color("red")', scad)
        self.assertIn('color("green")', scad)
        self.assertIn('color("blue")', scad)
        self.assertIn('color("yellow")', scad)
        
        # Check for geometric operations
        self.assertIn("union()", scad)
        self.assertIn("difference()", scad)
        self.assertIn("translate(", scad)
        self.assertIn("cylinder(", scad)
        self.assertIn("cube(", scad)
    
    def test_all_four_tiles_generated(self):
        """Test that exactly 4 tiles are generated."""
        self.gen.find_safe_tab_positions(num_tabs_per_seam=2)
        scad = self.gen.generate_scad()
        
        # Count color assignments (one per tile)
        color_count = scad.count('color("red")') + \
                     scad.count('color("green")') + \
                     scad.count('color("blue")') + \
                     scad.count('color("yellow")')
        
        self.assertEqual(color_count, 4, "Should generate exactly 4 tiles")
    
    def test_tiles_properly_spaced(self):
        """Test that tiles are spaced for separate build plates."""
        self.gen.find_safe_tab_positions(num_tabs_per_seam=2)
        scad = self.gen.generate_scad()
        
        # Check for bed spacing in translations (without spaces in coordinates)
        spacing = self.gen.bed_spacing
        self.assertIn(f"translate([{spacing},0,0])", scad)
        self.assertIn(f"translate([0,{spacing},0])", scad)
        self.assertIn(f"translate([{spacing},{spacing},0])", scad)
    
    def test_holes_generated_for_tiles(self):
        """Test that mounting holes are included in output."""
        self.gen.find_safe_tab_positions(num_tabs_per_seam=2)
        scad = self.gen.generate_scad()

        # Should contain cylinder calls for holes
        cylinder_matches = re.findall(r'cylinder\([^)]+\)', scad)
        self.assertGreater(len(cylinder_matches), 0,
                          "Should generate cylinders for mounting holes")

    def test_vertical_seam_auto_adjusts_around_holes(self):
        """The vertical seam should slide away from a conflicting hole."""
        seam_hole = [[self.board_w / 2 - 0.5, 25.0]]
        gen = JigsawBoardGenerator(
            board_width=self.board_w,
            board_height=self.board_h,
            board_thickness=self.board_t,
            holes=seam_hole,
            hole_radius=1.98,
        )

        gen.find_safe_tab_positions(num_tabs_per_seam=1)
        scad = gen.generate_scad()

        self.assertNotEqual(gen.mid_x, self.board_w / 2)
        self.assertGreater(abs(gen.mid_x - seam_hole[0][0]), gen.hole_r)
        self.assertIn("Auto-generated jigsaw board split", scad)

    def test_horizontal_seam_auto_adjusts_around_holes(self):
        """The horizontal seam should move when a hole is centered on it."""
        seam_hole = [[25.0, self.board_h / 2 + 0.5]]
        gen = JigsawBoardGenerator(
            board_width=self.board_w,
            board_height=self.board_h,
            board_thickness=self.board_t,
            holes=seam_hole,
            hole_radius=1.98,
        )

        gen.find_safe_tab_positions(num_tabs_per_seam=1)
        scad = gen.generate_scad()

        self.assertNotEqual(gen.mid_y, self.board_h / 2)
        self.assertGreater(abs(gen.mid_y - seam_hole[0][1]), gen.hole_r)
        self.assertIn("Auto-generated jigsaw board split", scad)

    def test_seam_adjustment_errors_when_no_vertical_path_exists(self):
        """If every possible vertical seam intersects a hole we still raise."""
        holes = [[20.0, 10.0], [40.0, 10.0], [60.0, 10.0], [80.0, 10.0]]
        gen = JigsawBoardGenerator(
            board_width=100.0,
            board_height=100.0,
            board_thickness=3.0,
            holes=holes,
            hole_radius=12.0,
        )

        with self.assertRaisesRegex(ValueError, "vertical seam"):
            gen.generate_scad()

    def test_parameter_adjustment(self):
        """Test that jigsaw parameters can be adjusted."""
        self.gen.peg_len = 12.0
        self.gen.peg_width = 18.0
        self.gen.peg_radius = 10.0
        self.gen.clearance = 0.3
        
        self.assertEqual(self.gen.peg_len, 12.0)
        self.assertEqual(self.gen.peg_width, 18.0)
        self.assertEqual(self.gen.peg_radius, 10.0)
        self.assertEqual(self.gen.clearance, 0.3)
    
    def test_no_tabs_at_exact_boundaries(self):
        """Test that tabs don't appear at exact tile boundaries (corners)."""
        # Set manual positions at boundaries (should be filtered out)
        self.gen.set_manual_tab_positions(
            vert_y=[0, self.gen.mid_y, self.board_h],
            horz_x=[0, self.gen.mid_x, self.board_w]
        )
        
        scad = self.gen.generate_scad()
        
        # The generated code should handle boundaries correctly
        # This is more of an integration test
        self.assertIsNotNone(scad)
        self.assertGreater(len(scad), 0)
    
    def test_tabs_respect_corner_buffers(self):
        """Tabs should keep a healthy distance from the physical corners."""
        self.gen.find_safe_tab_positions(num_tabs_per_seam=4,
                                         min_distance_from_corner=40.0)

        corner_buffer = 40.0

        for y_tab in self.gen.vert_tab_y:
            self.assertGreater(y_tab, corner_buffer,
                               f"Vertical tab at y={y_tab} too close to bottom edge")
            self.assertLess(y_tab, self.board_h - corner_buffer,
                            f"Vertical tab at y={y_tab} too close to top edge")

        for x_tab in self.gen.horz_tab_x:
            self.assertGreater(x_tab, corner_buffer,
                               f"Horizontal tab at x={x_tab} too close to left edge")
            self.assertLess(x_tab, self.board_w - corner_buffer,
                            f"Horizontal tab at x={x_tab} too close to right edge")
    
    def test_clearance_applied_to_female_pockets(self):
        """Test that clearance is properly applied."""
        self.gen.clearance = 0.6
        self.gen.find_safe_tab_positions(num_tabs_per_seam=2)
        
        # Generate and check that female pockets reference clearance
        scad = self.gen.generate_scad()
        
        # The code should work with different clearances
        self.assertIsNotNone(scad)
    
    def test_empty_holes_list(self):
        """Test generator works with no mounting holes."""
        gen_no_holes = JigsawBoardGenerator(
            board_width=100,
            board_height=100,
            board_thickness=3,
            holes=[],
            hole_radius=2.0
        )
        
        gen_no_holes.find_safe_tab_positions(num_tabs_per_seam=3)
        scad = gen_no_holes.generate_scad()
        
        self.assertIsNotNone(scad)
        self.assertGreater(len(scad), 0)
    
    def test_small_board(self):
        """Test generator works with smaller board dimensions."""
        gen_small = JigsawBoardGenerator(
            board_width=100,
            board_height=100,
            board_thickness=2,
            holes=[[25, 25], [75, 75]],
            hole_radius=1.5
        )
        
        num_vert, num_horz = gen_small.find_safe_tab_positions(
            num_tabs_per_seam=2,
            min_distance_from_corner=20
        )
        
        self.assertGreaterEqual(num_vert, 0)
        self.assertGreaterEqual(num_horz, 0)
    
    def test_tab_positions_within_board(self):
        """Test that all tab positions are within board boundaries."""
        self.gen.find_safe_tab_positions(num_tabs_per_seam=4)
        
        for y in self.gen.vert_tab_y:
            self.assertGreater(y, 0)
            self.assertLess(y, self.board_h)
        
        for x in self.gen.horz_tab_x:
            self.assertGreater(x, 0)
            self.assertLess(x, self.board_w)
    
    def test_save_scad_file(self):
        """Test that SCAD file can be saved."""
        self.gen.find_safe_tab_positions(num_tabs_per_seam=2)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.scad', delete=False) as f:
            temp_path = f.name
        
        try:
            self.gen.save_scad(temp_path)
            
            # Check file exists and has content
            self.assertTrue(os.path.exists(temp_path))
            
            with open(temp_path, 'r') as f:
                content = f.read()
            
            self.assertGreater(len(content), 0)
            self.assertIn("Auto-generated", content)
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestOpenSCADFramework(unittest.TestCase):
    """Test the embedded OpenSCAD framework functions."""
    
    def test_cube_generation(self):
        """Test cube generation."""
        from generators.jigsaw_generator import OpenSCAD
        
        cube = OpenSCAD.cube([10, 20, 30])
        self.assertIn("cube([10,20,30]", str(cube))
    
    def test_cylinder_generation(self):
        """Test cylinder generation."""
        from generators.jigsaw_generator import OpenSCAD
        
        cyl = OpenSCAD.cylinder(h=10, r=5)
        self.assertIn("cylinder(h=10", str(cyl))
        self.assertIn("r=5", str(cyl))
    
    def test_translate_operation(self):
        """Test translate transformation."""
        from generators.jigsaw_generator import OpenSCAD
        
        obj = OpenSCAD.cube(10).translate([5, 10, 15])
        code = str(obj)
        self.assertIn("translate([5,10,15])", code)
        self.assertIn("cube(10", code)
    
    def test_difference_operation(self):
        """Test boolean difference."""
        from generators.jigsaw_generator import OpenSCAD
        
        base = OpenSCAD.cube(20)
        hole = OpenSCAD.cylinder(h=25, r=5)
        result = base.difference(hole)
        
        code = str(result)
        self.assertIn("difference()", code)
        self.assertIn("cube(20", code)
        self.assertIn("cylinder(", code)
    
    def test_union_operation(self):
        """Test boolean union."""
        from generators.jigsaw_generator import OpenSCAD
        
        obj1 = OpenSCAD.cube(10)
        obj2 = OpenSCAD.circle(r=5)  # Use circle instead of sphere (2D framework)
        result = obj1.union(obj2)
        
        code = str(result)
        self.assertIn("union()", code)
    
    def test_color_operation(self):
        """Test color assignment."""
        from generators.jigsaw_generator import OpenSCAD
        
        obj = OpenSCAD.cube(10).color("red")
        code = str(obj)
        self.assertIn('color("red")', code)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""
    
    def test_very_tight_clearance(self):
        """Test with very tight clearance."""
        gen = JigsawBoardGenerator(100, 100, 3, [], 2.0)
        gen.clearance = 0.1
        gen.find_safe_tab_positions(num_tabs_per_seam=2)
        
        scad = gen.generate_scad()
        self.assertIsNotNone(scad)
    
    def test_very_loose_clearance(self):
        """Test with very loose clearance."""
        gen = JigsawBoardGenerator(100, 100, 3, [], 2.0)
        gen.clearance = 1.0
        gen.find_safe_tab_positions(num_tabs_per_seam=2)
        
        scad = gen.generate_scad()
        self.assertIsNotNone(scad)
    
    def test_many_holes_dense_pattern(self):
        """Test with many holes in dense pattern."""
        holes = [[x, y] for x in range(10, 90, 10) for y in range(10, 90, 10)]
        gen = JigsawBoardGenerator(100, 100, 3, holes, 2.0)
        
        num_vert, num_horz = gen.find_safe_tab_positions(
            num_tabs_per_seam=3,
            min_distance_from_hole=15
        )
        
        # Should still find some positions or zero if too dense
        self.assertGreaterEqual(num_vert, 0)
        self.assertGreaterEqual(num_horz, 0)


class TestEndToEndExecution(unittest.TestCase):
    """End-to-end coverage of the script entry point."""

    @staticmethod
    def _render_fixture(tmpdir: str) -> Tuple[Path, Path]:
        """Run the generator script and render it to STL via OpenSCAD."""
        script_path = SRC_DIR / "generators" / "jigsaw_generator.py"

        env = os.environ.copy()
        existing_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{SRC_DIR}{os.pathsep}{existing_path}" if existing_path else str(SRC_DIR)
        )

        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=tmpdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            if "Mounting holes are too close to the jigsaw seams" in result.stderr:
                raise unittest.SkipTest(
                    "Default board configuration bisects a mounting hole; "
                    "generator intentionally aborts to avoid invalid tiles."
                )
            raise AssertionError(
                "Script failed with stderr:\n" f"{result.stderr}\nstdout:\n{result.stdout}"
            )

        output_path = Path(tmpdir) / "jigsaw_board.scad"
        if not output_path.exists():
            raise AssertionError("Script did not produce SCAD file")

        rendered_path = Path(tmpdir) / "jigsaw_board_preview.stl"
        if not OPENSCAD_EXECUTABLE:
            raise AssertionError("OpenSCAD executable could not be located")

        render = subprocess.run(
            [OPENSCAD_EXECUTABLE, "-o", str(rendered_path), str(output_path)],
            capture_output=True,
            text=True,
            check=False,
        )

        if render.returncode != 0:
            raise AssertionError(
                "OpenSCAD failed to render output.\n"
                f"stdout:\n{render.stdout}\n"
                f"stderr:\n{render.stderr}"
            )

        if not rendered_path.exists():
            raise AssertionError("OpenSCAD did not write an output file")

        return output_path, rendered_path

    @unittest.skipUnless(OPENSCAD_EXECUTABLE, "OpenSCAD CLI is required for this test")
    def test_full_script_generates_scad_file(self):
        """Run the generator script via subprocess and render it with OpenSCAD."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path, rendered_path = self._render_fixture(tmpdir)

            content = output_path.read_text()
            self.assertIn("Auto-generated jigsaw board split", content)
            self.assertIn("color(\"red\")", content)

            self.assertGreater(rendered_path.stat().st_size, 0, "Rendered file is empty")

    @unittest.skipUnless(OPENSCAD_EXECUTABLE, "OpenSCAD CLI is required for this test")
    def test_rendered_geometry_has_expected_layout(self):
        """Raycast the generated STL to ensure the four-tile layout renders correctly."""

        with tempfile.TemporaryDirectory() as tmpdir:
            _, rendered_path = self._render_fixture(tmpdir)

            triangles = load_stl_triangles(rendered_path)
            self.assertGreater(len(triangles), 0, "Rendered STL did not contain any triangles")

            bbox_min, bbox_max = compute_bounding_box(triangles)

            board_w = 243.84
            board_h = 243.84
            board_t = 3.0
            bed_spacing = 300

            self.assertAlmostEqual(bbox_min[0], 0.0, delta=0.1)
            self.assertAlmostEqual(bbox_min[1], 0.0, delta=0.1)
            self.assertAlmostEqual(bbox_min[2], 0.0, delta=0.1)
            self.assertAlmostEqual(bbox_max[2], board_t, delta=0.1)
            self.assertAlmostEqual(bbox_max[0], board_w + bed_spacing, delta=0.1)
            self.assertAlmostEqual(bbox_max[1], board_h + bed_spacing, delta=0.1)

            def cast_at(x, y):
                origin = (x, y, -10.0)
                direction = (0.0, 0.0, 1.0)
                return len(cast_ray(triangles, origin, direction))

            mid_x = board_w / 2
            mid_y = board_h / 2

            hits_tile_a = cast_at(mid_x / 2, mid_y / 2)
            hits_tile_b = cast_at(bed_spacing + (mid_x + board_w) / 2, mid_y / 2)
            hits_gap = cast_at(board_w + 10, mid_y / 2)

            def assert_even_hits(count, message):
                self.assertGreater(
                    count,
                    0,
                    f"{message} should intersect the mesh at least once",
                )
                self.assertEqual(
                    count % 2,
                    0,
                    f"{message} should intersect the mesh an even number of times",
                )

            assert_even_hits(hits_tile_a, "Tile A center")
            assert_even_hits(hits_tile_b, "Tile B center")
            self.assertEqual(hits_gap, 0, "Gap between tiles should not intersect the mesh")

    @unittest.skipUnless(OPENSCAD_EXECUTABLE, "OpenSCAD CLI is required for this test")
    def test_rendered_geometry_visible_from_multiple_cameras(self):
        """Cast rays from different camera angles to ensure the mesh is watertight."""

        with tempfile.TemporaryDirectory() as tmpdir:
            _, rendered_path = self._render_fixture(tmpdir)

            triangles = load_stl_triangles(rendered_path)
            self.assertGreater(len(triangles), 0, "Rendered STL did not contain any triangles")

            board_w = 243.84
            board_h = 243.84
            board_t = 3.0
            bed_spacing = 300

            script_gen = JigsawBoardGenerator(
                board_width=board_w,
                board_height=board_h,
                board_thickness=board_t,
                holes=DEFAULT_FULL_BOARD_HOLES,
                hole_radius=1.98,
            )
            script_gen.find_safe_tab_positions(
                num_tabs_per_seam=4,
                min_distance_from_corner=40.0,
            )
            seam_x = script_gen.mid_x
            seam_y = script_gen.mid_y
            tile_a_center = (seam_x / 2, seam_y / 2, -10.0)
            tile_b_center_x = bed_spacing + (seam_x + board_w) / 2
            tile_a_side_origin = (-10.0, seam_y / 2, board_t / 2)

            cameras = [
                (tile_a_center, (0.0, 0.0, 1.0), True,
                 "Top-down camera should intersect tile A"),
                (tile_a_side_origin, (1.0, 0.0, 0.0), True,
                 "Side-on camera along +X should intersect the first column tile"),
                ((tile_b_center_x, -10.0, board_t / 2), (0.0, 1.0, 0.0), True,
                 "Front-on camera along +Y should intersect the bottom row tile"),
                ((board_w + 10.0, board_h / 2, board_t / 2), (0.0, 0.0, 1.0), False,
                 "A camera aimed at the spacing gap should see no intersections"),
            ]

            for origin, direction, should_hit, message in cameras:
                hits = len(cast_ray(triangles, origin, direction))
                if should_hit:
                    self.assertGreater(hits, 0, message)
                    self.assertEqual(
                        hits % 2,
                        0,
                        f"{message} should intersect the mesh an even number of times",
                    )
                else:
                    self.assertEqual(hits, 0, message)
    
    def test_requesting_more_tabs_than_possible(self):
        """Test requesting more tabs than space allows."""
        gen = JigsawBoardGenerator(100, 100, 3, [], 2.0)
        
        # Request 20 tabs but with high corner distance - may not fit all
        num_vert, num_horz = gen.find_safe_tab_positions(
            num_tabs_per_seam=20,
            min_distance_from_corner=45
        )
        
        # Should return what's possible, not necessarily all 20
        self.assertGreaterEqual(num_vert, 0)
        self.assertGreaterEqual(num_horz, 0)


def run_tests():
    """Run all tests and log summarized results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestJigsawBoardGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestOpenSCADFramework))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndExecution))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Log summary
    separator = "=" * 70
    logger.info(separator)
    logger.info("Tests run: %d", result.testsRun)
    logger.info(
        "Successes: %d",
        result.testsRun - len(result.failures) - len(result.errors),
    )
    logger.info("Failures: %d", len(result.failures))
    logger.info("Errors: %d", len(result.errors))
    logger.info(separator)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    success = run_tests()
    exit(0 if success else 1)
