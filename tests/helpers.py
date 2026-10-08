"""Helpers shared by test modules (import as ``from helpers import ...``)."""

from __future__ import annotations

from cardsmith.model import Border, Card, Hole, Slot, Template

CJK_FONT = "Noto Sans CJK JP:Bold"


def simple_template(**slot_kw) -> Template:
    """A one-slot template with no border or hole."""
    kw = {"name": "Word", "text": "{word}", "font": CJK_FONT, "size": 10.0, "y": 43.0}
    kw.update(slot_kw)
    return Template(
        name="Test",
        card=Card(width=54, height=86, thickness=1.2, corner_radius=3, padding=3),
        border=Border(enabled=False),
        hole=Hole(enabled=False),
        slots=[Slot(**kw)],
        fallback_fonts=[CJK_FONT],
    )
