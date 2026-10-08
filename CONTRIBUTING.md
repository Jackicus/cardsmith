# Contributing to Cardsmith

Thanks for helping! Bug reports, printer presets, templates and code are all welcome.

## Development setup

```sh
git clone https://github.com/Jackicus/cardsmith
cd cardsmith
python -m venv .venv
.venv/bin/pip install -e ".[gui,dev]"   # drop "gui" if you don't need the Qt app
```

Text rendering needs real fonts. The tests use **Noto Sans CJK JP Bold**; on Debian/Ubuntu:
`sudo apt-get install fonts-noto-cjk fontconfig`. Tests that need it are skipped if it is missing.

## Running checks

```sh
.venv/bin/ruff check src tests
.venv/bin/pytest -q
```

The whole suite runs in a few seconds. CI runs the same two commands on Python 3.11 and 3.13.
Tests must not import PySide6 – keep GUI code out of the engine modules.

## Project layout

| Path | What it does |
|---|---|
| `src/cardsmith/model.py` | `Template` / `Printer` dataclasses (TOML round-trip), layer snapping, colour bands, Cura layer numbers |
| `src/cardsmith/text.py` | Slot templates (`{field\|filter}`), Anki furigana, wrapping tokens |
| `src/cardsmith/fonts.py` | Font registry (fontconfig or directory scan) and glyph outlines → shapely |
| `src/cardsmith/layout.py` | One card's 2D geometry per height, layout issues, printability checks |
| `src/cardsmith/plate.py` | Packing cards onto the print bed |
| `src/cardsmith/mesh.py` | Extrusion with manifold3d, STL and 3MF writers |
| `src/cardsmith/export.py` | Whole-deck export: plates, single cards, manifest, print guide |
| `src/cardsmith/data.py` | Loading CSV / TSV / Anki exports / JSON |
| `src/cardsmith/settings.py`, `cli.py` | Saved printer profiles, built-in templates, command line |
| `src/cardsmith/gui/` | PySide6 app |
| `tests/` | pytest suite (`helpers.py` has shared builders, `conftest.py` the fixtures) |

## How templates work

1. A template (`templates/*.toml`) describes the card: size, thickness, border, hanging hole, and a list of **slots**.
2. Each slot is a line of text: `text = "{word|kanji}"` pulls the `word` column and applies filters; `{#}` / `{##}` are the card number / total.
3. Every slot (and the border) has a `height` above the card; heights are snapped to whole layers of the chosen printer.
4. Parts that end at the same height form a **colour band**; `palette` gives each band's colour, from the base upwards.
5. On export the bands become filament-change layer numbers (1-based, as shown in Cura's preview – the swap happens at the start of that layer) and per-colour 3MF objects.

## Pull requests

- Keep changes focused, and add a test for any bug you fix.
- Don't break the TOML format: unknown keys are ignored, so new fields need sensible defaults.
- Run ruff and pytest before pushing.
