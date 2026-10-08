"""Build print-ready files for a whole deck."""

from __future__ import annotations

import csv
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import mesh as ms
from . import plate as pl
from .layout import CardLayout, layout_card
from .model import ColourChange, Printer, Template, colour_changes, height_bands


@dataclass
class ExportOptions:
    plates_3mf: bool = True  # one merged object per plate (manual filament swaps)
    plates_colour_3mf: bool = True  # one object per colour (multi-material printers)
    plates_stl: bool = False
    singles_stl: bool = False
    singles_3mf: bool = False


@dataclass
class ExportResult:
    out_dir: Path
    files: list[Path] = field(default_factory=list)
    plates: int = 0
    cards: int = 0
    per_plate: int = 0
    changes: list[ColourChange] = field(default_factory=list)
    problem_cards: list[tuple[int, str, str]] = field(default_factory=list)
    guide: Path | None = None
    seconds: float = 0.0


class Cancelled(Exception):
    pass


Progress = Callable[[float, str], None]


def safe_name(s: str, limit: int = 40) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("._")
    return s[:limit] or "card"


def card_bands(lay: CardLayout) -> dict[int, ms.mf.Manifold]:
    """Solids of one card grouped by colour band, in the card's own frame."""
    groups: dict[int, list] = {}
    for f in lay.features:
        groups.setdefault(f.band, []).append(ms.extrude(f.geom, f.z0, f.z1))
    return {b: ms.union(parts) for b, parts in groups.items()}


def card_solid(lay: CardLayout) -> ms.mf.Manifold:
    return ms.union(list(card_bands(lay).values()))


def export_deck(
    template: Template,
    printer: Printer,
    rows: list[tuple[int, dict[str, str]]],
    out_dir: str | Path,
    options: ExportOptions | None = None,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExportResult:
    t0 = time.monotonic()
    options = options or ExportOptions()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = ExportResult(out)
    say = progress or (lambda f, m: None)

    def check():
        if cancelled and cancelled():
            raise Cancelled()

    total = len(rows)
    if total == 0:
        raise ValueError("No cards selected to export.")
    packing = pl.pack(template.card.width, template.card.height, printer)
    if packing.capacity == 0:
        raise ValueError(
            f"A {template.card.width:g} × {template.card.height:g} mm card does not fit on a "
            f"{printer.bed_width:g} × {printer.bed_depth:g} mm bed with a {printer.margin:g} mm margin."
        )
    bands = height_bands(template, printer)
    res.changes = colour_changes(template, printer)
    res.cards = total
    res.per_plate = packing.capacity

    # 1. Lay out every card (quick: no stroke analysis).
    layouts: list[tuple[int, CardLayout]] = []
    for n, (idx, row) in enumerate(rows):
        check()
        lay = layout_card(template, printer, row, idx, len(rows), check_print=False)
        layouts.append((idx, lay))
        bad = [i for i in lay.issues if i.level in ("error", "warning")]
        if bad:
            res.problem_cards.append((idx, lay.label, "; ".join(map(str, bad))))
        say(0.15 * (n + 1) / total, f"Laying out card {n + 1} of {total}")

    # 2. Plates.
    chunks = pl.chunk(total, packing.capacity)
    res.plates = len(chunks)
    manifest = [("card", "label", "plate", "position", "x_mm", "y_mm", "rotated")]
    want_plates = options.plates_3mf or options.plates_colour_3mf or options.plates_stl
    w_plates = 0.7 if (options.singles_stl or options.singles_3mf) else 0.85
    plates_dir = out / "plates"
    if want_plates:
        plates_dir.mkdir(exist_ok=True)
    for p, rng in enumerate(chunks, start=1):
        by_band: dict[int, list] = {}
        for k, li in enumerate(rng):
            check()
            idx, lay = layouts[li]
            slot = packing.slots[k]
            manifest.append((idx + 1, lay.label, p, k + 1, slot.x, slot.y, int(slot.rotated)))
            if want_plates:
                for b, solid in card_bands(lay).items():
                    by_band.setdefault(b, []).append(
                        ms.place(solid, slot.x, slot.y, slot.rotated, template.card.height))
            say(0.15 + w_plates * (p - 1 + (k + 1) / len(rng)) / len(chunks),
                f"Building plate {p} of {len(chunks)}")
        if not want_plates:
            continue
        band_solids = {b: ms.union(parts) for b, parts in by_band.items()}
        stem = f"plate_{p:02d}"
        if options.plates_3mf or options.plates_stl:
            merged = ms.MeshData.of(ms.union(list(band_solids.values())))
            if options.plates_3mf:
                f = plates_dir / f"{stem}.3mf"
                ms.write_3mf(f, [(f"Plate {p}", merged, None)], f"{template.name} – plate {p}")
                res.files.append(f)
            if options.plates_stl:
                f = plates_dir / f"{stem}.stl"
                ms.write_stl(f, merged, f"{template.name} plate {p}")
                res.files.append(f)
        if options.plates_colour_3mf:
            objs = []
            for b in sorted(band_solids):
                band = bands[b] if b < len(bands) else None
                label = ", ".join(band.features) if band else f"band {b}"
                colour = band.colour if band else None
                objs.append((f"Colour {b + 1} – {label}", ms.MeshData.of(band_solids[b]), colour))
            f = plates_dir / f"{stem}_colours.3mf"
            ms.write_3mf(f, objs, f"{template.name} – plate {p} (per colour)")
            res.files.append(f)

    # 3. Single cards.
    if options.singles_stl or options.singles_3mf:
        cards_dir = out / "cards"
        cards_dir.mkdir(exist_ok=True)
        for n, (idx, lay) in enumerate(layouts):
            check()
            stem = f"{idx + 1:03d}_{safe_name(lay.label)}"
            bands_solid = card_bands(lay)
            if options.singles_stl:
                f = cards_dir / f"{stem}.stl"
                ms.write_stl(f, ms.MeshData.of(ms.union(list(bands_solid.values()))), lay.label)
                res.files.append(f)
            if options.singles_3mf:
                f = cards_dir / f"{stem}.3mf"
                objs = [(f"Colour {b + 1}", ms.MeshData.of(s), bands[b].colour if b < len(bands) else None)
                        for b, s in sorted(bands_solid.items())]
                ms.write_3mf(f, objs, lay.label)
                res.files.append(f)
            say(0.15 + w_plates + (1 - 0.15 - w_plates) * (n + 1) / total,
                f"Writing card {n + 1} of {total}")

    # 4. Paperwork.
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(manifest)
    res.files.append(out / "manifest.csv")
    template.save(out / "template.toml")
    res.files.append(out / "template.toml")
    res.seconds = time.monotonic() - t0
    guide = out / "PRINT_GUIDE.md"
    guide.write_text(print_guide(template, printer, res, packing), encoding="utf-8")
    res.guide = guide
    res.files.append(guide)
    say(1.0, "Done")
    return res


# ---------------------------------------------------------------------------
# Human instructions


def colour_plan_lines(template: Template, printer: Printer) -> list[str]:
    bands = height_bands(template, printer)
    changes = {c.band: c for c in colour_changes(template, printer)}
    lines = [f"Start with **{bands[0].colour}** – card base, layers 1–"
             f"{printer.layers_below(bands[0].z_top)} (0 – {bands[0].z_top:g} mm)"]
    for b in bands[1:]:
        what = ", ".join(b.features)
        c = changes.get(b.index)
        if c:
            lines.append(f"Layer **{c.layer}** (z = {c.z:g} mm): swap to **{b.colour}** – {what} "
                         f"(up to {b.z_top:g} mm)")
        else:
            lines.append(f"{what} (up to {b.z_top:g} mm) keeps the same colour – no swap")
    return lines


def cura_steps(template: Template, printer: Printer) -> str:
    changes = colour_changes(template, printer)
    layers = ",".join(str(c.layer) for c in changes)
    if not changes:
        return "All parts use one colour, so no filament change is needed."
    return f"""\
1. Open the plate's `.3mf` in Cura. In print settings set **Layer Height = {printer.layer_height:g} mm**,
   **Initial Layer Height = {printer.first_layer_height:g} mm** and make sure **Adaptive Layers is off**
   – otherwise the layer numbers below no longer line up.
2. **Extensions → Post Processing → Modify G-Code → Add a script → Filament Change**.
3. Set **Layer** to `{layers}` (one script handles a comma-separated list).
   Keep *Use Firmware Configuration* ticked if your printer supports `M600`
   (most Marlin and Klipper setups do). If it doesn't, use **Pause at height** with
   *Pause at: Layer Number* instead, once per layer.
4. Slice and open **Preview**: drag the layer slider to layer {changes[0].layer} – it should be the
   first layer of the raised parts.
5. At each change the printer parks and waits: swap the filament, push until the new colour runs
   clean, wipe the nozzle and resume."""


def print_guide(template: Template, printer: Printer, res: ExportResult, packing: pl.PlateLayout) -> str:
    plan = "\n".join(f"- {line}" for line in colour_plan_lines(template, printer))
    problems = ""
    if res.problem_cards:
        rows = "\n".join(f"| {i + 1} | {label} | {msg} |" for i, label, msg in res.problem_cards[:200])
        problems = f"\n## Cards to double-check\n\n| # | Card | Issue |\n|---|---|---|\n{rows}\n"
    files = "\n".join(f"- `{f.relative_to(res.out_dir)}`" for f in res.files)
    c = template.card
    return f"""\
# {template.name} – print guide

Generated by Cardsmith for **{printer.name}** ({printer.bed_width:g} × {printer.bed_depth:g} mm bed).

- **{res.cards} cards** on **{res.plates} plate{'s' if res.plates != 1 else ''}**, up to
  {res.per_plate} per plate ({packing.description}).
- Card {c.width:g} × {c.height:g} mm, base {printer.snap_base(c.thickness):g} mm thick,
  layers {printer.layer_height:g} mm (first layer {printer.first_layer_height:g} mm).

## Colour plan (single nozzle, manual swaps)

{plan}

## Doing the colour change in Cura

{cura_steps(template, printer)}

## Multi-material printers (AMS, MMU, IDEX, tool changers)

Open `plate_XX_colours.3mf` instead: every colour is its own object, already aligned.
Assign an extruder/filament to each object, then select them all and **Group** (Ctrl+G) so they
move together. No filament-change script is needed.

## Other slicers

PrusaSlicer, OrcaSlicer and Bambu Studio open the same `.3mf` files. For manual swaps,
drag the layer slider in the preview to the layer above and click **+** to add a colour change.
{problems}
## Files

{files}

`manifest.csv` lists which card sits where on each plate.
"""
