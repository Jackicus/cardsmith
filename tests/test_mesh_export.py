from __future__ import annotations

import csv
import math
import zipfile
from xml.etree import ElementTree as ET

import manifold3d as mf
import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box

from cardsmith import mesh as ms
from cardsmith.export import Cancelled, ExportOptions, card_solid, colour_plan_lines, cura_steps, export_deck
from cardsmith.layout import layout_card
from cardsmith.model import Border, Hole, Printer, Template, colour_changes
from cardsmith.settings import default_template

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


# ---------------------------------------------------------------------------
# Solids


def test_extrude_square_volume():
    m = ms.extrude(box(0, 0, 10, 10), 0.0, 1.0)
    assert m.status() == mf.Error.NoError
    assert m.volume() == pytest.approx(100.0)
    lo, hi = m.bounding_box()[:3], m.bounding_box()[3:]
    assert lo == pytest.approx((0, 0, 0)) and hi == pytest.approx((10, 10, 1))


def test_extrude_offset_z_and_hole():
    g = box(0, 0, 10, 10).difference(box(3, 3, 7, 7))
    m = ms.extrude(g, 1.2, 1.8)
    assert m.status() == mf.Error.NoError
    assert m.volume() == pytest.approx((100 - 16) * 0.6)
    bb = m.bounding_box()
    assert bb[2] == pytest.approx(1.2) and bb[5] == pytest.approx(1.8)
    assert m.genus() == 1


def test_extrude_multipolygon_and_circle():
    g = Point(0, 0).buffer(5, quad_segs=32).union(box(20, 0, 22, 2))
    m = ms.extrude(g, 0, 2)
    assert m.status() == mf.Error.NoError
    assert m.volume() == pytest.approx((g.area) * 2, rel=1e-6)
    assert m.volume() == pytest.approx((math.pi * 25 + 4) * 2, rel=5e-3)


def test_extrude_empty_or_flat():
    assert ms.extrude(Polygon(), 0, 1).is_empty()
    assert ms.extrude(box(0, 0, 1, 1), 1, 1).is_empty()


def test_union_and_place():
    a = ms.extrude(box(0, 0, 10, 20), 0, 1)
    b = ms.extrude(box(5, 0, 15, 20), 0, 1)
    u = ms.union([a, b, mf.Manifold()])
    assert u.volume() == pytest.approx(300)
    assert ms.union([]).is_empty()
    # 10 x 20 card turned 90° at slot (100, 50) occupies x 100..120, y 50..60.
    placed = ms.place(a, 100, 50, True, 20)
    bb = placed.bounding_box()
    assert bb[0] == pytest.approx(100) and bb[3] == pytest.approx(120)
    assert bb[1] == pytest.approx(50) and bb[4] == pytest.approx(60)
    straight = ms.place(a, 100, 50, False, 20).bounding_box()
    assert straight[:2] == pytest.approx((100, 50))


def test_mesh_data():
    md = ms.MeshData.of(ms.extrude(box(0, 0, 1, 1), 0, 1))
    assert md.vertices.shape[1] == 3 and md.triangles.shape[1] == 3
    assert not md.empty
    assert ms.MeshData.of(mf.Manifold()).empty


# ---------------------------------------------------------------------------
# Writers


def test_write_stl_binary_size_and_normals(tmp_path):
    md = ms.MeshData.of(ms.extrude(box(0, 0, 10, 10), 0, 1))
    f = tmp_path / "a.stl"
    ms.write_stl(f, md, "Ünïcode name")
    data = f.read_bytes()
    n = len(md.triangles)
    assert len(data) == 84 + 50 * n
    assert int.from_bytes(data[80:84], "little") == n
    rec = np.frombuffer(data[84:], dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    norms = np.linalg.norm(rec["n"], axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
    # Outward normals: signed volume from the triangles is positive.
    v = rec["v"].astype(np.float64)
    vol = np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6
    assert vol == pytest.approx(100.0, rel=1e-5)


def _read_model(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        root = ET.fromstring(z.read("3D/3dmodel.model"))
        ET.fromstring(z.read("[Content_Types].xml"))
        rels = ET.fromstring(z.read("_rels/.rels"))
    return names, root, rels


def test_write_3mf_structure(tmp_path):
    a = ms.MeshData.of(ms.extrude(box(0, 0, 10, 10), 0, 1))
    b = ms.MeshData.of(ms.extrude(box(20, 0, 30, 10), 0, 2))
    empty = ms.MeshData.of(mf.Manifold())
    f = tmp_path / "a.3mf"
    ms.write_3mf(f, [("Base & <one>", a, "#ff0000"), ("Top", b, None), ("Empty", empty, "#00FF00")], "T")
    names, root, rels = _read_model(f)
    assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= names
    assert root.get("unit") == "millimeter"
    target = rels[0].get("Target")
    assert target == "/3D/3dmodel.model"
    objs = root.findall("m:resources/m:object", NS)
    assert [o.get("name") for o in objs] == ["Base & <one>", "Top"]  # empty object dropped
    items = root.findall("m:build/m:item", NS)
    assert [i.get("objectid") for i in items] == [o.get("id") for o in objs]
    bases = root.findall("m:resources/m:basematerials/m:base", NS)
    assert [b.get("displaycolor") for b in bases] == ["#FF0000FF", "#CCCCCCFF"]
    for o, md in zip(objs, (a, b), strict=True):
        verts = o.findall("m:mesh/m:vertices/m:vertex", NS)
        tris = o.findall("m:mesh/m:triangles/m:triangle", NS)
        assert len(verts) == len(md.vertices)
        assert len(tris) == len(md.triangles)
        idx = {int(t.get(k)) for t in tris for k in ("v1", "v2", "v3")}
        assert max(idx) < len(verts) and min(idx) >= 0


def test_write_3mf_without_colours(tmp_path):
    a = ms.MeshData.of(ms.extrude(box(0, 0, 10, 10), 0, 1))
    f = tmp_path / "a.3mf"
    ms.write_3mf(f, [("Plate 1", a, None)])
    _, root, _ = _read_model(f)
    assert root.find("m:resources/m:basematerials", NS) is None
    (obj,) = root.findall("m:resources/m:object", NS)
    assert obj.get("pid") is None


# ---------------------------------------------------------------------------
# Whole-deck export


def _plain_template() -> Template:
    """No text, so it needs no fonts: base + border + hole."""
    t = Template(
        name="Plain",
        border=Border(enabled=True, width=1.5, height=0.4),
        hole=Hole(enabled=True, diameter=4.0),
        slots=[],
    )
    t.palette = ["#FFFFFF", "#000000"]
    return t


def _vertices(path):
    _, root, _ = _read_model(path)
    out = {}
    for o in root.findall("m:resources/m:object", NS):
        out[o.get("name")] = np.array(
            [[float(v.get(k)) for k in "xyz"] for v in o.findall("m:mesh/m:vertices/m:vertex", NS)]
        )
    return out


def test_export_deck_plain(tmp_path):
    t = _plain_template()
    p = Printer(bed_width=130, bed_depth=200)
    rows = [(i, {"word": str(i)}) for i in range(5)]
    seen = []
    res = export_deck(t, p, rows, tmp_path / "out", ExportOptions(plates_stl=True, singles_stl=True),
                      progress=lambda f, m: seen.append(f))
    out = tmp_path / "out"
    assert res.cards == 5
    assert res.per_plate == 4  # 2 x 2 on a 120 x 190 usable area
    assert res.plates == 2
    for name in ("plate_01.3mf", "plate_01_colours.3mf", "plate_02.3mf", "plate_01.stl"):
        assert (out / "plates" / name).exists(), name
    assert len(list((out / "cards").glob("*.stl"))) == 5
    assert (out / "manifest.csv").exists() and (out / "template.toml").exists()
    assert res.guide == out / "PRINT_GUIDE.md"
    guide = res.guide.read_text(encoding="utf-8")
    assert "5 cards" in guide and "2 plates" in guide
    assert Template.load(out / "template.toml") == t
    assert all(f.exists() for f in res.files)
    assert seen == sorted(seen) and seen[-1] == 1.0

    with open(out / "manifest.csv", encoding="utf-8") as fh:
        manifest = list(csv.DictReader(fh))
    assert len(manifest) == 5
    assert [m["plate"] for m in manifest] == ["1", "1", "1", "1", "2"]

    # Plate geometry stays on the bed, in bed coordinates (front-left origin).
    verts = _vertices(out / "plates" / "plate_01.3mf")
    (v,) = verts.values()
    assert v[:, 0].min() >= p.margin - 1e-3 and v[:, 0].max() <= p.bed_width - p.margin + 1e-3
    assert v[:, 1].min() >= p.margin - 1e-3 and v[:, 1].max() <= p.bed_depth - p.margin + 1e-3
    assert v[:, 2].min() == pytest.approx(0) and v[:, 2].max() == pytest.approx(1.6)

    colours = _vertices(out / "plates" / "plate_01_colours.3mf")
    assert list(colours) == ["Colour 1 – Card", "Colour 2 – Border"]
    assert colours["Colour 1 – Card"][:, 2].max() == pytest.approx(1.2)
    assert colours["Colour 2 – Border"][:, 2].min() == pytest.approx(1.2)


def test_export_deck_singles_3mf_and_no_plates(tmp_path):
    t = _plain_template()
    opts = ExportOptions(plates_3mf=False, plates_colour_3mf=False, singles_3mf=True)
    res = export_deck(t, Printer(), [(0, {}), (1, {})], tmp_path, opts)
    assert not (tmp_path / "plates").exists()
    assert len(list((tmp_path / "cards").glob("*.3mf"))) == 2
    assert res.plates == 1


def test_export_deck_cancel(tmp_path):
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(Cancelled):
        export_deck(_plain_template(), Printer(), [(i, {}) for i in range(5)], tmp_path, cancelled=cancelled)
    assert not (tmp_path / "PRINT_GUIDE.md").exists()


def test_export_deck_errors(tmp_path):
    with pytest.raises(ValueError, match="No cards"):
        export_deck(_plain_template(), Printer(), [], tmp_path)
    t = _plain_template()
    t.card.width = 500
    with pytest.raises(ValueError, match="does not fit"):
        export_deck(t, Printer(), [(0, {})], tmp_path)


def test_card_solid_is_valid_manifold():
    t = _plain_template()
    lay = layout_card(t, Printer(), {}, check_print=False)
    s = card_solid(lay)
    assert s.status() == mf.Error.NoError
    base_area = lay.features[0].geom.area
    border_area = lay.features[1].geom.area
    assert s.volume() == pytest.approx(base_area * 1.2 + border_area * 0.4, rel=1e-3)
    assert s.genus() == 1  # the hanging hole


@pytest.mark.usefixtures("cjk_face")
def test_export_deck_with_text(tmp_path):
    t = default_template()
    rows = [(0, {"word": "日", "reading": "にち", "meaning": "day; sun", "jlpt": "N5"}),
            (1, {"word": "\U00013000", "meaning": "hieroglyph"})]
    res = export_deck(t, Printer(), rows, tmp_path)
    assert res.plates == 1
    assert [i for i, _, _ in res.problem_cards] == [1]
    colours = _vertices(tmp_path / "plates" / "plate_01_colours.3mf")
    assert len(colours) == 3
    guide = res.guide.read_text(encoding="utf-8")
    assert "Cards to double-check" in guide


def test_guide_layer_numbers_match_colour_changes():
    t = default_template()  # base 1.2, border +0.4, text +0.6, three different colours
    p = Printer()
    changes = colour_changes(t, p)
    assert [c.layer for c in changes] == [7, 9]
    steps = cura_steps(t, p)
    assert "`7,9`" in steps
    lines = colour_plan_lines(t, p)
    assert lines[0].endswith("layers 1–6 (0 – 1.2 mm)")
    assert "Layer **7**" in lines[1] and "Layer **9**" in lines[2]


def test_cura_steps_single_colour():
    t = _plain_template()
    t.palette = ["#FFFFFF", "#FFFFFF"]
    assert "no filament change" in cura_steps(t, Printer())


def test_write_3mf_escapes_quotes_in_names(tmp_path):
    a = ms.MeshData.of(ms.extrude(box(0, 0, 1, 1), 0, 1))
    f = tmp_path / "q.3mf"
    ms.write_3mf(f, [('Colour 2 – Say "hi"', a, "#FF0000")])
    _, root, _ = _read_model(f)
    assert root.find("m:resources/m:object", NS).get("name") == 'Colour 2 – Say "hi"'


def test_export_removes_stale_plates_from_earlier_runs(tmp_path):
    t = Template(slots=[])
    rows = [(i, {}) for i in range(20)]
    export_deck(t, Printer(), rows, tmp_path, ExportOptions(plates_colour_3mf=False))
    many = sorted(p.name for p in (tmp_path / "plates").iterdir())
    export_deck(t, Printer(), rows[:2], tmp_path, ExportOptions(plates_colour_3mf=False))
    few = sorted(p.name for p in (tmp_path / "plates").iterdir())
    assert len(many) > 1
    assert few == ["plate_01.3mf"]
    (tmp_path / "plates" / "notes.txt").write_text("mine")
    export_deck(t, Printer(), rows[:2], tmp_path, ExportOptions(plates_colour_3mf=False))
    assert (tmp_path / "plates" / "notes.txt").exists()  # only our own files are cleared
