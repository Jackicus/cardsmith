from __future__ import annotations

import itertools

import pytest

from cardsmith.model import Printer
from cardsmith.plate import chunk, pack

EPS = 1e-6


def _rects(layout):
    w, h = layout.card_w, layout.card_h
    for s in layout.slots:
        dx, dy = (h, w) if s.rotated else (w, h)
        yield (s.x, s.y, s.x + dx, s.y + dy)


def _separation(a, b) -> float:
    """Gap between two axis-aligned rectangles (negative = overlap)."""
    dx = max(b[0] - a[2], a[0] - b[2])
    dy = max(b[1] - a[3], a[1] - b[3])
    return max(dx, dy)


CASES = [
    (54, 86, Printer()),
    (86, 54, Printer()),
    (54, 86, Printer(bed_width=250, bed_depth=210)),
    (63, 88, Printer(bed_width=180, bed_depth=180)),
    (50, 50, Printer()),
    (30, 70, Printer(bed_width=256, bed_depth=256, gap=2, margin=3)),
    (54, 86, Printer(bed_width=350, bed_depth=350, gap=6, margin=10)),
    (40, 100, Printer(bed_width=330, bed_depth=240)),
]


@pytest.mark.parametrize(("w", "h", "printer"), CASES)
def test_pack_no_overlap_and_respects_gap(w, h, printer):
    lay = pack(w, h, printer)
    assert lay.capacity > 0
    rects = list(_rects(lay))
    for a, b in itertools.combinations(rects, 2):
        assert _separation(a, b) >= printer.gap - EPS, (a, b)


@pytest.mark.parametrize(("w", "h", "printer"), CASES)
def test_pack_within_bed_margin(w, h, printer):
    lay = pack(w, h, printer)
    m = printer.margin
    for x0, y0, x1, y1 in _rects(lay):
        assert x0 >= m - EPS and y0 >= m - EPS
        assert x1 <= printer.bed_width - m + EPS
        assert y1 <= printer.bed_depth - m + EPS


@pytest.mark.parametrize(("w", "h", "printer"), CASES)
def test_pack_is_centred(w, h, printer):
    rects = list(_rects(pack(w, h, printer)))
    minx = min(r[0] for r in rects)
    maxx = max(r[2] for r in rects)
    miny = min(r[1] for r in rects)
    maxy = max(r[3] for r in rects)
    assert minx == pytest.approx(printer.bed_width - maxx, abs=1e-3)
    assert miny == pytest.approx(printer.bed_depth - maxy, abs=1e-3)


def test_rotation_improves_count():
    p = Printer()  # 220 x 220, margin 5, gap 4
    upright_only = pack(54, 86, Printer(allow_rotation=False))
    assert upright_only.capacity == 6
    assert not any(s.rotated for s in upright_only.slots)
    best = pack(54, 86, p)
    assert best.capacity >= 7
    assert any(s.rotated for s in best.slots)
    assert any(not s.rotated for s in best.slots)


def test_square_cards_never_rotated():
    lay = pack(50, 50, Printer())
    assert lay.capacity == 9
    assert not any(s.rotated for s in lay.slots)


def test_rotation_alone_when_only_rotated_fits():
    # 30 x 200 does not fit a 180-deep bed upright, but fits sideways.
    p = Printer(bed_width=220, bed_depth=180)
    assert pack(30, 200, Printer(bed_width=220, bed_depth=180, allow_rotation=False)).capacity == 0
    lay = pack(30, 200, p)
    assert lay.capacity > 0
    assert all(s.rotated for s in lay.slots)


def test_max_per_plate():
    lay = pack(54, 86, Printer(max_per_plate=4))
    assert lay.capacity == 4
    rects = list(_rects(lay))
    assert min(r[0] for r in rects) == pytest.approx(220 - max(r[2] for r in rects), abs=1e-3)


def test_card_larger_than_bed():
    assert pack(300, 300, Printer()).capacity == 0
    assert pack(211, 50, Printer(allow_rotation=False)).capacity == 0  # 220 - 2*5 = 210


def test_card_exactly_fills_usable_area():
    lay = pack(210, 210, Printer())
    assert lay.capacity == 1
    assert (lay.slots[0].x, lay.slots[0].y) == (5, 5)


def test_slot_order_back_to_front():
    lay = pack(50, 50, Printer())
    tops = [s.y + 50 for s in lay.slots]
    assert tops == sorted(tops, reverse=True)


def test_chunk():
    assert chunk(10, 4) == [range(0, 4), range(4, 8), range(8, 10)]
    assert chunk(8, 4) == [range(0, 4), range(4, 8)]
    assert chunk(3, 10) == [range(0, 3)]
    assert chunk(0, 4) == []
    assert chunk(5, 0) == []
    assert sum(len(r) for r in chunk(97, 7)) == 97
