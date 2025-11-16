"""Reusable OpenSCAD utilities shared across generators."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    @staticmethod
    def module_call(name: str, args: Sequence[object] | None = None) -> "OpenSCAD":
        """Return an ``OpenSCAD`` object that invokes ``name`` with ``args``."""

        if args:
            arg_str = ", ".join(map(str, args))
            return OpenSCAD(f"{name}({arg_str});")
        return OpenSCAD(f"{name}();")


@dataclass
class OpenSCADModule:
    """Container describing an OpenSCAD module definition."""

    name: str
    body: OpenSCAD
    args: Sequence[str] = field(default_factory=list)

    def render(self) -> str:
        signature = f"module {self.name}({', '.join(self.args)})" if self.args else f"module {self.name}()"
        return f"{signature} {{\n{self.body.code}\n}}"


class OpenSCADScript:
    """High level helper for procedurally generating OpenSCAD files."""

    def __init__(self) -> None:
        self._headers: List[str] = []
        self._functions: List[str] = []
        self._modules: List[OpenSCADModule] = []
        self._body: List[str] = []

    def add_header(self, text: str) -> None:
        """Append ``text`` to the comment header block."""

        cleaned = text.strip()
        if cleaned:
            self._headers.append(cleaned)

    def define_function(
        self,
        name: str,
        expression: object,
        args: Sequence[str] | None = None,
    ) -> None:
        """Register an OpenSCAD function definition."""

        args_repr = f"({', '.join(args)})" if args else "()"
        expr_repr = self._format_expression(expression)
        self._functions.append(f"function {name}{args_repr} = {expr_repr};")

    def define_module(
        self,
        name: str,
        body: OpenSCAD,
        args: Sequence[str] | None = None,
    ) -> None:
        """Register a module definition backed by ``body``."""

        module = OpenSCADModule(name=name, body=body, args=list(args or []))
        self._modules.append(module)

    def add_body(self, snippet: OpenSCAD | str) -> None:
        """Append a raw code ``snippet`` to the main body."""

        if isinstance(snippet, OpenSCAD):
            self._body.append(snippet.code)
        else:
            self._body.append(snippet)

    def render(self) -> str:
        """Return the fully assembled OpenSCAD document."""

        sections: List[str] = []
        if self._headers:
            sections.append("\n".join(self._headers))
        if self._functions:
            sections.append("\n".join(self._functions))
        if self._modules:
            sections.append("\n\n".join(module.render() for module in self._modules))
        if self._body:
            sections.append("\n".join(self._body))
        return beautify_scad_code("\n\n".join(filter(None, sections)))

    @staticmethod
    def _format_expression(expression: object) -> str:
        if isinstance(expression, OpenSCAD):
            return expression.code
        if isinstance(expression, (list, tuple)):
            return "[" + ",".join(map(str, expression)) + "]"
        return str(expression)


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


__all__ = [
    "GeometryMath",
    "OpenSCAD",
    "OpenSCADModule",
    "OpenSCADScript",
    "beautify_scad_code",
]

