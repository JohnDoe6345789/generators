#!/usr/bin/env python3
"""
Generate OpenSCAD code for splitting a board with mounting holes into jigsaw tiles.
Uses the OpenSCAD Python framework for clean, programmatic generation.
"""

import logging
from typing import List, Tuple


logger = logging.getLogger(__name__)

# Embedded OpenSCAD framework
class OpenSCAD:
    """Main class for building OpenSCAD objects with chainable operations."""
    
    def __init__(self, code=""):
        self.code = code
    
    def __str__(self):
        return self.code
    
    def __add__(self, other):
        return OpenSCAD(f"{self.code}\n{other.code}")
    
    @staticmethod
    def cube(size, center=False):
        if isinstance(size, (list, tuple)):
            s = f"[{','.join(map(str, size))}]"
        else:
            s = str(size)
        c = "true" if center else "false"
        return OpenSCAD(f"cube({s}, center={c});")
    
    @staticmethod
    def cylinder(h, r=None, d=None, center=False):
        params = [f"h={h}"]
        if r is not None:
            params.append(f"r={r}")
        elif d is not None:
            params.append(f"d={d}")
        if center:
            params.append("center=true")
        params.append("$fn=64")
        return OpenSCAD(f"cylinder({', '.join(params)});")
    
    @staticmethod
    def circle(r=None, d=None, fn=48):
        if r is not None:
            return OpenSCAD(f"circle(r={r}, $fn={fn});")
        return OpenSCAD(f"circle(d={d}, $fn={fn});")
    
    @staticmethod
    def square(size, center=False):
        if isinstance(size, (list, tuple)):
            s = f"[{','.join(map(str, size))}]"
        else:
            s = str(size)
        c = "true" if center else "false"
        return OpenSCAD(f"square({s}, center={c});")
    
    @staticmethod
    def polygon(points):
        pts = "[" + ",".join(f"[{','.join(map(str, p))}]" for p in points) + "]"
        return OpenSCAD(f"polygon(points={pts});")
    
    def translate(self, v):
        vec = f"[{','.join(map(str, v))}]"
        return OpenSCAD(f"translate({vec}) {{\n{self.code}\n}}")
    
    def rotate(self, a, v=None):
        if v is None:
            if isinstance(a, (list, tuple)):
                ang = f"[{','.join(map(str, a))}]"
            else:
                ang = str(a)
            return OpenSCAD(f"rotate({ang}) {{\n{self.code}\n}}")
        else:
            vec = f"[{','.join(map(str, v))}]"
            return OpenSCAD(f"rotate(a={a}, v={vec}) {{\n{self.code}\n}}")
    
    def color(self, c):
        if isinstance(c, str):
            col = f'"{c}"'
        else:
            col = f"[{','.join(map(str, c))}]"
        return OpenSCAD(f"color({col}) {{\n{self.code}\n}}")
    
    def union(self, *others):
        objects = [self] + list(others)
        combined = "\n".join(obj.code for obj in objects)
        return OpenSCAD(f"union() {{\n{combined}\n}}")
    
    def difference(self, *others):
        objects = [self] + list(others)
        combined = "\n".join(obj.code for obj in objects)
        return OpenSCAD(f"difference() {{\n{combined}\n}}")
    
    def hull(self, *others):
        if others:
            objects = [self] + list(others)
            combined = "\n".join(obj.code for obj in objects)
            return OpenSCAD(f"hull() {{\n{combined}\n}}")
        return OpenSCAD(f"hull() {{\n{self.code}\n}}")
    
    def linear_extrude(self, height, center=False, twist=0, scale=1):
        params = [f"height={height}"]
        if center:
            params.append("center=true")
        if twist != 0:
            params.append(f"twist={twist}")
        if scale != 1:
            params.append(f"scale={scale}")
        return OpenSCAD(f"linear_extrude({', '.join(params)}) {{\n{self.code}\n}}")


class GeometryMath:
    """Utility helpers for common 2D geometric calculations."""

    @staticmethod
    def distance(point_a: Tuple[float, float], point_b: Tuple[float, float]) -> float:
        """Return the Euclidean distance between two XY points."""

        ax, ay = point_a
        bx, by = point_b
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    @staticmethod
    def is_within(value: float, lower: float, upper: float,
                  inclusive: bool = False) -> bool:
        """Return True if ``value`` lies within the provided bounds."""

        if inclusive:
            return lower <= value <= upper
        return lower < value < upper


class JigsawBoardGenerator:
    def __init__(self, 
                 board_width: float,
                 board_height: float,
                 board_thickness: float,
                 holes: List[Tuple[float, float]],
                 hole_radius: float = 1.98):
        """
        Initialize the jigsaw board generator.
        
        Args:
            board_width: Board width in mm
            board_height: Board height in mm
            board_thickness: Board thickness in mm
            holes: List of (x, y) coordinates for mounting holes
            hole_radius: Radius of mounting holes in mm
        """
        self.board_w = board_width
        self.board_h = board_height
        self.board_t = board_thickness
        self.holes = holes
        self.hole_r = hole_radius
        
        # Jigsaw parameters (adjustable for tighter/looser fit)
        self.peg_len = 14.0      # Depth of tab
        self.peg_width = 16.0    # Width of tab
        self.peg_radius = 9.0    # Rounded knob radius
        self.clearance = 0.50    # Extra clearance for female cuts
        
        # Calculate seam locations (default to geometric midpoints).  These may
        # be nudged slightly to avoid bisecting mounting holes.
        self.mid_x = board_width / 2
        self.mid_y = board_height / 2
        self._seams_locked = False
        
        # Tab positions
        self.vert_tab_y = []
        self.horz_tab_x = []
        
        # Spacing for multi-plate layout
        self.bed_spacing = 300
    
    def find_safe_tab_positions(self, num_tabs_per_seam: int = 4, 
                                min_distance_from_hole: float = 20.0,
                                min_distance_from_corner: float = 40.0):
        """
        Automatically find safe positions for tabs that avoid mounting holes and corners.
        
        Args:
            num_tabs_per_seam: Number of tabs to place on each seam
            min_distance_from_hole: Minimum distance from any hole center
            min_distance_from_corner: Minimum distance from board corners
        """
        self._ensure_safe_seams()

        # Find vertical tab positions (along y-axis at x = mid_x)
        y_candidates = []
        y_min = min_distance_from_corner
        y_max = self.board_h - min_distance_from_corner
        y_range = y_max - y_min
        
        step = y_range / (num_tabs_per_seam + 1)
        for i in range(1, num_tabs_per_seam + 1):
            y_pos = y_min + i * step

            safe = True
            for hx, hy in self.holes:
                dist = GeometryMath.distance((hx, hy), (self.mid_x, y_pos))
                if dist < min_distance_from_hole:
                    safe = False
                    break
            
            if safe:
                y_candidates.append(y_pos)
        
        # Find horizontal tab positions (along x-axis at y = mid_y)
        x_candidates = []
        x_min = min_distance_from_corner
        x_max = self.board_w - min_distance_from_corner
        x_range = x_max - x_min
        
        step = x_range / (num_tabs_per_seam + 1)
        for i in range(1, num_tabs_per_seam + 1):
            x_pos = x_min + i * step

            safe = True
            for hx, hy in self.holes:
                dist = GeometryMath.distance((hx, hy), (x_pos, self.mid_y))
                if dist < min_distance_from_hole:
                    safe = False
                    break
            
            if safe:
                x_candidates.append(x_pos)
        
        self.vert_tab_y = y_candidates[:num_tabs_per_seam]
        self.horz_tab_x = x_candidates[:num_tabs_per_seam]
        
        return len(self.vert_tab_y), len(self.horz_tab_x)
    
    def set_manual_tab_positions(self, vert_y: List[float], horz_x: List[float]):
        """Manually set tab positions."""
        self.vert_tab_y = vert_y
        self.horz_tab_x = horz_x
    
    def _create_male_profile_2d(self) -> OpenSCAD:
        """Create the 2D male tab profile with rounded base."""
        # Rounded base using hull
        base = OpenSCAD.circle(r=1, fn=16).translate([1, 1]).hull(
            OpenSCAD.circle(r=1, fn=16).translate([1, self.peg_width - 1]),
            OpenSCAD.circle(r=0.5, fn=16).translate([self.peg_len - self.peg_radius, self.peg_width/2])
        )
        
        # Main rounded knob
        knob = OpenSCAD.circle(r=self.peg_radius, fn=48).translate([self.peg_len/2, self.peg_width/2])
        
        return base.union(knob)
    
    def _create_female_profile_2d(self) -> OpenSCAD:
        """Create the 2D female pocket profile with entry chamfers."""
        extra = self.clearance
        chamfer = 1.5
        
        # Main pocket
        pocket = OpenSCAD.square([self.peg_len + 2*extra, self.peg_width + 2*extra]).translate([-extra, -extra])
        
        # Rounded knob pocket
        knob_pocket = OpenSCAD.circle(r=self.peg_radius + extra, fn=48).translate([self.peg_len/2, self.peg_width/2])
        
        # Entry chamfers
        chamfer1 = OpenSCAD.polygon([[0, 0], [chamfer, 0], [0, chamfer]]).translate([-extra - chamfer, -extra])
        chamfer2 = OpenSCAD.polygon([[0, 0], [0, -chamfer], [chamfer, 0]]).translate([-extra - chamfer, self.peg_width + extra])
        
        return pocket.union(knob_pocket, chamfer1, chamfer2)
    
    def _create_vert_male_tab(self, y_mid: float) -> OpenSCAD:
        """Create a vertical male tab at the given Y position."""
        profile = self._create_male_profile_2d()
        return profile.linear_extrude(height=self.board_t).translate([
            self.mid_x,
            y_mid - self.peg_width/2,
            0,
        ])
    
    def _create_vert_female_pocket(self, y_mid: float) -> OpenSCAD:
        """Create a vertical female pocket at the given Y position."""
        profile = self._create_female_profile_2d()
        return profile.linear_extrude(height=self.board_t + 2).translate([
            self.mid_x,
            y_mid - self.peg_width/2 - self.clearance,
            -1,
        ])
    
    def _create_horz_male_tab(self, x_mid: float) -> OpenSCAD:
        """Create a horizontal male tab at the given X position."""
        profile = self._create_male_profile_2d()
        return profile.linear_extrude(height=self.board_t).rotate([0, 0, 90]).translate([
            x_mid - self.peg_width/2,
            self.mid_y,
            0,
        ])
    
    def _create_horz_female_pocket(self, x_mid: float) -> OpenSCAD:
        """Create a horizontal female pocket at the given X position."""
        profile = self._create_female_profile_2d()
        return profile.linear_extrude(height=self.board_t + 2).rotate([0, 0, 90]).translate([
            x_mid - self.peg_width/2 - self.clearance,
            self.mid_y,
            -1,
        ])
    
    def _create_holes_for_tile(self, x1: float, y1: float, x2: float, y2: float) -> List[OpenSCAD]:
        """Create hole cylinders for a specific tile."""
        holes = []
        for hx, hy in self.holes:
            if x1 <= hx <= x2 and y1 <= hy <= y2:
                hole = OpenSCAD.cylinder(h=self.board_t + 2, r=self.hole_r).translate([hx, hy, -1])
                holes.append(hole)
        return holes
    
    def _create_tile(self, x1: float, y1: float, x2: float, y2: float,
                     vert_male: bool, horz_male: bool, color: str) -> OpenSCAD:
        """
        Create a single tile with appropriate jigsaw features.
        
        Args:
            x1, y1, x2, y2: Tile boundaries
            vert_male: True if this tile has male vertical tabs (on RIGHT edge)
            horz_male: True if this tile has male horizontal tabs (on TOP edge)
            color: Color for visualization
        """
        # Base plate
        base = OpenSCAD.cube([x2 - x1, y2 - y1, self.board_t]).translate([x1, y1, 0])
        
        # Add male tabs and female pockets
        male_tabs = []
        subtract_features = []
        
        # Buffer distance from corners to avoid tabs at corners
        corner_buffer = self.peg_width * 1.5  # Must be clear of corners
        
        # Vertical seam processing (left/right edge at x = mid_x)
        # Male tabs stick OUT to the right, female pockets receive from the left
        if vert_male:
            # This tile creates male tabs sticking RIGHT
            for y_mid in self.vert_tab_y:
                # Only create tab if it's within THIS tile's Y range AND not near corners
                # Must be away from both the tile's own corners AND the global board corners
                if (GeometryMath.is_within(y_mid, y1 + corner_buffer, y2 - corner_buffer) and
                    GeometryMath.is_within(y_mid, corner_buffer, self.board_h - corner_buffer)):
                    male_tabs.append(self._create_vert_male_tab(y_mid))
        else:
            # This tile has female pockets receiving from the LEFT
            for y_mid in self.vert_tab_y:
                if (GeometryMath.is_within(y_mid, y1 + corner_buffer, y2 - corner_buffer) and
                    GeometryMath.is_within(y_mid, corner_buffer, self.board_h - corner_buffer)):
                    subtract_features.append(self._create_vert_female_pocket(y_mid))
        
        # Horizontal seam processing (top/bottom edge at y = mid_y)
        # Male tabs stick OUT to the top, female pockets receive from below
        if horz_male:
            # This tile creates male tabs sticking UP
            for x_mid in self.horz_tab_x:
                # Only create tab if it's within THIS tile's X range AND not near corners
                if (GeometryMath.is_within(x_mid, x1 + corner_buffer, x2 - corner_buffer) and
                    GeometryMath.is_within(x_mid, corner_buffer, self.board_w - corner_buffer)):
                    male_tabs.append(self._create_horz_male_tab(x_mid))
        else:
            # This tile has female pockets receiving from BELOW
            for x_mid in self.horz_tab_x:
                if (GeometryMath.is_within(x_mid, x1 + corner_buffer, x2 - corner_buffer) and
                    GeometryMath.is_within(x_mid, corner_buffer, self.board_w - corner_buffer)):
                    subtract_features.append(self._create_horz_female_pocket(x_mid))
        
        # Add holes to subtract
        subtract_features.extend(self._create_holes_for_tile(x1, y1, x2, y2))
        
        # Combine everything
        if male_tabs:
            tile = base.union(*male_tabs)
        else:
            tile = base
        
        if subtract_features:
            tile = tile.difference(*subtract_features)
        
        return tile.color(color)
    
    def generate_tiles(self) -> OpenSCAD:
        """Generate all four tiles in a spaced layout."""
        self._ensure_safe_seams()
        if not self.vert_tab_y or not self.horz_tab_x:
            self.find_safe_tab_positions()

        self._validate_holes_clear_of_seams()
        
        # CRITICAL: Each tile only gets tabs/pockets on the seams it touches
        # Vertical seam at mid_x: Tiles A & C (left) have MALE, Tiles B & D (right) have FEMALE
        # Horizontal seam at mid_y: Tiles A & B (bottom) have MALE, Tiles C & D (top) have FEMALE
        
        # Tile A: bottom-left
        # - Right edge (x=mid_x): male tabs sticking right into B
        # - Top edge (y=mid_y): male tabs sticking up into C
        tile_a = self._create_tile(0, 0, self.mid_x, self.mid_y, 
                                   vert_male=True, horz_male=True, color="red")
        
        # Tile B: bottom-right  
        # - Left edge (x=mid_x): female pockets receiving from A
        # - Top edge (y=mid_y): male tabs sticking up into D
        tile_b = self._create_tile(self.mid_x, 0, self.board_w, self.mid_y,
                                   vert_male=False, horz_male=True, color="green")
        tile_b = tile_b.translate([self.bed_spacing, 0, 0])
        
        # Tile C: top-left
        # - Right edge (x=mid_x): male tabs sticking right into D
        # - Bottom edge (y=mid_y): female pockets receiving from A
        tile_c = self._create_tile(0, self.mid_y, self.mid_x, self.board_h,
                                   vert_male=True, horz_male=False, color="blue")
        tile_c = tile_c.translate([0, self.bed_spacing, 0])
        
        # Tile D: top-right
        # - Left edge (x=mid_x): female pockets receiving from C
        # - Bottom edge (y=mid_y): female pockets receiving from B
        tile_d = self._create_tile(self.mid_x, self.mid_y, self.board_w, self.board_h,
                                   vert_male=False, horz_male=False, color="yellow")
        tile_d = tile_d.translate([self.bed_spacing, self.bed_spacing, 0])
        
        return tile_a + tile_b + tile_c + tile_d
    
    def generate_scad(self) -> str:
        """Generate the complete OpenSCAD code with header comments."""
        if not self.vert_tab_y or not self.horz_tab_x:
            self.find_safe_tab_positions()
        
        header = f"""// Auto-generated jigsaw board split
// Board: {self.board_w} x {self.board_h} x {self.board_t} mm
// Generated with {len(self.holes)} mounting holes
// Vertical tabs at Y: {[f"{y:.1f}" for y in self.vert_tab_y]}
// Horizontal tabs at X: {[f"{x:.1f}" for x in self.horz_tab_x]}

"""
        
        tiles = self.generate_tiles()
        return header + str(tiles)

    def _validate_holes_clear_of_seams(self) -> None:
        """Ensure no mounting hole is bisected by either seam."""
        self._ensure_safe_seams()

        conflicts = []
        tolerance = 1e-6
        for hx, hy in self.holes:
            if abs(hx - self.mid_x) <= self.hole_r + tolerance:
                conflicts.append(
                    f"({hx:.3f}, {hy:.3f}) intersects the vertical seam at x={self.mid_x:.3f}"
                )
            if abs(hy - self.mid_y) <= self.hole_r + tolerance:
                conflicts.append(
                    f"({hx:.3f}, {hy:.3f}) intersects the horizontal seam at y={self.mid_y:.3f}"
                )

        if conflicts:
            message = (
                "Mounting holes are too close to the jigsaw seams; these would be split "
                "across tiles: " + "; ".join(conflicts)
            )
            raise ValueError(message)

    def _ensure_safe_seams(self) -> None:
        """Shift seam positions away from mounting holes if necessary."""

        if getattr(self, "_seams_locked", False):
            return

        self.mid_x = self._find_safe_seam_position(self.mid_x, axis="x")
        self.mid_y = self._find_safe_seam_position(self.mid_y, axis="y")
        self._seams_locked = True

    def _find_safe_seam_position(self, start: float, axis: str) -> float:
        """Return the closest seam location to ``start`` that avoids holes."""

        axis_length = self.board_w if axis == "x" else self.board_h
        coord_index = 0 if axis == "x" else 1
        clearance = self.hole_r + 0.25
        search_step = 0.5
        max_steps = int((axis_length / 2) / search_step) + 2

        def seam_is_clear(candidate: float) -> bool:
            if not GeometryMath.is_within(candidate, clearance, axis_length - clearance):
                return False
            for hole in self.holes:
                if abs(hole[coord_index] - candidate) <= clearance:
                    return False
            return True

        offsets = [0.0]
        for step in range(1, max_steps):
            offsets.append(step * search_step)
            offsets.append(-step * search_step)

        for offset in offsets:
            candidate = start + offset
            if seam_is_clear(candidate):
                return candidate

        seam_name = "vertical" if axis == "x" else "horizontal"
        raise ValueError(
            f"Unable to place a safe {seam_name} seam; all candidate positions intersect mounting holes."
        )
    
    def save_scad(self, filename: str):
        """Save the generated OpenSCAD code to a file."""
        with open(filename, 'w') as f:
            f.write(self.generate_scad())
        logger.info("Generated OpenSCAD file: %s", filename)
        logger.info("Vertical tabs: %d", len(self.vert_tab_y))
        logger.info("Horizontal tabs: %d", len(self.horz_tab_x))


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # microATX board dimensions
    board_width = 243.84
    board_height = 243.84
    board_thickness = 3.0
    
    # Mounting hole positions
    holes = [
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
        [220.455, 83.287]
    ]
    
    # Create generator
    gen = JigsawBoardGenerator(
        board_width=board_width,
        board_height=board_height,
        board_thickness=board_thickness,
        holes=holes,
        hole_radius=1.98
    )
    
    # Auto-find safe tab positions (avoids corners and holes)
    num_vert, num_horz = gen.find_safe_tab_positions(
        num_tabs_per_seam=4,
        min_distance_from_corner=40.0
    )
    logger.info(
        "Auto-found %d vertical tabs and %d horizontal tabs",
        num_vert,
        num_horz,
    )
    
    # Adjust jigsaw parameters for fit
    gen.peg_len = 14.0
    gen.peg_width = 16.0
    gen.peg_radius = 9.0
    gen.clearance = 0.50
    
    # Generate and save
    gen.save_scad("jigsaw_board.scad")
    
    # Or print to console
    # print(gen.generate_scad())
