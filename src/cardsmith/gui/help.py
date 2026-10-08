"""Built-in quick guide."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

GUIDE = """
# Cardsmith in one minute

1. **Open a deck** – any CSV/TSV, an Anki *Notes in Plain Text* export, or JSON. Every column becomes a
   field you can place on the card.
2. **Text tab** – each *slot* is a line of raised text. Set its text to `{column}` (use the **{ }** button),
   pick a font and size, and drag it around in the preview. Long text can shrink or wrap.
3. **Card tab** – size, thickness, rounded corners, a raised border and an optional hole for a ring.
4. **Colours tab** – pick filament colours for each height (see below).
5. **Printer tab** – your bed size and layer heights. Cardsmith packs as many cards per plate as fit,
   turning some sideways when that squeezes more in.
6. **Export** – you get plates ready for Cura (`plate_01.3mf` …), optional single-card files, and a
   `PRINT_GUIDE.md` with the exact filament-change layers.

## How the colours work

A card is printed flat, bottom-up. Everything is a stack of layers:

| Height | What's there | Colour |
|---|---|---|
| 0 – 1.2 mm | the card | colour 1 |
| 1.2 – 1.6 mm | border **and** the lower part of the text | colour 2 |
| 1.6 – 1.8 mm | only the top of the text | colour 3 |

Swap filament at the start of each band and, seen from above, the card, the border and the text each
show a different colour – with a single nozzle. Parts with the **same height share a colour**, so to
give two things different colours, give them different heights. The **Colours** tab shows the bands
and the layer numbers to use.

## Filament change in Cura

1. In Cura's print settings, set **Layer Height** and **Initial Layer Height** to the values on the
   Printer tab, and turn **Adaptive Layers** off.
2. **Extensions → Post Processing → Modify G-Code → Add a script → Filament Change**.
3. Type the layer numbers, comma-separated (e.g. `7,9`). Cardsmith shows them on the Colours tab and
   in the export window, where **Copy layer numbers** puts them on the clipboard.
4. Slice, then check **Preview**: drag the layer slider to the first number – it should be the first
   layer of the raised parts.

If your printer's firmware doesn't support `M600`, use the **Pause at height** script (by layer
number) instead. With an AMS / MMU / multi-extruder printer, open `plate_XX_colours.3mf` and give each
object its own filament instead – no script needed.

## Print tips

- Bold fonts print best. Strokes thinner than the nozzle show up **red** in the preview, gaps that may
  fill in show **orange**.
- Keep secondary text at 4–5 mm or bigger with a 0.4 mm nozzle.
- A textured PEI sheet gives the card a nice back; a smooth sheet gives a glossy one.
- Ironing (top surface only) makes the raised tops smoother.

## Text tricks

| Write | Shows |
|---|---|
| `{word}` | the *word* column |
| `{furigana\\|kanji}` | `漢字[かんじ]` → 漢字 |
| `{furigana\\|kana}` | `漢字[かんじ]` → かんじ |
| `{meaning\\|first}` | first item of `a; b; c` |
| `{#}` / `{##}` | card number / total |

Tick **Furigana** on a slot whose text uses `漢字[かんじ]` to put the readings above the kanji.
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cardsmith help")
        self.resize(720, 760)
        v = QVBoxLayout(self)
        t = QTextBrowser()
        t.setOpenExternalLinks(True)
        t.setMarkdown(GUIDE)
        v.addWidget(t)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        b.rejected.connect(self.reject)
        v.addWidget(b)
