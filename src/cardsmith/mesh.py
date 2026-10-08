"""2D shapes → watertight solids (manifold3d) → STL / 3MF files."""

from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import manifold3d as mf
import numpy as np
from shapely.geometry.base import BaseGeometry

from .fonts import to_multipolygon


def _rings(g: BaseGeometry) -> list[np.ndarray]:
    rings = []
    for p in to_multipolygon(g).geoms:
        for ring in (p.exterior, *p.interiors):
            pts = np.asarray(ring.coords, dtype=np.float64)[:-1, :2]
            if len(pts) >= 3:
                rings.append(np.ascontiguousarray(pts))
    return rings


def extrude(g: BaseGeometry, z0: float, z1: float) -> mf.Manifold:
    rings = _rings(g)
    if not rings or z1 <= z0:
        return mf.Manifold()
    cs = mf.CrossSection(rings, mf.FillRule.EvenOdd)
    return mf.Manifold.extrude(cs, z1 - z0).translate((0.0, 0.0, z0))


def place(m: mf.Manifold, x: float, y: float, rotated: bool, card_h: float) -> mf.Manifold:
    """Move a card-frame solid to its bed slot (rotating 90° CCW if needed)."""
    if rotated:
        return m.rotate((0.0, 0.0, 90.0)).translate((x + card_h, y, 0.0))
    return m.translate((x, y, 0.0))


def union(parts: list[mf.Manifold]) -> mf.Manifold:
    parts = [p for p in parts if not p.is_empty()]
    if not parts:
        return mf.Manifold()
    if len(parts) == 1:
        return parts[0]
    return mf.Manifold.batch_boolean(parts, mf.OpType.Add)


@dataclass
class MeshData:
    vertices: np.ndarray  # (n, 3) float
    triangles: np.ndarray  # (m, 3) int

    @classmethod
    def of(cls, m: mf.Manifold) -> MeshData:
        mesh = m.to_mesh()
        v = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
        t = np.asarray(mesh.tri_verts, dtype=np.int64)
        return cls(v, t)

    @property
    def empty(self) -> bool:
        return len(self.triangles) == 0


def write_stl(path: str | Path, mesh: MeshData, name: str = "cardsmith") -> None:
    v, t = mesh.vertices, mesh.triangles
    tri = v[t]  # (m, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"] = n
    rec["v"] = tri
    header = f"cardsmith binary STL: {name}".encode("ascii", "replace")[:80].ljust(80, b" ")
    with open(path, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(t)))
        f.write(rec.tobytes())


_CT = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""


def write_3mf(path: str | Path, objects: list[tuple[str, MeshData, str | None]],
              title: str = "Cardsmith") -> None:
    """Write a 3MF with one object per entry (name, mesh, display colour).

    Coordinates are bed coordinates: Cura (and other slicers) place 3MF
    objects relative to the front-left corner of the bed, so plates land
    exactly where they were packed.
    """
    objects = [o for o in objects if not o[1].empty]
    colours = [c for _, _, c in objects]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
        f' <metadata name="Title">{escape(title)}</metadata>',
        ' <metadata name="Application">Cardsmith</metadata>',
        " <resources>",
    ]
    has_colour = any(colours)
    if has_colour:
        out.append('  <basematerials id="1">')
        for i, (name, _, c) in enumerate(objects):
            out.append(f'   <base name={quoteattr(name)} displaycolor="{(c or "#CCCCCC").upper()}FF"/>')
        out.append("  </basematerials>")
    for i, (name, mesh, _) in enumerate(objects):
        oid = i + 2
        attrs = f' pid="1" pindex="{i}"' if has_colour else ""
        out.append(f'  <object id="{oid}" type="model" name={quoteattr(name)}{attrs}>')
        out.append("   <mesh>")
        out.append("    <vertices>")
        out.extend(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in mesh.vertices)
        out.append("    </vertices>")
        out.append("    <triangles>")
        out.extend(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.triangles)
        out.append("    </triangles>")
        out.append("   </mesh>")
        out.append("  </object>")
    out.append(" </resources>")
    out.append(" <build>")
    out.extend(f'  <item objectid="{i + 2}"/>' for i in range(len(objects)))
    out.append(" </build>")
    out.append("</model>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", "\n".join(out))
