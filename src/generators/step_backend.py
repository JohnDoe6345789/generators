"""Pure-Python STEP utilities derived from OpenCascade primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float, float]
Triangle = Tuple[Point, Point, Point]


@dataclass(slots=True)
class StepSolid:
    """Thin wrapper exposing the tessellated solid volume."""

    name: str
    triangles: List[Triangle]
    volume: float

    def Volume(self) -> float:
        return self.volume


class StepBackend:
    """High level façade for loading and meshing STEP solids without OCP."""

    def load_solids(self, step_path: str | Path) -> List[StepSolid]:
        model = _StepModel.from_file(step_path)
        solids = list(model.iter_solids())
        if not solids:
            raise ValueError(f"Unable to extract solids from STEP file: {step_path}")
        return solids

    def make_compound(self, solids: Sequence[StepSolid]) -> List[StepSolid]:
        return list(solids)

    def tessellate(
        self,
        compound: Sequence[StepSolid],
        angular_tolerance: float,
        linear_tolerance: float,
    ) -> Tuple[List[List[float]], List[List[int]]]:
        vertex_lookup: Dict[Tuple[float, float, float], int] = {}
        vertices: List[List[float]] = []
        faces: List[List[int]] = []

        for solid in compound:
            for tri in solid.triangles:
                indices: List[int] = []
                for coords in tri:
                    key = _rounded(coords)
                    if key not in vertex_lookup:
                        vertex_lookup[key] = len(vertices)
                        vertices.append([coords[0], coords[1], coords[2]])
                    indices.append(vertex_lookup[key])
                if len({indices[0], indices[1], indices[2]}) == 3:
                    faces.append(indices)

        return vertices, faces

    @staticmethod
    def _solid_volume(triangles: Iterable[Triangle]) -> float:
        volume = 0.0
        for tri in triangles:
            volume += _signed_tetra_volume(tri)
        return abs(volume)


class _StepModel:
    """Helper that indexes STEP entities and exposes solid iterators."""

    def __init__(self, entities: Dict[str, _Entity]) -> None:
        self._entities = entities

    @classmethod
    def from_file(cls, step_path: str | Path) -> "_StepModel":
        path = Path(step_path)
        entities = _load_step_entities(path)
        return cls(entities)

    def iter_solids(self) -> Iterable[StepSolid]:
        for ref, entity in self._entities.items():
            if entity.name != "MANIFOLD_SOLID_BREP":
                continue
            name = entity.params[0] or ref
            shell_ref = _as_reference(entity.params[1])
            polygons = self._shell_polygons(shell_ref)
            triangles: List[Triangle] = []
            for polygon in polygons:
                triangles.extend(_triangulate(polygon))
            if not triangles:
                continue
            volume = StepBackend._solid_volume(triangles)
            yield StepSolid(name=name, triangles=triangles, volume=volume)

    def _shell_polygons(self, shell_ref: str) -> List[List[Point]]:
        shell = self._entity(shell_ref)
        if shell.name != "CLOSED_SHELL":
            return []
        face_refs = _as_references(shell.params[1])
        polygons: List[List[Point]] = []
        for face_ref in face_refs:
            polygons.extend(self._face_polygons(face_ref))
        return polygons

    def _face_polygons(self, face_ref: str) -> List[List[Point]]:
        face = self._entity(face_ref)
        if face.name != "ADVANCED_FACE":
            return []
        bound_refs = _as_references(face.params[1])
        polygons: List[List[Point]] = []
        for bound_ref in bound_refs:
            bound = self._entity(bound_ref)
            if bound.name not in {"FACE_BOUND", "FACE_OUTER_BOUND"}:
                continue
            if len(bound.params) < 2:
                continue
            if len(bound.params) == 3 and not _as_bool(bound.params[2]):
                # Ignore inner loops for now to keep the tessellation simple.
                continue
            loop_ref = _as_reference(bound.params[1])
            loop_points = self._loop_points(loop_ref)
            if len(loop_points) >= 3:
                polygons.append(loop_points)
        return polygons

    def _loop_points(self, loop_ref: str) -> List[Point]:
        loop = self._entity(loop_ref)
        if loop.name != "EDGE_LOOP":
            return []
        oriented_refs = _as_references(loop.params[1])
        points: List[Point] = []
        for oriented_ref in oriented_refs:
            start, end = self._edge_points(oriented_ref)
            if not points:
                points.append(start)
            else:
                if not _points_close(points[-1], start):
                    if _points_close(points[-1], end):
                        start, end = end, start
                    else:
                        points.append(start)
                if _points_close(points[0], end) and len(points) > 2:
                    continue
            points.append(end)
        if len(points) > 2 and _points_close(points[0], points[-1]):
            points.pop()
        return points

    def _edge_points(self, oriented_ref: str) -> Tuple[Point, Point]:
        oriented = self._entity(oriented_ref)
        if oriented.name != "ORIENTED_EDGE":
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        curve_ref = _as_reference(oriented.params[3])
        curve = self._entity(curve_ref)
        if curve.name != "EDGE_CURVE":
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        start = self._vertex_coords(curve.params[1])
        end = self._vertex_coords(curve.params[2])
        if not _as_bool(oriented.params[4]):
            start, end = end, start
        return start, end

    def _vertex_coords(self, vertex_ref: object) -> Point:
        vertex = self._entity(_as_reference(vertex_ref))
        if vertex.name != "VERTEX_POINT":
            return (0.0, 0.0, 0.0)
        point = self._entity(_as_reference(vertex.params[1]))
        if point.name != "CARTESIAN_POINT":
            return (0.0, 0.0, 0.0)
        coords = point.params[1]
        return (float(coords[0]), float(coords[1]), float(coords[2]))

    def _entity(self, ref: str) -> _Entity:
        entity = self._entities.get(ref)
        if entity is None:
            raise KeyError(f"Missing STEP entity: {ref}")
        return entity


def _triangulate(points: List[Point]) -> List[Triangle]:
    if len(points) < 3:
        return []
    anchor = points[0]
    triangles: List[Triangle] = []
    for idx in range(1, len(points) - 1):
        triangle = (anchor, points[idx], points[idx + 1])
        if _triangle_area(triangle) > 1e-9:
            triangles.append(triangle)
    return triangles


def _triangle_area(triangle: Triangle) -> float:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    ab = (bx - ax, by - ay, bz - az)
    ac = (cx - ax, cy - ay, cz - az)
    cross_x = ab[1] * ac[2] - ab[2] * ac[1]
    cross_y = ab[2] * ac[0] - ab[0] * ac[2]
    cross_z = ab[0] * ac[1] - ab[1] * ac[0]
    return 0.5 * (cross_x**2 + cross_y**2 + cross_z**2) ** 0.5


def _signed_tetra_volume(triangle: Triangle) -> float:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    volume = (
        ax * (by * cz - bz * cy)
        - ay * (bx * cz - bz * cx)
        + az * (bx * cy - by * cx)
    ) / 6.0
    return volume


def _rounded(point: Point, digits: int = 9) -> Tuple[float, float, float]:
    return (round(point[0], digits), round(point[1], digits), round(point[2], digits))


def _points_close(a: Point, b: Point, tol: float = 1e-6) -> bool:
    return isclose(a[0], b[0], abs_tol=tol) and isclose(a[1], b[1], abs_tol=tol) and isclose(a[2], b[2], abs_tol=tol)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().strip(".").lower()
        if text == "t":
            return True
        if text == "f":
            return False
    return bool(value)


def _as_reference(value: object) -> str:
    if isinstance(value, str):
        return value
    raise TypeError(f"Unsupported reference type: {type(value)!r}")


def _as_references(value: object) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [_as_reference(item) for item in value]
    try:
        return [_as_reference(item) for item in list(value)]
    except TypeError:
        return [_as_reference(value)]


@dataclass(slots=True)
class _Entity:
    """Representation of a STEP entity declaration."""

    name: str
    params: List[object]


def _load_step_entities(path: Path) -> Dict[str, _Entity]:
    """Load and parse STEP entities from the provided file path."""

    text = path.read_text(encoding="utf-8", errors="ignore")
    return _parse_step_data(text)


def _parse_step_data(text: str) -> Dict[str, _Entity]:
    """Parse all DATA sections of a STEP file into entity mappings."""

    cleaned = _COMMENT_RE.sub(" ", text)
    upper = cleaned.upper()
    sections: List[str] = []
    start = 0
    while True:
        data_idx = upper.find("DATA;", start)
        if data_idx == -1:
            break
        data_idx += len("DATA;")
        end_idx = upper.find("ENDSEC;", data_idx)
        if end_idx == -1:
            body = cleaned[data_idx:]
            start = len(cleaned)
        else:
            body = cleaned[data_idx:end_idx]
            start = end_idx + len("ENDSEC;")
        sections.append(body)

    entities: Dict[str, _Entity] = {}
    for section in sections:
        for statement in _split_statements(section):
            parsed = _parse_entity(statement)
            if parsed is None:
                continue
            ref, entity = parsed
            entities[ref] = entity
    return entities


def _split_statements(section: str) -> Iterable[str]:
    """Yield STEP statements separated by top-level semicolons."""

    statements: List[str] = []
    depth = 0
    in_string = False
    start = 0
    idx = 0
    length = len(section)
    while idx < length:
        char = section[idx]
        if char == "'":
            if in_string and idx + 1 < length and section[idx + 1] == "'":
                idx += 2
                continue
            in_string = not in_string
            idx += 1
            continue
        if in_string:
            idx += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == ";" and depth == 0:
            statement = section[start:idx].strip()
            if statement:
                statements.append(statement)
            start = idx + 1
        idx += 1
    return statements


def _parse_entity(statement: str) -> Optional[Tuple[str, _Entity]]:
    """Parse a single entity assignment line."""

    if not statement.startswith("#"):
        return None
    eq_index = statement.find("=")
    if eq_index == -1:
        return None
    ref = statement[:eq_index].strip()
    body = statement[eq_index + 1 :].strip()
    paren_index = body.find("(")
    if paren_index == -1 or not body.endswith(")"):
        return None
    name = body[:paren_index].strip().upper()
    params_text = body[paren_index + 1 : -1]
    params = _parse_parameter_list(params_text)
    return ref, _Entity(name=name, params=params)


def _parse_parameter_list(text: str) -> List[object]:
    """Parse a comma-delimited parameter list."""

    params: List[object] = []
    idx = 0
    length = len(text)
    while True:
        idx = _skip_ws(text, idx)
        if idx >= length:
            break
        value, idx = _parse_value(text, idx)
        params.append(value)
        idx = _skip_ws(text, idx)
        if idx < length and text[idx] == ",":
            idx += 1
            continue
        break
    return params


def _parse_value(text: str, idx: int) -> Tuple[object, int]:
    """Parse a single STEP value and return the new cursor index."""

    idx = _skip_ws(text, idx)
    if idx >= len(text):
        return "", idx
    char = text[idx]
    if char == "(":
        items: List[object] = []
        idx += 1
        while True:
            idx = _skip_ws(text, idx)
            if idx >= len(text):
                break
            if text[idx] == ")":
                idx += 1
                break
            item, idx = _parse_value(text, idx)
            items.append(item)
            idx = _skip_ws(text, idx)
            if idx < len(text) and text[idx] == ",":
                idx += 1
                continue
            if idx < len(text) and text[idx] == ")":
                idx += 1
                break
        return items, idx
    if char == "'":
        idx += 1
        buffer: List[str] = []
        while idx < len(text):
            current = text[idx]
            if current == "'":
                if idx + 1 < len(text) and text[idx + 1] == "'":
                    buffer.append("'")
                    idx += 2
                    continue
                idx += 1
                break
            buffer.append(current)
            idx += 1
        return "".join(buffer), idx
    if char == "#":
        idx += 1
        start = idx
        while idx < len(text) and text[idx].isdigit():
            idx += 1
        return f"#{text[start:idx]}", idx
    if char == ".":
        idx += 1
        start = idx
        while idx < len(text) and text[idx] != ".":
            idx += 1
        enum_value = text[start:idx].upper()
        if idx < len(text) and text[idx] == ".":
            idx += 1
        return enum_value, idx
    if char in "+-" or char.isdigit() or char == ".":
        match = _NUMBER_RE.match(text, idx)
        if match:
            number = match.group(0).replace("d", "e").replace("D", "E")
            idx = match.end()
            return float(number), idx
    if char == "$" or char == "*":
        return None, idx + 1
    match = _IDENTIFIER_RE.match(text, idx)
    if match:
        word = match.group(0)
        idx = match.end()
        upper = word.upper()
        if upper == "TRUE":
            return True, idx
        if upper == "FALSE":
            return False, idx
        return upper, idx
    return "", idx + 1


def _skip_ws(text: str, idx: int) -> int:
    while idx < len(text) and text[idx].isspace():
        idx += 1
    return idx


_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[EeDd][+-]?\d+)?")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")


__all__ = ["StepBackend", "StepSolid"]
