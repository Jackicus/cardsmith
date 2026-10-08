"""Pack cards onto print beds.

All cards in a deck share one size, so the best layout is a grid, possibly
with a strip of rotated cards filling the leftover space. We try every split
(rows/columns in one orientation, the rest rotated) and keep the one that
fits the most cards, then centre the whole arrangement on the bed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Printer


@dataclass(frozen=True)
class Slot:
    x: float  # bed position of the card's lower-left corner (after rotation)
    y: float
    rotated: bool  # True = card turned 90° (its width runs along bed Y)


@dataclass
class PlateLayout:
    slots: list[Slot]
    card_w: float
    card_h: float
    bed_w: float
    bed_d: float
    description: str

    @property
    def capacity(self) -> int:
        return len(self.slots)


def _fit(length: float, size: float, gap: float) -> int:
    if size <= 0 or length < size:
        return 0
    return int(math.floor((length + gap + 1e-9) / (size + gap)))


def _grid(nx: int, ny: int, w: float, h: float, gap: float, x0: float, y0: float, rot: bool):
    return [Slot(x0 + i * (w + gap), y0 + j * (h + gap), rot) for j in range(ny) for i in range(nx)]


def pack(card_w: float, card_h: float, printer: Printer) -> PlateLayout:
    m, g = printer.margin, printer.gap
    U = printer.bed_width - 2 * m
    V = printer.bed_depth - 2 * m
    w, h = card_w, card_h
    best: tuple[int, float, list[Slot], str] = (0, 0.0, [], "nothing fits")

    def consider(slots: list[Slot], desc: str) -> None:
        nonlocal best
        if not slots:
            return
        # Prefer more cards, then the tighter bounding box.
        bx = max(s.x + (h if s.rotated else w) for s in slots) - min(s.x for s in slots)
        by = max(s.y + (w if s.rotated else h) for s in slots) - min(s.y for s in slots)
        score = (len(slots), -bx * by)
        if score > (best[0], best[1]):
            best = (len(slots), -bx * by, slots, desc)

    orientations = [(w, h, False)]
    if printer.allow_rotation and abs(w - h) > 1e-6:
        orientations.append((h, w, True))

    for aw, ah, arot in orientations:
        nx, ny = _fit(U, aw, g), _fit(V, ah, g)
        consider(_grid(nx, ny, aw, ah, g, 0, 0, arot), f"{nx} × {ny}")
        if not printer.allow_rotation:
            continue
        bw, bh, brot = ah, aw, not arot
        # Rows of A along the bottom, rotated cards filling the strip above.
        for rows in range(0, ny + 1):
            used = rows * (ah + g)
            main = _grid(nx, rows, aw, ah, g, 0, 0, arot)
            sx, sy = _fit(U, bw, g), _fit(V - used, bh, g)
            extra = _grid(sx, sy, bw, bh, g, 0, used, brot)
            if extra:
                consider(main + extra, f"{nx} × {rows} + {sx} × {sy} turned")
        # Columns of A on the left, rotated cards filling the strip on the right.
        for cols in range(0, nx + 1):
            used = cols * (aw + g)
            main = _grid(cols, ny, aw, ah, g, 0, 0, arot)
            sx, sy = _fit(U - used, bw, g), _fit(V, bh, g)
            extra = _grid(sx, sy, bw, bh, g, used, 0, brot)
            if extra:
                consider(main + extra, f"{cols} × {ny} + {sx} × {sy} turned")

    _, _, slots, desc = best
    if printer.max_per_plate > 0:
        slots = slots[: printer.max_per_plate]
    if slots:
        # Centre on the bed and order front-to-back, left-to-right in rows
        # from the back so plate order reads like a page.
        minx = min(s.x for s in slots)
        miny = min(s.y for s in slots)
        maxx = max(s.x + (h if s.rotated else w) for s in slots)
        maxy = max(s.y + (w if s.rotated else h) for s in slots)
        ox = (printer.bed_width - (maxx - minx)) / 2 - minx
        oy = (printer.bed_depth - (maxy - miny)) / 2 - miny
        slots = [Slot(round(s.x + ox, 4), round(s.y + oy, 4), s.rotated) for s in slots]
        slots.sort(key=lambda s: (-round(s.y + (w if s.rotated else h), 2), s.x))
    return PlateLayout(slots, w, h, printer.bed_width, printer.bed_depth, desc)


def chunk(n_cards: int, capacity: int) -> list[range]:
    if capacity <= 0:
        return []
    return [range(i, min(i + capacity, n_cards)) for i in range(0, n_cards, capacity)]
