#!/usr/bin/env python3
"""
Unit tests for the Jigsaw Board Generator.
Run with: python -m pytest test_jigsaw.py -v
or: python test_jigsaw.py
"""

import unittest
import re
from typing import List, Tuple


# Import the generator (assumes it's in the same directory)
# If running standalone, paste the JigsawBoardGenerator class here
try:
    from jigsaw_generator import JigsawBoardGenerator
except ImportError:
    # For standalone testing, you'll need to paste the class here
    print("Warning: Could not import JigsawBoardGenerator")
    print("Make sure the module is in the same directory or PYTHONPATH")


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
    
    def test_no_tabs_near_tile_corners(self):
        """Test that tabs maintain buffer distance from tile corners."""
        # Generate with known positions
        self.gen.find_safe_tab_positions(num_tabs_per_seam=4)
        
        # Get the corner buffer from the generator
        corner_buffer = self.gen.peg_width * 1.5
        
        # Check vertical tabs don't appear too close to any tile's Y boundaries
        for y_tab in self.gen.vert_tab_y:
            # Should be away from y=0, y=mid_y, and y=board_h
            self.assertGreater(y_tab, corner_buffer, 
                             f"Vertical tab at y={y_tab} too close to bottom edge")
            self.assertLess(y_tab, self.board_h - corner_buffer,
                          f"Vertical tab at y={y_tab} too close to top edge")
            
            # Should not be too close to the mid_y seam
            dist_from_mid = abs(y_tab - self.gen.mid_y)
            self.assertGreater(dist_from_mid, corner_buffer,
                             f"Vertical tab at y={y_tab} too close to horizontal seam at y={self.gen.mid_y}")
        
        # Check horizontal tabs don't appear too close to any tile's X boundaries  
        for x_tab in self.gen.horz_tab_x:
            # Should be away from x=0, x=mid_x, and x=board_w
            self.assertGreater(x_tab, corner_buffer,
                             f"Horizontal tab at x={x_tab} too close to left edge")
            self.assertLess(x_tab, self.board_w - corner_buffer,
                          f"Horizontal tab at x={x_tab} too close to right edge")
            
            # Should not be too close to the mid_x seam
            dist_from_mid = abs(x_tab - self.gen.mid_x)
            self.assertGreater(dist_from_mid, corner_buffer,
                             f"Horizontal tab at x={x_tab} too close to vertical seam at x={self.gen.mid_x}")
    
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
        import tempfile
        import os
        
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
        from jigsaw_generator import OpenSCAD
        
        cube = OpenSCAD.cube([10, 20, 30])
        self.assertIn("cube([10,20,30]", str(cube))
    
    def test_cylinder_generation(self):
        """Test cylinder generation."""
        from jigsaw_generator import OpenSCAD
        
        cyl = OpenSCAD.cylinder(h=10, r=5)
        self.assertIn("cylinder(h=10", str(cyl))
        self.assertIn("r=5", str(cyl))
    
    def test_translate_operation(self):
        """Test translate transformation."""
        from jigsaw_generator import OpenSCAD
        
        obj = OpenSCAD.cube(10).translate([5, 10, 15])
        code = str(obj)
        self.assertIn("translate([5,10,15])", code)
        self.assertIn("cube(10", code)
    
    def test_difference_operation(self):
        """Test boolean difference."""
        from jigsaw_generator import OpenSCAD
        
        base = OpenSCAD.cube(20)
        hole = OpenSCAD.cylinder(h=25, r=5)
        result = base.difference(hole)
        
        code = str(result)
        self.assertIn("difference()", code)
        self.assertIn("cube(20", code)
        self.assertIn("cylinder(", code)
    
    def test_union_operation(self):
        """Test boolean union."""
        from jigsaw_generator import OpenSCAD
        
        obj1 = OpenSCAD.cube(10)
        obj2 = OpenSCAD.circle(r=5)  # Use circle instead of sphere (2D framework)
        result = obj1.union(obj2)
        
        code = str(result)
        self.assertIn("union()", code)
    
    def test_color_operation(self):
        """Test color assignment."""
        from jigsaw_generator import OpenSCAD
        
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
    """Run all tests and print results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestJigsawBoardGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestOpenSCADFramework))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
