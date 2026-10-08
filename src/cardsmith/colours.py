"""Friendly names for filament colours, and palette presets."""

from __future__ import annotations

# Common filament colours (roughly what spools are sold as).
NAMED = {
    "White": "#F5F5F2",
    "Cream": "#F4EFE6",
    "Ivory": "#EDE3CC",
    "Beige": "#D9C7A7",
    "Light grey": "#BFC2C4",
    "Grey": "#8A8D91",
    "Dark grey": "#4A4D52",
    "Black": "#1A1A1A",
    "Ink blue": "#1F2A44",
    "Navy": "#1C2E5A",
    "Blue": "#1F5FBF",
    "Sky blue": "#5FB2E8",
    "Teal": "#13837E",
    "Mint": "#9FE0C4",
    "Green": "#2E7D32",
    "Matcha": "#8DA563",
    "Olive": "#6B6B2A",
    "Yellow": "#F9D423",
    "Gold": "#C9A227",
    "Orange": "#F57C1F",
    "Red": "#C0392B",
    "Vermilion": "#E0533D",
    "Sakura pink": "#F4B6C2",
    "Pink": "#E85D9A",
    "Magenta": "#B0277A",
    "Purple": "#6A1B9A",
    "Lavender": "#B4A7D6",
    "Brown": "#6D4C35",
    "Wood": "#A67B5B",
    "Silver": "#B8BCC2",
}

PALETTES: dict[str, list[str]] = {
    "Washi (cream · red · ink)": ["#F4EFE6", "#C0392B", "#1F2A44"],
    "Sumi (white · black)": ["#F5F5F2", "#1A1A1A", "#1A1A1A"],
    "Night (black · gold · white)": ["#1A1A1A", "#C9A227", "#F5F5F2"],
    "Matcha (cream · green · brown)": ["#F4EFE6", "#8DA563", "#6D4C35"],
    "Sakura (white · pink · grey)": ["#F5F5F2", "#F4B6C2", "#4A4D52"],
    "Ocean (white · teal · navy)": ["#F5F5F2", "#13837E", "#1C2E5A"],
    "Arcade (navy · orange · yellow)": ["#1C2E5A", "#F57C1F", "#F9D423"],
    "Classroom (yellow · black)": ["#F9D423", "#1A1A1A", "#1A1A1A"],
}


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def colour_name(hex_colour: str) -> str:
    """Nearest friendly name, e.g. ``#C1392C`` → ``Red``."""
    try:
        r, g, b = _rgb(hex_colour)
    except ValueError:
        return hex_colour
    best, dist = hex_colour, 1e18
    for name, h in NAMED.items():
        r2, g2, b2 = _rgb(h)
        # Weighted RGB distance ("redmean"), good enough for naming.
        rm = (r + r2) / 2
        d = (2 + rm / 256) * (r - r2) ** 2 + 4 * (g - g2) ** 2 + (2 + (255 - rm) / 256) * (b - b2) ** 2
        if d < dist:
            best, dist = name, d
    return best
