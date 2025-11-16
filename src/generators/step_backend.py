"""Pure-Python STEP utilities derived from OpenCascade primitives."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

try:  # pragma: no cover - import guard
    from steputils.p21 import Enumeration, Reference, load
except ModuleNotFoundError as exc:  # pragma: no cover - explicit error path
    raise ModuleNotFoundError(
        "STEP tessellation requires the 'steputils' package. Install it via 'pip install steputils'."
    ) from exc

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
        with path.open("r", encoding="utf-8", errors="ignore") as stream:
            step_file = load(stream)
        entities: Dict[str, _Entity] = {}
        for section in step_file.data:
            for ref, instance in getattr(section, "instances", {}).items():
                entity = getattr(instance, "entity", None)
                if entity is None:
                    continue
                entities[ref] = entity
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

    def _vertex_coords(self, vertex_ref: str | Reference) -> Point:
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
    if isinstance(value, Enumeration):
        value = str(value)
    if isinstance(value, str):
        text = value.strip().strip(".").lower()
        if text == "t":
            return True
        if text == "f":
            return False
    return bool(value)


def _as_reference(value: object) -> str:
    if isinstance(value, Reference):
        return str(value)
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


_Entity = object  # Alias for readability; steputils does not expose a stub type.


__all__ = ["StepBackend", "StepSolid"]
