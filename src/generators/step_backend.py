"""In-house STEP utilities derived from OpenCascade primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import List, Sequence, Tuple

_OCP: SimpleNamespace | None = None
_OCP_ERROR: ModuleNotFoundError | None = None


def _require_ocp() -> SimpleNamespace:
    """Return cached OpenCascade bindings, importing them on demand."""

    global _OCP, _OCP_ERROR
    if _OCP is not None:
        return _OCP
    if _OCP_ERROR is not None:
        raise ModuleNotFoundError(
            "STEP tessellation requires the 'OCP' package. Install it via 'pip install OCP'."
        ) from _OCP_ERROR
    try:  # pragma: no cover - exercised through downstream helpers
        from OCP.BRep import BRep_Builder, BRep_Tool
        from OCP.BRepGProp import brepgprop_VolumeProperties
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.GProp import GProp_GProps
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Poly import Poly_Triangle
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape, topods_Face, topods_Solid
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        _OCP_ERROR = exc
        raise ModuleNotFoundError(
            "STEP tessellation requires the 'OCP' package. Install it via 'pip install OCP'."
        ) from exc

    _OCP = SimpleNamespace(
        BRep_Builder=BRep_Builder,
        BRepMesh_IncrementalMesh=BRepMesh_IncrementalMesh,
        BRep_Tool=BRep_Tool,
        IFSelect_RetDone=IFSelect_RetDone,
        Poly_Triangle=Poly_Triangle,
        STEPControl_Reader=STEPControl_Reader,
        TopAbs_FACE=TopAbs_FACE,
        TopAbs_SOLID=TopAbs_SOLID,
        TopExp_Explorer=TopExp_Explorer,
        TopLoc_Location=TopLoc_Location,
        TopoDS_Compound=TopoDS_Compound,
        TopoDS_Shape=TopoDS_Shape,
        brepgprop_VolumeProperties=brepgprop_VolumeProperties,
        topods_Face=topods_Face,
        topods_Solid=topods_Solid,
        GProp_GProps=GProp_GProps,
    )
    return _OCP


@dataclass(slots=True)
class StepSolid:
    """Thin wrapper exposing the solid volume."""

    shape: "TopoDS_Shape"
    volume: float

    def Volume(self) -> float:
        return self.volume


class StepBackend:
    """High level façade for loading and meshing STEP solids."""

    def load_solids(self, step_path: str | Path) -> List[StepSolid]:
        modules = _require_ocp()
        reader = modules.STEPControl_Reader()
        status = reader.ReadFile(str(step_path))
        if status != modules.IFSelect_RetDone:
            raise ValueError(f"Unable to load STEP file: {step_path}")

        for root in range(1, reader.NbRootsForTransfer() + 1):
            reader.TransferRoot(root)

        solids: List[StepSolid] = []
        for index in range(1, reader.NbShapes() + 1):
            shape = reader.Shape(index)
            explorer = modules.TopExp_Explorer(shape, modules.TopAbs_SOLID)
            while explorer.More():
                solid = modules.topods_Solid(explorer.Current())
                volume = self._solid_volume(solid)
                solids.append(StepSolid(shape=solid, volume=volume))
                explorer.Next()
        return solids

    def make_compound(self, solids: Sequence[StepSolid]):
        modules = _require_ocp()
        builder = modules.BRep_Builder()
        compound = modules.TopoDS_Compound()
        builder.MakeCompound(compound)
        for solid in solids:
            builder.Add(compound, solid.shape)
        return compound

    def tessellate(
        self,
        compound,
        angular_tolerance: float,
        linear_tolerance: float,
    ) -> Tuple[List[List[float]], List[List[int]]]:
        modules = _require_ocp()
        modules.BRepMesh_IncrementalMesh(compound, linear_tolerance, False, angular_tolerance, True)

        explorer = modules.TopExp_Explorer(compound, modules.TopAbs_FACE)
        vertex_lookup: dict[Tuple[float, float, float], int] = {}
        vertices: List[List[float]] = []
        faces: List[List[int]] = []

        while explorer.More():
            face = modules.topods_Face(explorer.Current())
            loc = modules.TopLoc_Location()
            triangulation = modules.BRep_Tool.Triangulation(face, loc)
            explorer.Next()
            if triangulation is None:
                continue

            transform = loc.Transformation()
            node_indices = [0] * (triangulation.NbNodes() + 1)
            nodes = triangulation.Nodes()
            for idx in range(1, triangulation.NbNodes() + 1):
                point = nodes.Value(idx).Transformed(transform)
                coords = (point.X(), point.Y(), point.Z())
                key = (round(coords[0], 9), round(coords[1], 9), round(coords[2], 9))
                if key not in vertex_lookup:
                    vertex_lookup[key] = len(vertices)
                    vertices.append([coords[0], coords[1], coords[2]])
                node_indices[idx] = vertex_lookup[key]

            triangles = triangulation.Triangles()
            for idx in range(1, triangulation.NbTriangles() + 1):
                tri: Poly_Triangle = triangles.Value(idx)
                a, b, c = tri.Get()
                faces.append([node_indices[a], node_indices[b], node_indices[c]])

        return vertices, faces

    @staticmethod
    def _solid_volume(shape) -> float:
        modules = _require_ocp()
        props = modules.GProp_GProps()
        modules.brepgprop_VolumeProperties(shape, props)
        return float(props.Mass())


__all__ = ["StepBackend", "StepSolid"]
