from __future__ import annotations

import pytest

from cardsmith import fonts, settings
from cardsmith.model import PRINTER_PRESETS, Printer


def test_printer_profiles_save_override_delete():
    assert [p.name for p in settings.load_printers()] == [p.name for p in PRINTER_PRESETS]
    mine = Printer(name="Prusa MINI", bed_width=181, bed_depth=181, nozzle=0.6)
    settings.save_printer(mine)
    settings.save_printer(Printer(name="My Voron", bed_width=300, bed_depth=300))
    loaded = settings.load_printers()
    names = [p.name for p in loaded]
    assert names[:2] == ["My Voron", "Prusa MINI"]
    assert names.count("Prusa MINI") == 1  # saved profile overrides the preset
    assert settings.find_printer("prusa mini").bed_width == 181
    assert settings.find_printer("voron").name == "My Voron"
    settings.delete_printer("My Voron")
    assert settings.find_printer("My Voron") is None


def test_resolve_template(tmp_path):
    from cardsmith.model import Template

    p = tmp_path / "x.toml"
    Template(name="X").save(p)
    assert settings.resolve_template(str(p)).name == "X"
    assert settings.resolve_template("kanji").slots
    with pytest.raises(FileNotFoundError):
        settings.resolve_template("nope")


def test_contours_nonzero_fill_with_counter():
    # Outer square CCW, inner square CW -> a frame (like 口).
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    inner = [(3, 3), (3, 7), (7, 7), (7, 3)]
    g = fonts._contours_to_geometry([inner, outer])
    assert g.area == pytest.approx(100 - 16)
    # Nested island wound like the outer contour fills back in (like 回).
    island = [(4, 4), (6, 4), (6, 6), (4, 6)]
    g = fonts._contours_to_geometry([outer, inner, island])
    assert g.area == pytest.approx(100 - 16 + 4)


def test_to_multipolygon():
    from shapely.geometry import GeometryCollection, LineString, Polygon, box

    assert fonts.to_multipolygon(Polygon()).is_empty
    assert len(fonts.to_multipolygon(box(0, 0, 1, 1)).geoms) == 1
    gc = GeometryCollection([box(0, 0, 1, 1), LineString([(0, 0), (1, 1)])])
    assert len(fonts.to_multipolygon(gc).geoms) == 1


def test_resolve_missing_font():
    assert fonts.try_face("No Such Family:Bold") is None
    with pytest.raises(fonts.FontError):
        fonts.face("No Such Family:Bold")
    assert fonts.registry.resolve("/no/such/font.ttf") is None


def test_shape_and_geometry(cjk_face):
    run = fonts.shape("日本", cjk_face, [], 10.0)
    assert run.width == pytest.approx(20.0, rel=0.05)  # CJK glyphs are 1 em wide
    assert not run.missing
    g = run.geometry()
    assert g.is_valid and g.area > 10
    x0, y0, x1, y1 = g.bounds
    assert 0 <= x0 and x1 <= run.width + 0.01
    spaced = fonts.shape("日本", cjk_face, [], 10.0, letter_spacing=2.0)
    assert spaced.width == pytest.approx(run.width + 2.0)


def test_resolve_by_path(cjk_face):
    ref = cjk_face.ref
    spec = f"{ref.path}#{ref.index}"
    f = fonts.face(spec)
    assert f.has("日")


def test_glyph_with_counters(cjk_face):
    g = cjk_face.outline("回")
    polys = fonts.to_multipolygon(g).geoms
    assert len(polys) == 2  # outer frame + inner square
    assert sum(len(p.interiors) for p in polys) == 2
