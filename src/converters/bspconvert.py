#!/usr/bin/env python3
"""
Half-Life 2 BSP → STL converter (simplified) with logging and progress bar.

This script reads a Source-engine BSP (e.g. Half-Life 2 / Episode Two) and
writes out a static STL mesh of world geometry (brush faces). It focuses on
lump data for vertices, edges, surfedges and faces and exports those as
triangles.

Notes / limitations:
- Targets Source BSP version 20 (HL2-era). Other versions may fail.
- Only exports world geometry (not models, props, or displacements).
- Ignores textures, lightmaps, materials – geometry only.
- Treats each polygon face as a triangle fan from vertex 0.
- Very lightweight parser: not all lumps or flags are used.
- Designed as a starting point for tinkering, not a production tool.

Logging:
- Uses Python's logging module.
- Logs high-level steps at INFO level.
- Debug logging can be enabled with --debug.

Progress bar:
- Shows a simple text progress bar for face→triangle conversion
  on stderr.
- Can be disabled with --no-progress.

Usage:
    python bsp_to_stl.py input_map.bsp output_mesh.stl
    python bsp_to_stl.py --debug input_map.bsp output_mesh.stl
"""

import argparse
import logging
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, BinaryIO, Iterable


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Basic data structures
# ---------------------------------------------------------------------------


@dataclass
class LumpInfo:
    offset: int
    length: int
    version: int
    four_cc: int


@dataclass
class BSPHeader:
    ident: bytes
    version: int
    lumps: List[LumpInfo]
    revision: int


@dataclass
class Face:
    plane_num: int
    side: int
    on_node: int
    first_edge: int
    num_edges: int
    texinfo: int
    dispinfo: int
    surface_fog_volume_id: int
    style: Tuple[int, int, int, int]
    lightofs: int
    area: float
    lightmap_mins_x: int
    lightmap_mins_y: int
    lightmap_size_x: int
    lightmap_size_y: int
    orig_face: int
    num_prims: int
    first_prim_id: int
    smoothing_groups: int


# ---------------------------------------------------------------------------
# BSP parsing
# ---------------------------------------------------------------------------


BSP_IDENT = b"VBSP"
NUM_LUMPS = 64

# LUMP indices for Source BSP v20 (HL2)
LUMP_VERTICES = 3
LUMP_EDGES = 12
LUMP_SURFEDGES = 13
LUMP_FACES = 7


def read_header(f: BinaryIO) -> BSPHeader:
    header_struct = struct.Struct("<4s i")
    data = f.read(header_struct.size)
    if len(data) != header_struct.size:
        raise ValueError("Failed to read BSP header ident/version")

    ident, version = header_struct.unpack(data)
    if ident != BSP_IDENT:
        raise ValueError(f"Not a Source BSP (ident={ident!r})")
    if version != 20:
        logger.warning(
            "BSP version %s (expected 20 for HL2). "
            "Script may still work but is not guaranteed.",
            version,
        )

    lumps: List[LumpInfo] = []
    lump_struct = struct.Struct("<iiii")
    for _ in range(NUM_LUMPS):
        data = f.read(lump_struct.size)
        if len(data) != lump_struct.size:
            raise ValueError("Failed to read lump directory")
        offset, length, version_l, four_cc = lump_struct.unpack(data)
        lumps.append(
            LumpInfo(
                offset=offset,
                length=length,
                version=version_l,
                four_cc=four_cc,
            )
        )

    revision_struct = struct.Struct("<i")
    rev_data = f.read(revision_struct.size)
    if len(rev_data) != revision_struct.size:
        raise ValueError("Failed to read BSP revision")
    (revision,) = revision_struct.unpack(rev_data)

    logger.info(
        "Read BSP header: ident=%s, version=%d, revision=%d",
        ident.decode("ascii", errors="replace"),
        version,
        revision,
    )
    return BSPHeader(ident=ident, version=version, lumps=lumps, revision=revision)


def read_vertices(f: BinaryIO, header: BSPHeader) -> List[Tuple[float, float, float]]:
    lump = header.lumps[LUMP_VERTICES]
    f.seek(lump.offset)
    vert_struct = struct.Struct("<fff")
    count = lump.length // vert_struct.size
    logger.info("Reading %d vertices...", count)
    vertices: List[Tuple[float, float, float]] = []
    for _ in range(count):
        data = f.read(vert_struct.size)
        if len(data) != vert_struct.size:
            raise ValueError("Failed to read vertex")
        vertices.append(vert_struct.unpack(data))
    logger.debug("First vertex: %s", vertices[0] if vertices else None)
    return vertices


def read_edges(f: BinaryIO, header: BSPHeader) -> List[Tuple[int, int]]:
    lump = header.lumps[LUMP_EDGES]
    f.seek(lump.offset)
    edge_struct = struct.Struct("<HH")
    count = lump.length // edge_struct.size
    logger.info("Reading %d edges...", count)
    edges: List[Tuple[int, int]] = []
    for _ in range(count):
        data = f.read(edge_struct.size)
        if len(data) != edge_struct.size:
            raise ValueError("Failed to read edge")
        v0, v1 = edge_struct.unpack(data)
        edges.append((v0, v1))
    return edges


def read_surfedges(f: BinaryIO, header: BSPHeader) -> List[int]:
    lump = header.lumps[LUMP_SURFEDGES]
    f.seek(lump.offset)
    surfedge_struct = struct.Struct("<i")
    count = lump.length // surfedge_struct.size
    logger.info("Reading %d surfedges...", count)
    surfedges: List[int] = []
    for _ in range(count):
        data = f.read(surfedge_struct.size)
        if len(data) != surfedge_struct.size:
            raise ValueError("Failed to read surfedge")
        (idx,) = surfedge_struct.unpack(data)
        surfedges.append(idx)
    return surfedges


def read_faces(f: BinaryIO, header: BSPHeader) -> List[Face]:
    """
    Read dface_t array (56 bytes per face, Source BSP v20 layout).
    """
    lump = header.lumps[LUMP_FACES]
    f.seek(lump.offset)

    # struct dface_t from Valve dev wiki:
    #
    # unsigned short  planenum;
    # byte            side;
    # byte            onNode;
    # int             firstedge;
    # short           numedges;
    # short           texinfo;
    # short           dispinfo;
    # short           surfaceFogVolumeID;
    # byte            styles[4];
    # int             lightofs;
    # float           area;
    # int             LightmapTextureMinsInLuxels[2];
    # int             LightmapTextureSizeInLuxels[2];
    # int             origFace;
    # unsigned short  numPrims;
    # unsigned short  firstPrimID;
    # unsigned int    smoothingGroups;
    #
    # Total: 56 bytes.
    #
    face_struct = struct.Struct("<HBBihhhh4bif2i2iiHHI")

    count = lump.length // face_struct.size
    logger.info("Reading %d faces...", count)

    faces: List[Face] = []
    for _ in range(count):
        data = f.read(face_struct.size)
        if len(data) != face_struct.size:
            raise ValueError("Failed to read face")

        unpacked = face_struct.unpack(data)
        (
            plane_num,
            side,
            on_node,
            first_edge,
            num_edges,
            texinfo,
            dispinfo,
            surface_fog_volume_id,
            style0,
            style1,
            style2,
            style3,
            lightofs,
            area,
            lm_mins_x,
            lm_mins_y,
            lm_size_x,
            lm_size_y,
            orig_face,
            num_prims,
            first_prim_id,
            smoothing_groups,
        ) = unpacked

        faces.append(
            Face(
                plane_num=plane_num,
                side=side,
                on_node=on_node,
                first_edge=first_edge,
                num_edges=num_edges,
                texinfo=texinfo,
                dispinfo=dispinfo,
                surface_fog_volume_id=surface_fog_volume_id,
                style=(style0, style1, style2, style3),
                lightofs=lightofs,
                area=area,
                lightmap_mins_x=lm_mins_x,
                lightmap_mins_y=lm_mins_y,
                lightmap_size_x=lm_size_x,
                lightmap_size_y=lm_size_y,
                orig_face=orig_face,
                num_prims=num_prims,
                first_prim_id=first_prim_id,
                smoothing_groups=smoothing_groups,
            )
        )
    return faces


# ---------------------------------------------------------------------------
# Mesh construction
# ---------------------------------------------------------------------------


def build_face_vertices(
    face: Face,
    vertices: List[Tuple[float, float, float]],
    edges: List[Tuple[int, int]],
    surfedges: List[int],
) -> List[Tuple[float, float, float]]:
    result: List[Tuple[float, float, float]] = []
    for i in range(face.num_edges):
        surfedge_index = surfedges[face.first_edge + i]
        if surfedge_index >= 0:
            edge = edges[surfedge_index]
            v_index = edge[0]
        else:
            edge = edges[-surfedge_index]
            v_index = edge[1]
        result.append(vertices[v_index])
    return result


def triangulate_polygon(
    verts: List[Tuple[float, float, float]]
) -> Iterable[Tuple[Tuple[float, float, float], ...]]:
    if len(verts) < 3:
        return []

    tris: List[Tuple[Tuple[float, float, float], ...]] = []
    v0 = verts[0]
    for i in range(1, len(verts) - 1):
        v1 = verts[i]
        v2 = verts[i + 1]
        tris.append((v0, v1, v2))
    return tris


def _print_progress(
    current: int,
    total: int,
    width: int = 40,
) -> None:
    """
    Render a simple progress bar to stderr without disrupting logging output.
    """
    if total <= 0:
        return
    ratio = min(max(float(current) / float(total), 0.0), 1.0)
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    percent = ratio * 100.0
    msg = f"\r[{bar}] {percent:5.1f}% ({current}/{total})"
    sys.stderr.write(msg)
    sys.stderr.flush()


def build_triangles(
    vertices: List[Tuple[float, float, float]],
    edges: List[Tuple[int, int]],
    surfedges: List[int],
    faces: List[Face],
    show_progress: bool = True,
) -> List[Tuple[Tuple[float, float, float], ...]]:
    logger.info(
        "Building triangles from %d faces (displacements skipped)...",
        len(faces),
    )

    triangles: List[Tuple[Tuple[float, float, float], ...]] = []
    total_faces = len(faces)
    if total_faces == 0:
        return triangles

    step = max(1, total_faces // 200)

    processed = 0
    for idx, face in enumerate(faces):
        if face.num_edges < 3:
            continue
        if face.dispinfo != -1:
            continue

        poly_verts = build_face_vertices(face, vertices, edges, surfedges)
        tris = triangulate_polygon(poly_verts)
        triangles.extend(tris)

        processed += 1
        if show_progress and (idx % step == 0 or idx == total_faces - 1):
            _print_progress(idx + 1, total_faces)

    if show_progress:
        sys.stderr.write("\n")

    logger.info("Generated %d triangles.", len(triangles))
    return triangles


# ---------------------------------------------------------------------------
# STL writer
# ---------------------------------------------------------------------------


def compute_normal(
    v0: Tuple[float, float, float],
    v1: Tuple[float, float, float],
    v2: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    ax = v1[0] - v0[0]
    ay = v1[1] - v0[1]
    az = v1[2] - v0[2]
    bx = v2[0] - v0[0]
    by = v2[1] - v0[1]
    bz = v2[2] - v0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length == 0.0:
        return 0.0, 0.0, 0.0
    return nx / length, ny / length, nz / length


def write_binary_stl(
    path: Path,
    triangles: List[Tuple[Tuple[float, float, float], ...]],
) -> None:
    logger.info("Writing STL with %d triangles to %s", len(triangles), path)
    with path.open("wb") as f:
        header_text = "HL2 BSP to STL"
        header = header_text.encode("ascii") + b" " * (80 - len(header_text))
        f.write(header)
        f.write(struct.pack("<I", len(triangles)))
        for tri in triangles:
            v0, v1, v2 = tri
            normal = compute_normal(v0, v1, v2)
            f.write(struct.pack("<fff", *normal))
            f.write(struct.pack("<fff", *v0))
            f.write(struct.pack("<fff", *v1))
            f.write(struct.pack("<fff", *v2))
            f.write(struct.pack("<H", 0))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Half-Life 2 BSP (Source) to STL mesh."
    )
    parser.add_argument("input_bsp", type=Path, help="Path to input .bsp file")
    parser.add_argument(
        "output_stl",
        type=str,
        help=(
            "Output STL filename (will be placed in bsp_to_stl_output/ "
            "to avoid modifying current folder)"
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable face processing progress bar.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )
    logger.debug("Debug logging enabled.")


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    configure_logging(args.debug)

    if not args.input_bsp.is_file():
        logger.error("Input BSP not found: %s", args.input_bsp)
        return 1

    output_dir = Path.cwd() / "bsp_to_stl_output"
    output_dir.mkdir(exist_ok=True)
    out_path = output_dir / args.output_stl

    logger.info("Input BSP: %s", args.input_bsp)
    logger.info("Output STL: %s", out_path)
    logger.info("Output directory ensured: %s", output_dir)

    with args.input_bsp.open("rb") as f:
        header = read_header(f)
        vertices = read_vertices(f, header)
        edges = read_edges(f, header)
        surfedges = read_surfedges(f, header)
        faces = read_faces(f, header)

    triangles = build_triangles(
        vertices,
        edges,
        surfedges,
        faces,
        show_progress=not args.no_progress,
    )

    if not triangles:
        logger.error(
            "No triangles generated. BSP might be unsupported or empty."
        )
        return 1

    write_binary_stl(out_path, triangles)

    logger.info("Wrote STL with %d triangles to: %s", len(triangles), out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
