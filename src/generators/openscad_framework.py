"""Reusable OpenSCAD utilities shared across generators."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple


def beautify_scad_code(code: str, indent: str = "    ") -> str:
    """Return a consistently indented representation of ``code``."""

    formatted_lines: List[str] = []
    level = 0

    for raw_line in code.splitlines():
        stripped = raw_line.strip()

        if not stripped:
            formatted_lines.append("")
            continue

        line_level = level
        if stripped.startswith("}"):
            line_level = max(line_level - 1, 0)
            level = line_level

        formatted_lines.append(f"{indent * line_level}{stripped}")

        if stripped.endswith("{"):
            level += 1

    return "\n".join(formatted_lines)


class OpenSCAD:
    """Main class for building OpenSCAD objects with chainable operations."""

    def __init__(self, code: str = "") -> None:
        self.code = code

    def __str__(self) -> str:
        return self.code

    def __add__(self, other: "OpenSCAD") -> "OpenSCAD":
        return OpenSCAD(f"{self.code}\n{other.code}")

    @staticmethod
    def _format_size(size: Sequence[float] | float) -> str:
        if isinstance(size, (list, tuple)):
            return "[" + ",".join(map(str, size)) + "]"
        return str(size)

    @staticmethod
    def cube(size: Sequence[float] | float, center: bool = False) -> "OpenSCAD":
        s = OpenSCAD._format_size(size)
        c = "true" if center else "false"
        return OpenSCAD(f"cube({s}, center={c});")

    @staticmethod
    def cylinder(
        h: float,
        r: float | None = None,
        d: float | None = None,
        center: bool = False,
    ) -> "OpenSCAD":
        params: List[str] = [f"h={h}"]
        if r is not None:
            params.append(f"r={r}")
        elif d is not None:
            params.append(f"d={d}")
        if center:
            params.append("center=true")
        params.append("$fn=64")
        return OpenSCAD(f"cylinder({', '.join(params)});")

    @staticmethod
    def circle(r: float | None = None, d: float | None = None, fn: int = 48) -> "OpenSCAD":
        if r is not None:
            return OpenSCAD(f"circle(r={r}, $fn={fn});")
        return OpenSCAD(f"circle(d={d}, $fn={fn});")

    @staticmethod
    def square(size: Sequence[float] | float, center: bool = False) -> "OpenSCAD":
        s = OpenSCAD._format_size(size)
        c = "true" if center else "false"
        return OpenSCAD(f"square({s}, center={c});")

    @staticmethod
    def polygon(points: Iterable[Sequence[float]]) -> "OpenSCAD":
        pts = "[" + ",".join(f"[{','.join(map(str, p))}]" for p in points) + "]"
        return OpenSCAD(f"polygon(points={pts});")

    def translate(self, v: Sequence[float]) -> "OpenSCAD":
        vec = f"[{','.join(map(str, v))}]"
        return OpenSCAD(f"translate({vec}) {{\n{self.code}\n}}")

    def rotate(
        self,
        a: Sequence[float] | float,
        v: Sequence[float] | None = None,
    ) -> "OpenSCAD":
        if v is None:
            if isinstance(a, (list, tuple)):
                ang = f"[{','.join(map(str, a))}]"
            else:
                ang = str(a)
            return OpenSCAD(f"rotate({ang}) {{\n{self.code}\n}}")

        vec = f"[{','.join(map(str, v))}]"
        return OpenSCAD(f"rotate(a={a}, v={vec}) {{\n{self.code}\n}}")

    def color(self, c: Sequence[float] | str) -> "OpenSCAD":
        if isinstance(c, str):
            col = f'"{c}"'
        else:
            col = f"[{','.join(map(str, c))}]"
        return OpenSCAD(f"color({col}) {{\n{self.code}\n}}")

    def union(self, *others: "OpenSCAD") -> "OpenSCAD":
        objects = [self] + list(others)
        combined = "\n".join(obj.code for obj in objects)
        return OpenSCAD(f"union() {{\n{combined}\n}}")

    def difference(self, *others: "OpenSCAD") -> "OpenSCAD":
        objects = [self] + list(others)
        combined = "\n".join(obj.code for obj in objects)
        return OpenSCAD(f"difference() {{\n{combined}\n}}")

    def hull(self, *others: "OpenSCAD") -> "OpenSCAD":
        if others:
            objects = [self] + list(others)
            combined = "\n".join(obj.code for obj in objects)
            return OpenSCAD(f"hull() {{\n{combined}\n}}")
        return OpenSCAD(f"hull() {{\n{self.code}\n}}")

    def linear_extrude(
        self,
        height: float,
        center: bool = False,
        twist: float = 0,
        scale: float = 1,
    ) -> "OpenSCAD":
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
    def is_within(
        value: float,
        lower: float,
        upper: float,
        inclusive: bool = False,
    ) -> bool:
        """Return True if ``value`` lies within the provided bounds."""

        if inclusive:
            return lower <= value <= upper
        return lower < value < upper


__all__ = ["beautify_scad_code", "GeometryMath", "OpenSCAD"]

