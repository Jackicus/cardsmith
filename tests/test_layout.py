from __future__ import annotations

import math

import pytest
from helpers import CJK_FONT, simple_template
from shapely.geometry import Point, Polygon, box

from cardsmith.layout import border_shape, card_outline, hole_centre, layout_card, print_problems
from cardsmith.model import Border, Hole, Printer, Slot, Template
from cardsmith.settings import default_template

needs_cjk = pytest.mark.usefixtures("cjk_face")

ROW = {"word": "漢字", "reading": "カン・かんじ", "meaning": "Chinese character", "jlpt": "N5"}


def _issues(lay, level=None, slot=None):
    return [i for i in lay.issues if (level is None or i.level == level) and (slot is None or i.slot == slot)]


@needs_cjk
def test_kanji_template_features_and_z_ranges():
    t = default_template()
    p = Printer()
    lay = layout_card(t, p, ROW)
    by_name = {f.name: f for f in lay.features}
    assert set(by_name) == {"Card", "Border", "Word", "Reading", "Meaning", "Tag"}
    base = by_name["Card"]
    assert (base.kind, base.z0, base.z1, base.band) == ("base", 0.0, pytest.approx(1.2), 0)
    border = by_name["Border"]
    assert border.z0 == pytest.approx(1.2) and border.z1 == pytest.approx(1.6)
    for name in ("Word", "Reading", "Meaning", "Tag"):
        f = by_name[name]
        assert f.kind == "slot"
        assert f.z0 == pytest.approx(1.2) and f.z1 == pytest.approx(1.8)
        assert f.band == 2
        assert not f.geom.is_empty
    assert lay.base_z == pytest.approx(1.2)
    assert lay.top_z == pytest.approx(1.8)
    assert lay.label == "漢字"
    assert lay.worst() in (None, "info")


@needs_cjk
def test_z_ranges_follow_printer_layers():
    t = default_template()
    p = Printer(first_layer_height=0.28, layer_height=0.2)
    lay = layout_card(t, p, ROW, check_print=False)
    base = next(f for f in lay.features if f.kind == "base")
    assert base.z1 == pytest.approx(1.28)
    assert all(f.z0 == pytest.approx(1.28) for f in lay.features if f.kind != "base")


@needs_cjk
def test_text_stays_within_card():
    t = default_template()
    lay = layout_card(t, Printer(), ROW, check_print=False)
    outline = card_outline(t.card.width, t.card.height, t.card.corner_radius)
    for f in lay.features:
        assert f.geom.within(outline.buffer(1e-6)), f.name
    for b in lay.boxes:
        x0, y0, x1, y1 = b.bounds
        assert 0 <= x0 < x1 <= t.card.width
        assert 0 <= y0 < y1 <= t.card.height


@needs_cjk
def test_slot_y_measured_from_top():
    t = simple_template(y=20.0)
    lay = layout_card(t, Printer(), {"word": "日"}, check_print=False)
    (b,) = lay.boxes
    centre = (b.bounds[1] + b.bounds[3]) / 2
    assert centre == pytest.approx(86 - 20, abs=1.5)


@needs_cjk
def test_alignment():
    def bounds(align):
        lay = layout_card(simple_template(align=align, size=6.0), Printer(), {"word": "日本"}, check_print=False)
        return lay.boxes[0].bounds

    # Ink bounds sit slightly inside the advance box (side bearings).
    lx0, _, lx1, _ = bounds("left")
    assert 3.0 <= lx0 <= 4.5
    rx0, _, rx1, _ = bounds("right")
    assert 49.5 <= rx1 <= 51.0
    cx0, _, cx1, _ = bounds("center")
    assert (cx0 + cx1) / 2 == pytest.approx(27.0, abs=0.6)
    assert lx1 - lx0 == pytest.approx(rx1 - rx0) == pytest.approx(cx1 - cx0)


@needs_cjk
def test_long_text_shrinks_with_info():
    t = simple_template(size=12.0, min_size=3.0, fit="shrink")
    lay = layout_card(t, Printer(), {"word": "漢字漢字漢字漢字"}, check_print=False)
    (b,) = lay.boxes
    assert b.size < 12.0
    assert b.bounds[2] - b.bounds[0] <= 48.0 + 0.05
    infos = _issues(lay, "info", "Word")
    assert any("shrunk" in i.message for i in infos)
    assert not _issues(lay, "error")


@needs_cjk
def test_shrink_hits_min_size_warns_and_errors():
    t = simple_template(size=12.0, min_size=10.0, fit="shrink")
    lay = layout_card(t, Printer(), {"word": "漢字漢字漢字漢字漢字"}, check_print=False)
    assert lay.boxes[0].size == pytest.approx(10.0)
    assert any("wider" in i.message for i in _issues(lay, "warning"))
    assert any("off the edge" in i.message for i in _issues(lay, "error"))


@needs_cjk
def test_long_text_wraps():
    t = simple_template(size=5.0, min_size=4.0, fit="wrap", max_lines=3)
    lay = layout_card(t, Printer(), {"word": "the quick brown fox jumps over the lazy dog"}, check_print=False)
    (b,) = lay.boxes
    assert 2 <= b.lines <= 3
    assert b.size == pytest.approx(5.0)
    assert b.bounds[2] - b.bounds[0] <= 48.0 + 0.05
    assert not _issues(lay, "warning")


@needs_cjk
def test_wrap_too_many_lines_warns():
    t = simple_template(size=5.0, min_size=4.5, fit="wrap", max_lines=1)
    lay = layout_card(t, Printer(), {"word": "the quick brown fox jumps over the lazy dog"}, check_print=False)
    assert any("lines" in i.message for i in _issues(lay, "warning", "Word"))


@needs_cjk
def test_missing_glyph_is_error():
    t = simple_template()
    lay = layout_card(t, Printer(), {"word": "日\U00013000"}, check_print=False)  # Egyptian hieroglyph
    errs = _issues(lay, "error", "Word")
    assert any("\U00013000" in i.message for i in errs)
    assert lay.worst() == "error"


@needs_cjk
def test_unknown_font_falls_back_with_warning():
    t = simple_template(font="Definitely Not A Font:Bold")
    lay = layout_card(t, Printer(), {"word": "日"}, check_print=False)
    assert any("not found" in i.message for i in _issues(lay, "warning", "Word"))
    assert lay.boxes


@needs_cjk
def test_no_usable_font_is_error():
    t = simple_template(font="Nope:Bold")
    t.fallback_fonts = ["Also Nope:Bold"]
    lay = layout_card(t, Printer(), {"word": "日"}, check_print=False)
    assert _issues(lay, "error", "Word")


@needs_cjk
def test_empty_field_is_info_and_skipped():
    t = simple_template()
    lay = layout_card(t, Printer(), {"word": ""}, check_print=False)
    assert [f.kind for f in lay.features] == ["base"]
    assert any("empty" in i.message for i in _issues(lay, "info"))
    assert lay.label == "card 1"


@needs_cjk
def test_ruby_slot_places_reading_above():
    t = simple_template(text="{e}", ruby=True, size=10.0)
    plain = layout_card(simple_template(text="{e}", size=10.0), Printer(), {"e": "漢字[かんじ]"}, check_print=False)
    ruby = layout_card(t, Printer(), {"e": "漢字[かんじ]"}, check_print=False)
    assert ruby.boxes[0].bounds[3] > plain.boxes[0].bounds[3] + 2
    assert ruby.label == "漢字"


@needs_cjk
def test_hole_cuts_card():
    t = simple_template()
    t.hole = Hole(enabled=True, diameter=5.0, position="top-left", offset=6.0)
    lay = layout_card(t, Printer(), {"word": "日"}, check_print=False)
    hx, hy = hole_centre(t)
    assert (hx, hy) == (6.0, 80.0)
    base = lay.features[0]
    assert not base.geom.contains(Point(hx, hy))
    outline = card_outline(54, 86, 3)
    assert base.geom.area == pytest.approx(outline.area - math.pi * 2.5**2, rel=2e-3)


@pytest.mark.parametrize(
    ("pos", "expected"),
    [("top-left", (5.5, 80.5)), ("bottom-right", (48.5, 5.5)), ("top-center", (27.0, 80.5)),
     ("center-left", (5.5, 43.0))],
)
def test_hole_positions(pos, expected):
    t = Template(hole=Hole(enabled=True, position=pos, offset=5.5))
    assert hole_centre(t) == expected


def test_border_ring_area():
    w, h, r, bw = 54.0, 86.0, 4.0, 1.5
    t = Template(border=Border(enabled=True, width=bw, inset=0.0), hole=Hole(enabled=False))
    outline = card_outline(w, h, r)
    ring = border_shape(t, outline, Polygon())
    expected = (w * h - (4 - math.pi) * r * r) - ((w - 2 * bw) * (h - 2 * bw) - (4 - math.pi) * (r - bw) ** 2)
    assert ring.area == pytest.approx(expected, rel=5e-3)
    assert ring.within(outline.buffer(1e-6))


def test_border_with_inset_and_hole_ring():
    t = Template(
        border=Border(enabled=True, width=1.0, inset=1.0, around_hole=True),
        hole=Hole(enabled=True, diameter=4.0, position="top-left", offset=6.0),
        slots=[],
    )
    lay = layout_card(t, Printer(), {}, check_print=False)
    border = next(f for f in lay.features if f.kind == "border")
    # Inset: the outermost millimetre of the card is clear.
    assert not border.geom.intersects(box(10, 0, 40, 0.9))
    # Ring around the hole, but not covering the hole itself.
    assert border.geom.contains(Point(6.0 + 2.5, 80.0))
    assert not border.geom.contains(Point(6.0, 80.0))


@needs_cjk
def test_border_disabled_no_feature():
    t = simple_template()
    lay = layout_card(t, Printer(), {"word": "日"}, check_print=False)
    assert "border" not in {f.kind for f in lay.features}


def test_print_problems_thin_rectangle():
    thin, gaps = print_problems(box(0, 0, 0.2, 10), 0.4)
    assert thin.area == pytest.approx(2.0, rel=0.05)
    assert gaps.is_empty


def test_print_problems_narrow_gap():
    g = box(0, 0, 10, 10).union(box(10.2, 0, 20, 10))
    thin, gaps = print_problems(g, 0.4)
    assert thin.is_empty
    assert not gaps.is_empty
    assert gaps.area == pytest.approx(0.2 * 10, rel=0.1)
    gx0, _, gx1, _ = gaps.bounds
    assert gx0 >= 10 - 1e-6 and gx1 <= 10.2 + 1e-6


def test_print_problems_fat_square_clean():
    thin, gaps = print_problems(box(0, 0, 10, 10), 0.4)
    assert thin.is_empty and gaps.is_empty


def test_print_problems_wide_gap_ok():
    g = box(0, 0, 10, 10).union(box(11, 0, 20, 10))
    _, gaps = print_problems(g, 0.4)
    assert gaps.is_empty


@needs_cjk
def test_layout_reports_thin_strokes_for_tiny_text():
    t = simple_template(size=3.0, min_size=3.0)
    t.fallback_fonts = [CJK_FONT]
    lay = layout_card(t, Printer(nozzle=0.6), {"word": "書"})
    assert not lay.thin.is_empty or not lay.gaps.is_empty
    assert _issues(lay, "warning", "Word")


@needs_cjk
def test_thin_border_warning():
    t = simple_template()
    t.border = Border(enabled=True, width=0.3)
    lay = layout_card(t, Printer(), {"word": "日"})
    assert _issues(lay, "warning", "Border")


@needs_cjk
def test_overlapping_slots_warn():
    t = simple_template(size=10.0)
    t.slots.append(Slot("Again", "{word}", font=CJK_FONT, size=10.0, y=43.0))
    lay = layout_card(t, Printer(), {"word": "日"}, check_print=False)
    assert any("overlaps" in i.message for i in _issues(lay, "warning", "Again"))
