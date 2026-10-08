"""Turn a template + one data row into exact 2D geometry per height.

Coordinates are millimetres in the card's own frame: origin at the
bottom-left corner, x to the right, y up (the same as the printer bed, so
nothing needs flipping on export). Slot ``y`` values in the template are
measured from the *top* edge because that is how people think about cards.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import fonts
from . import text as tx
from .model import Printer, Slot, Template, height_bands


@dataclass
class Feature:
    name: str
    kind: str  # "base" | "border" | "slot"
    geom: BaseGeometry
    z0: float
    z1: float
    band: int
    slot_index: int | None = None


@dataclass
class Issue:
    level: str  # "error" | "warning" | "info"
    message: str
    slot: str | None = None

    def __str__(self) -> str:
        where = f"{self.slot}: " if self.slot else ""
        return f"{where}{self.message}"


@dataclass
class SlotBox:
    slot_index: int
    bounds: tuple[float, float, float, float]
    content: str
    size: float
    lines: int


@dataclass
class CardLayout:
    width: float
    height: float
    base_z: float
    outline: BaseGeometry
    hole: BaseGeometry
    features: list[Feature] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    boxes: list[SlotBox] = field(default_factory=list)
    thin: BaseGeometry = field(default_factory=Polygon)
    gaps: BaseGeometry = field(default_factory=Polygon)
    label: str = ""

    @property
    def top_z(self) -> float:
        return max((f.z1 for f in self.features), default=self.base_z)

    def worst(self) -> str | None:
        levels = {i.level for i in self.issues}
        for lvl in ("error", "warning", "info"):
            if lvl in levels:
                return lvl
        return None


# ---------------------------------------------------------------------------
# Card furniture


def card_outline(w: float, h: float, r: float) -> BaseGeometry:
    r = max(0.0, min(r, w / 2 - 0.01, h / 2 - 0.01))
    if r <= 0:
        return box(0, 0, w, h)
    return box(r, r, w - r, h - r).buffer(r, quad_segs=24)


def hole_centre(t: Template) -> tuple[float, float]:
    c, hole = t.card, t.hole
    v, _, hz = hole.position.partition("-")
    x = {"left": hole.offset, "center": c.width / 2, "right": c.width - hole.offset}.get(hz, hole.offset)
    y = {"top": c.height - hole.offset, "center": c.height / 2, "bottom": hole.offset}.get(v, c.height / 2)
    return x, y


def hole_shape(t: Template) -> BaseGeometry:
    if not t.hole.enabled or t.hole.diameter <= 0:
        return Polygon()
    x, y = hole_centre(t)
    return Point(x, y).buffer(t.hole.diameter / 2, quad_segs=24)


def border_shape(t: Template, outline: BaseGeometry, hole: BaseGeometry) -> BaseGeometry:
    b = t.border
    if not b.enabled or b.width <= 0:
        return Polygon()
    outer = outline.buffer(-b.inset, quad_segs=24) if b.inset > 0 else outline
    ring = outer.difference(outer.buffer(-b.width, quad_segs=24))
    if not hole.is_empty and b.around_hole:
        ring = ring.union(hole.buffer(b.width, quad_segs=24))
    return ring.intersection(outline).difference(hole)


# ---------------------------------------------------------------------------
# Text


@dataclass
class _Laid:
    geom: BaseGeometry
    size: float
    lines: int
    issues: list[Issue]


def _faces(slot: Slot, t: Template) -> tuple[fonts.Face, list[fonts.Face], list[Issue]]:
    issues: list[Issue] = []
    fallbacks = [f for f in (fonts.try_face(s) for s in t.fallback_fonts) if f]
    primary = fonts.try_face(slot.font)
    if primary is None:
        if not fallbacks:
            raise fonts.FontError(f"No usable font for {slot.name!r} (tried {slot.font!r})")
        issues.append(Issue("warning", f"font {slot.font!r} not found, using {fallbacks[0].ref.key}", slot.name))
        primary = fallbacks[0]
    return primary, fallbacks, issues


def _available_width(slot: Slot, t: Template) -> float:
    c = t.card
    full = c.width - 2 * c.padding
    if slot.align == "center":
        full -= 2 * abs(slot.x_offset)
    else:
        full -= slot.x_offset
    if slot.max_width > 0:
        full = min(full, slot.max_width) if full > 0 else slot.max_width
    return max(full, 1.0)


def _place_x(slot: Slot, t: Template, width: float) -> float:
    c = t.card
    if slot.align == "left":
        return c.padding + slot.x_offset
    if slot.align == "right":
        return c.width - c.padding - slot.x_offset - width
    return c.width / 2 + slot.x_offset - width / 2


def _wrap(tokens: list[str], primary, fallbacks, size, spacing, max_w) -> list[str]:
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        trial = cur + tok
        if cur and fonts.shape(trial.rstrip(), primary, fallbacks, size, spacing).width > max_w:
            lines.append(cur.rstrip())
            cur = tok.lstrip()
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def _lay_plain(slot: Slot, t: Template, content: str, primary, fallbacks, y_centre: float) -> _Laid:
    issues: list[Issue] = []
    max_w = _available_width(slot, t)
    size = slot.size
    sp = slot.letter_spacing

    if slot.fit == "wrap":
        tokens = tx.wrap_tokens(content)
        lines = _wrap(tokens, primary, fallbacks, size, sp, max_w)
        while len(lines) > max(1, slot.max_lines) and size > slot.min_size:
            size = max(slot.min_size, size * 0.92)
            lines = _wrap(tokens, primary, fallbacks, size, sp, max_w)
        if len(lines) > max(1, slot.max_lines):
            issues.append(Issue("warning", f"needs {len(lines)} lines (max {slot.max_lines}) even at minimum size", slot.name))
        runs = [fonts.shape(line, primary, fallbacks, size, sp) for line in lines]
        widest = max(r.width for r in runs)
        if widest > max_w + 0.01:
            # A single unbreakable word: shrink to fit as a last resort.
            size2 = max(slot.min_size, size * max_w / widest)
            if size2 < size:
                size = size2
                runs = [fonts.shape(line, primary, fallbacks, size, sp) for line in lines]
    else:
        runs = [fonts.shape(content, primary, fallbacks, size, sp)]
        if slot.fit == "shrink" and runs[0].width > max_w:
            size = max(slot.min_size, size * max_w / runs[0].width)
            runs = [fonts.shape(content, primary, fallbacks, size, sp)]

    if any(r.width > max_w + 0.05 for r in runs):
        issues.append(Issue("warning", "text is wider than its space" +
                            (" even at minimum size" if slot.fit != "none" else ""), slot.name))

    pitch = size * slot.line_spacing
    parts = []
    n = len(runs)
    for i, run in enumerate(runs):
        cy = y_centre - (i - (n - 1) / 2) * pitch
        g = run.geometry()
        if g.is_empty:
            continue
        x0 = _place_x(slot, t, run.width)
        parts.append(affinity.translate(g, x0, cy - run.mid))
    missing = sorted({m for r in runs for m in r.missing})
    if missing:
        issues.append(Issue("error", f"no installed font has: {''.join(missing)}", slot.name))
    return _Laid(unary_union(parts) if parts else Polygon(), size, n, issues)


def _lay_ruby(slot: Slot, t: Template, content: str, primary, fallbacks, y_centre: float) -> _Laid:
    issues: list[Issue] = []
    max_w = _available_width(slot, t)
    segs = tx.ruby_segments(content)

    def build(size: float):
        rs = size * slot.ruby_scale
        sp = slot.letter_spacing
        items = []
        x = 0.0
        for k, (base, reading) in enumerate(segs):
            br = fonts.shape(base, primary, fallbacks, size, sp)
            rr = fonts.shape(reading, primary, fallbacks, rs, 0) if reading else None
            base_dx, ruby_dx, w = 0.0, 0.0, br.width
            if rr is not None:
                need = rr.width - br.width
                if need > 0:
                    # A long reading may hang over neighbouring kana (up to one
                    # ruby character each side), as in Japanese typesetting.
                    allow_l = rs if k > 0 and segs[k - 1][1] is None else 0.0
                    allow_r = rs if k < len(segs) - 1 and segs[k + 1][1] is None else 0.0
                    ol = min(allow_l, need / 2)
                    orr = min(allow_r, need / 2)
                    rest = need - ol - orr
                    extra_l = min(allow_l - ol, rest)
                    ol += extra_l
                    rest -= extra_l
                    extra_r = min(allow_r - orr, rest)
                    orr += extra_r
                    rest -= extra_r
                    w = br.width + rest
                    base_dx = rest / 2
                    ruby_dx = base_dx - ol - rest / 2
                else:
                    ruby_dx = -need / 2
            items.append((x, w, br, rr, base_dx, ruby_dx))
            x += w + sp
        return items, max(0.0, x - sp)

    size = slot.size
    items, total = build(size)
    if slot.fit != "none" and total > max_w:
        size = max(slot.min_size, size * max_w / total)
        items, total = build(size)
    if total > max_w + 0.05:
        issues.append(Issue("warning", "text is wider than its space", slot.name))

    x0 = _place_x(slot, t, total)
    parts = []
    missing: set[str] = set()
    ruby_cy = y_centre + size / 2 + slot.ruby_gap + size * slot.ruby_scale / 2
    for x, _w, br, rr, base_dx, ruby_dx in items:
        missing.update(br.missing)
        g = br.geometry()
        if not g.is_empty:
            parts.append(affinity.translate(g, x0 + x + base_dx, y_centre - br.mid))
        if rr:
            missing.update(rr.missing)
            g = rr.geometry()
            if not g.is_empty:
                parts.append(affinity.translate(g, x0 + x + ruby_dx, ruby_cy - rr.mid))
    if missing:
        issues.append(Issue("error", f"no installed font has: {''.join(sorted(missing))}", slot.name))
    return _Laid(unary_union(parts) if parts else Polygon(), size, 1, issues)


def lay_slot(slot: Slot, t: Template, content: str) -> _Laid:
    primary, fallbacks, issues = _faces(slot, t)
    y_centre = t.card.height - slot.y
    if slot.ruby and tx.has_ruby(content):
        laid = _lay_ruby(slot, t, content, primary, fallbacks, y_centre)
    else:
        laid = _lay_plain(slot, t, tx.kanji(content), primary, fallbacks, y_centre)
    laid.issues[:0] = issues
    return laid


# ---------------------------------------------------------------------------
# Printability checks


def _significant(g: BaseGeometry, min_area: float) -> BaseGeometry:
    polys = [p for p in fonts.to_multipolygon(g).geoms if p.area >= min_area]
    return unary_union(polys) if polys else Polygon()


def print_problems(g: BaseGeometry, limit: float) -> tuple[BaseGeometry, BaseGeometry]:
    """Areas thinner than ``limit`` (strokes) and gaps narrower than it.

    Morphological opening/closing with a disc of the nozzle width; tiny
    slivers at sharp corners are ignored.
    """
    if g.is_empty or limit <= 0:
        return Polygon(), Polygon()
    r = limit / 2
    min_area = 0.5 * limit * limit
    opened = g.buffer(-r, quad_segs=6).buffer(r, quad_segs=6)
    thin = _significant(g.difference(opened), min_area)
    closed = g.buffer(r, quad_segs=6).buffer(-r, quad_segs=6)
    gaps = _significant(closed.difference(g), min_area)
    return thin, gaps


# ---------------------------------------------------------------------------


def layout_card(t: Template, printer: Printer, row: dict[str, str], index: int = 0,
                total: int = 0, check_print: bool = True) -> CardLayout:
    c = t.card
    base_z = printer.snap_base(c.thickness)
    outline = card_outline(c.width, c.height, c.corner_radius)
    hole = hole_shape(t)
    lay = CardLayout(c.width, c.height, base_z, outline, hole)

    bands = height_bands(t, printer)
    band_of = {round(b.z_top, 4): b.index for b in bands}

    lay.features.append(Feature("Card", "base", outline.difference(hole), 0.0, base_z, 0))

    border = border_shape(t, outline, hole)
    if not border.is_empty:
        z1 = round(base_z + printer.snap_relief(t.border.height), 4)
        lay.features.append(Feature("Border", "border", border, base_z, z1, band_of.get(z1, 1)))

    safe = box(c.padding, c.padding, c.width - c.padding, c.height - c.padding)
    solid = outline.difference(hole)
    placed: list[tuple[str, BaseGeometry]] = []
    limit = printer.feature_limit
    thin_parts, gap_parts = [], []

    for i, slot in enumerate(t.slots):
        if not slot.enabled:
            continue
        content = tx.render(slot.text, row, index, total)
        if not content:
            if slot.text.strip():
                lay.issues.append(Issue("info", "empty for this card", slot.name))
            continue
        if not lay.label:
            lay.label = tx.kanji(content)
        try:
            laid = lay_slot(slot, t, content)
        except fonts.FontError as e:
            lay.issues.append(Issue("error", str(e), slot.name))
            continue
        lay.issues.extend(laid.issues)
        g = laid.geom
        if g.is_empty:
            continue
        lay.boxes.append(SlotBox(i, g.bounds, content, laid.size, laid.lines))
        if laid.size < slot.size - 0.01:
            lay.issues.append(Issue("info", f"shrunk to {laid.size:.1f} mm to fit", slot.name))

        if not g.within(outline):
            lay.issues.append(Issue("error", "runs off the edge of the card", slot.name))
        elif not g.within(safe):
            lay.issues.append(Issue("warning", "extends into the padding", slot.name))
        if not hole.is_empty and g.intersects(hole):
            lay.issues.append(Issue("warning", "is cut by the hole", slot.name))
        if not border.is_empty and g.intersects(border):
            lay.issues.append(Issue("warning", "touches the border", slot.name))
        for other, og in placed:
            if g.intersects(og):
                lay.issues.append(Issue("warning", f"overlaps {other}", slot.name))
        placed.append((slot.name, g))

        g = g.intersection(solid)
        z1 = round(base_z + printer.snap_relief(slot.height), 4)
        lay.features.append(Feature(slot.name, "slot", g, base_z, z1, band_of.get(z1, 1), i))

        if check_print:
            thin, gaps = print_problems(g, limit)
            if not thin.is_empty:
                thin_parts.append(thin)
                frac = thin.area / max(g.area, 1e-9)
                if frac > 0.03:
                    lay.issues.append(Issue(
                        "warning", f"{frac:.0%} of strokes are thinner than {limit:.2f} mm "
                        "(try a bolder font or bigger size)", slot.name))
            if not gaps.is_empty:
                gap_parts.append(gaps)
                frac = gaps.area / max(g.area, 1e-9)
                if frac > 0.05:
                    lay.issues.append(Issue(
                        "warning", f"gaps narrower than {limit:.2f} mm may fill in", slot.name))

    if check_print:
        if not border.is_empty and t.border.width < limit:
            lay.issues.append(Issue("warning", f"border is thinner than {limit:.2f} mm", "Border"))
        lay.thin = unary_union(thin_parts) if thin_parts else Polygon()
        lay.gaps = unary_union(gap_parts) if gap_parts else Polygon()
    if not lay.label:
        lay.label = f"card {index + 1}"
    return lay
