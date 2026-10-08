"""Font discovery and glyph outlines.

Fonts are referred to as ``"Family:Style"`` (e.g. ``"Noto Sans CJK JP:Bold"``)
or by a path to a font file (optionally ``path#index`` for a face inside a
``.ttc`` collection). Glyph outlines come straight from the font with
fontTools and are flattened into shapely polygons in millimetres, so the
preview, the checks and the printed mesh all use the exact same shapes.
"""

from __future__ import annotations

import functools
import math
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTCollection, TTFont
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}


@dataclass(frozen=True)
class FontRef:
    family: str
    style: str
    path: str
    index: int = 0

    @property
    def key(self) -> str:
        return f"{self.family}:{self.style}"


class FontRegistry:
    """Index of installed fonts (fontconfig when available, else a dir scan)."""

    def __init__(self) -> None:
        self._fonts: dict[str, FontRef] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            refs = _fc_list() if shutil.which("fc-list") else []
            if not refs:
                refs = _scan_dirs()
            for r in refs:
                self._fonts.setdefault(r.key.lower(), r)
            for r in _bundled():
                self._fonts.setdefault(r.key.lower(), r)
            self._loaded = True

    def all(self) -> list[FontRef]:
        self._load()
        return sorted(self._fonts.values(), key=lambda r: (r.family.lower(), r.style.lower()))

    def families(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self.all():
            out.setdefault(r.family, []).append(r.style)
        return out

    def resolve(self, spec: str) -> FontRef | None:
        """Find a font by ``Family:Style``, ``Family`` or file path."""
        self._load()
        spec = spec.strip()
        path, _, idx = spec.partition("#")
        if os.sep in path or Path(path).suffix.lower() in FONT_EXTS:
            p = Path(path).expanduser()
            if p.exists():
                return FontRef(p.stem, "", str(p), int(idx or 0))
            return None
        fam, _, style = spec.partition(":")
        hit = self._fonts.get(f"{fam}:{style}".lower())
        if hit:
            return hit
        # Same family, closest style: exact family with Regular/Bold fallbacks.
        cands = [r for r in self._fonts.values() if r.family.lower() == fam.lower()]
        if not cands:
            return None
        for want in (style, "Regular", "Book", "Medium", "Bold"):
            for r in cands:
                if r.style.lower() == want.lower():
                    return r
        return cands[0]


def _fc_list() -> list[FontRef]:
    try:
        out = subprocess.run(
            ["fc-list", "--format", "%{file}|%{index}|%{family[0]}|%{style[0]}\n"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    refs = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        path, index, family, style = parts
        if Path(path).suffix.lower() not in FONT_EXTS or not family:
            continue
        refs.append(FontRef(family, style or "Regular", path, int(index or 0)))
    return refs


def _font_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        return [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                home / "AppData/Local/Microsoft/Windows/Fonts"]
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library/Fonts"]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
            home / ".local/share/fonts", home / ".fonts"]


def _faces_in(path: Path) -> list[FontRef]:
    refs = []
    try:
        if path.suffix.lower() in {".ttc", ".otc"}:
            fonts = TTCollection(str(path), lazy=True).fonts
        else:
            fonts = [TTFont(str(path), lazy=True)]
        for i, f in enumerate(fonts):
            name = f["name"]
            family = name.getBestFamilyName() or path.stem
            style = name.getBestSubFamilyName() or "Regular"
            refs.append(FontRef(family, style, str(path), i))
    except Exception:  # broken or unsupported font files are simply skipped
        pass
    return refs


def _scan_dirs() -> list[FontRef]:
    refs = []
    for d in _font_dirs():
        if d.exists():
            for p in d.rglob("*"):
                if p.suffix.lower() in FONT_EXTS:
                    refs.extend(_faces_in(p))
    return refs


def _bundled() -> list[FontRef]:
    d = Path(__file__).parent / "fonts"
    refs = []
    if d.exists():
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in FONT_EXTS:
                refs.extend(_faces_in(p))
    return refs


registry = FontRegistry()


# ---------------------------------------------------------------------------
# Glyph outlines


class _FlattenPen(BasePen):
    """Collect glyph contours as polylines, flattening curves."""

    def __init__(self, glyphset, tolerance: float) -> None:
        super().__init__(glyphset)
        self.tol = tolerance
        self.contours: list[list[tuple[float, float]]] = []
        self._cur: list[tuple[float, float]] = []

    def _moveTo(self, pt):
        self._cur = [pt]

    def _lineTo(self, pt):
        self._cur.append(pt)

    def _steps(self, *pts) -> int:
        length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        return max(2, min(24, math.ceil(length / self.tol)))

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        n = self._steps(p0, p1, p2, p3)
        for i in range(1, n + 1):
            t = i / n
            mt = 1 - t
            self._cur.append((
                mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
                mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1],
            ))

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        n = self._steps(p0, p1, p2)
        for i in range(1, n + 1):
            t = i / n
            mt = 1 - t
            self._cur.append((
                mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1],
            ))

    def _closePath(self):
        if len(self._cur) >= 3:
            self.contours.append(self._cur)
        self._cur = []

    _endPath = _closePath


def _contours_to_geometry(contours: list[list[tuple[float, float]]]) -> BaseGeometry:
    """Apply the non-zero fill rule using contour direction and nesting.

    Contours are processed from largest to smallest; ones wound like the
    outermost contour add area, the others cut it away. This handles nested
    shapes (e.g. 回) and overlapping contours in variable fonts.
    """
    polys = []
    for c in contours:
        p = Polygon(c)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty or p.area <= 0:
            continue
        signed = _signed_area(c)
        polys.append((abs(signed), signed > 0, p))
    if not polys:
        return Polygon()
    polys.sort(key=lambda t: -t[0])
    outer_dir = polys[0][1]
    geom: BaseGeometry = Polygon()
    for _, ccw, p in polys:
        geom = geom.union(p) if ccw == outer_dir else geom.difference(p)
    return geom


def _signed_area(c) -> float:
    a = 0.0
    for (x1, y1), (x2, y2) in zip(c, c[1:] + c[:1]):
        a += x1 * y2 - x2 * y1
    return a / 2


class Face:
    """A loaded font face with cached glyph outlines (in font units)."""

    def __init__(self, ref: FontRef) -> None:
        self.ref = ref
        if ref.path.lower().endswith((".ttc", ".otc")):
            self.font = TTFont(ref.path, fontNumber=ref.index, lazy=True)
        else:
            self.font = TTFont(ref.path, lazy=True)
        self.cmap = self.font.getBestCmap() or {}
        self.upem = self.font["head"].unitsPerEm
        self.glyphset = self.font.getGlyphSet()
        self.hmtx = self.font["hmtx"]
        os2 = self.font["OS/2"] if "OS/2" in self.font else None
        if os2 is not None and os2.sTypoAscender:
            self.ascender, self.descender = os2.sTypoAscender, os2.sTypoDescender
        else:
            hhea = self.font["hhea"]
            self.ascender, self.descender = hhea.ascent, hhea.descent
        self._outlines: dict[str, BaseGeometry] = {}
        self._lock = threading.Lock()

    def has(self, ch: str) -> bool:
        return ord(ch) in self.cmap

    def advance(self, ch: str) -> float:
        """Advance width in font units."""
        name = self.cmap.get(ord(ch))
        if name is None:
            return self.upem * 0.5
        return self.hmtx[name][0]

    def outline(self, ch: str) -> BaseGeometry:
        """Glyph shape in font units (y up, origin on the baseline)."""
        name = self.cmap.get(ord(ch))
        if name is None:
            return Polygon()
        with self._lock:
            g = self._outlines.get(name)
            if g is None:
                pen = _FlattenPen(self.glyphset, tolerance=self.upem / 160)
                self.glyphset[name].draw(pen)
                g = _contours_to_geometry(pen.contours)
                self._outlines[name] = g
        return g

    @property
    def mid(self) -> float:
        """Vertical centre of the em box, in font units above the baseline."""
        return (self.ascender + self.descender) / 2


@functools.lru_cache(maxsize=64)
def _load_face(ref: FontRef) -> Face:
    return Face(ref)


class FontError(LookupError):
    pass


def face(spec: str) -> Face:
    ref = registry.resolve(spec)
    if ref is None:
        raise FontError(f"Font not found: {spec!r}")
    return _load_face(ref)


def try_face(spec: str) -> Face | None:
    try:
        return face(spec)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Text runs


@dataclass
class Run:
    """A single line of shaped text, measured in mm at a given size."""

    glyphs: list[tuple[Face, str, float]]  # (face, char, x position in mm)
    width: float
    size: float
    primary: Face
    missing: list[str]

    def geometry(self) -> BaseGeometry:
        """Glyph shapes in mm, baseline at y=0, starting at x=0."""
        parts = []
        for f, ch, x in self.glyphs:
            g = f.outline(ch)
            if g.is_empty:
                continue
            s = self.size / f.upem
            parts.append(affinity.affine_transform(g, [s, 0, 0, s, x, 0]))
        if not parts:
            return Polygon()
        return unary_union(parts)

    @property
    def mid(self) -> float:
        """Vertical centre of the line in mm above the baseline."""
        return self.primary.mid * self.size / self.primary.upem


def shape(text: str, primary: Face, fallbacks: list[Face], size: float,
          letter_spacing: float = 0.0) -> Run:
    """Lay out ``text`` on one line, picking a font per character."""
    x = 0.0
    glyphs = []
    missing = []
    chars = [c for c in text if c not in "\r\n"]
    for i, ch in enumerate(chars):
        f = primary
        if not primary.has(ch) and not ch.isspace():
            f = next((fb for fb in fallbacks if fb.has(ch)), None)
            if f is None:
                missing.append(ch)
                f = primary
        glyphs.append((f, ch, x))
        x += f.advance(ch) * size / f.upem
        if i < len(chars) - 1:
            x += letter_spacing
    return Run(glyphs, x, size, primary, missing)


def to_multipolygon(g: BaseGeometry) -> MultiPolygon:
    if g.is_empty:
        return MultiPolygon()
    if isinstance(g, Polygon):
        return MultiPolygon([g])
    if isinstance(g, MultiPolygon):
        return g
    polys = [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon) and not p.is_empty]
    return MultiPolygon(polys)
