"""Command line interface.

    cardsmith                         open the app
    cardsmith build deck.tsv -t kanji -p "Bambu Lab A1" -o out/
    cardsmith check deck.tsv -t my-template.toml
    cardsmith printers | templates | fonts --ja
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _printer(args):
    from .model import Printer
    from .settings import find_printer

    p = find_printer(args.printer) if args.printer else None
    if args.printer and p is None:
        sys.exit(f"Unknown printer {args.printer!r}. Run `cardsmith printers` to list them.")
    p = p or Printer()
    if args.bed:
        try:
            w, d = (float(v) for v in args.bed.lower().replace("×", "x").split("x"))
        except ValueError:
            sys.exit("--bed must look like 220x220")
        p.bed_width, p.bed_depth = w, d
        p.name = f"Custom {w:g} × {d:g}"
    overrides = {a: getattr(args, a, None) for a in ("margin", "gap", "nozzle", "layer_height", "first_layer_height")}
    overrides = {k: v for k, v in overrides.items() if v is not None}
    if overrides:
        p = Printer.from_dict({**p.to_dict(), **overrides})  # validates the new values
    return p


def _deck_rows(args):
    from .data import load_deck

    deck = load_deck(args.deck, has_header={"auto": None, "yes": True, "no": False}[args.header])
    rows = deck.selected()
    if args.limit is not None:
        rows = rows[: max(0, args.limit)]
    return deck, rows


def _warn_missing_columns(template, deck) -> None:
    from .text import fields_in

    cols = {c.lower() for c in deck.columns}
    missing = sorted({f for s in template.slots if s.enabled for f in fields_in(s.text)
                      if f not in ("#", "##") and f.lower() not in cols})
    if missing:
        print(f"warning: the deck has no {', '.join(missing)} column(s); those lines will be blank. "
              f"Columns: {', '.join(deck.columns)}", file=sys.stderr)


def cmd_build(args) -> int:
    from .export import ExportOptions, cura_steps, export_deck
    from .settings import resolve_template

    template = resolve_template(args.template)
    printer = _printer(args)
    deck, rows = _deck_rows(args)
    _warn_missing_columns(template, deck)
    out = Path(args.out or f"{deck.name}-cards")
    opts = ExportOptions(
        plates_3mf=not args.no_plates,
        plates_colour_3mf=not args.no_plates and not args.no_colour_3mf,
        plates_stl=args.stl,
        singles_stl=args.singles,
        singles_3mf=args.singles_3mf,
    )

    def progress(f: float, msg: str) -> None:
        bar = "█" * int(f * 30)
        print(f"\r  [{bar:<30}] {msg:<40}", end="", file=sys.stderr, flush=True)

    res = export_deck(template, printer, rows, out, opts, progress if sys.stderr.isatty() else None,
                      total_arg=len(deck))
    if sys.stderr.isatty():
        print(file=sys.stderr)
    print(f"✓ {res.cards} cards → {res.plates} plate(s), {res.per_plate} per plate, in {res.seconds:.1f}s")
    print(f"  Output: {res.out_dir.resolve()}")
    if res.problem_cards:
        print(f"  ⚠ {len(res.problem_cards)} card(s) have layout warnings – see PRINT_GUIDE.md")
    print()
    print(cura_steps(template, printer))
    return 0


def cmd_check(args) -> int:
    from .layout import layout_card
    from .settings import resolve_template

    template = resolve_template(args.template)
    printer = _printer(args)
    deck, rows = _deck_rows(args)
    _warn_missing_columns(template, deck)
    bad = 0
    for idx, row in rows:
        lay = layout_card(template, printer, row, idx, len(deck), check_print=not args.fast)
        issues = [i for i in lay.issues if i.level != "info" or args.verbose]
        if issues:
            bad += 1
            print(f"#{idx + 1} {lay.label}")
            for i in issues:
                print(f"   {i.level:7} {i}")
    print(f"{len(rows) - bad} of {len(rows)} cards look fine.")
    return 1 if bad else 0


def cmd_printers(args) -> int:
    from .settings import load_printers

    for p in load_printers():
        print(f"{p.name:32} {p.bed_width:g} × {p.bed_depth:g} mm")
    return 0


def cmd_templates(args) -> int:
    from .settings import builtin_templates

    for name, path in builtin_templates().items():
        print(f"{name:20} {path}")
    return 0


def cmd_fonts(args) -> int:
    from . import fonts

    for ref in fonts.registry.all():
        if args.ja:
            try:
                if not fonts.face(ref.key).has("あ"):
                    continue
            except Exception:
                continue
        print(f"{ref.key:50} {ref.path}")
    return 0


def cmd_doctor(args) -> int:
    """Check the things Cardsmith needs, and say how to fix what's missing."""
    import platform
    from importlib import metadata

    from . import fonts, settings, slicer

    problems = 0

    def line(ok: bool | None, what: str, detail: str = "") -> None:
        nonlocal problems
        mark = {True: "✓", False: "✗", None: "–"}[ok]
        problems += ok is False
        print(f" {mark} {what:<22} {detail}")

    print(f"Cardsmith {__version__} on Python {platform.python_version()} ({platform.system()})\n")
    line(sys.version_info >= (3, 11), "Python 3.11+", platform.python_version())
    for pkg in ("fonttools", "shapely", "manifold3d", "numpy", "tomli-w"):
        try:
            line(True, pkg, metadata.version(pkg))
        except metadata.PackageNotFoundError:
            line(False, pkg, f"missing – pip install {pkg}")
    try:
        import PySide6

        line(True, "PySide6 (the app)", PySide6.__version__)
    except ImportError:
        line(None, "PySide6 (the app)", "not installed – command line only. pip install 'cardsmith[gui]'")

    n_fonts = len(fonts.registry.all())
    line(n_fonts > 0, "Fonts", f"{n_fonts} found" if n_fonts else "none found – install some fonts")
    template = settings.default_template()
    for spec in dict.fromkeys(s.font for s in template.slots):
        ok = fonts.try_face(spec) is not None
        line(ok, "Default template font", spec if ok else f"{spec} not found – install Noto Sans CJK JP "
             "(fonts-noto-cjk / noto-fonts-cjk) or pick another font in the app")
    ja = next((r.key for r in fonts.registry.all() if "CJK JP" in r.family), None)
    line(True if ja else None, "Japanese font", ja or "none – only needed for Japanese text")

    cura = slicer.find_cura()
    line(True if cura else None, "Cura", " ".join(cura) if cura else
         "not found – only needed for 'Open in Cura'. Set CARDSMITH_CURA=/path/to/cura")
    cfg = "the settings folder"
    try:
        cfg = settings.config_dir()
        probe = cfg / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        line(True, "Settings folder", str(cfg))
    except OSError as e:
        line(False, "Settings folder", f"{cfg} is not writable ({e})")

    print("\nAll good." if not problems else f"\n{problems} problem{'s' if problems != 1 else ''} found.")
    return 1 if problems else 0


def cmd_gui(args) -> int:
    try:
        from .gui.app import main as gui_main
    except ImportError as e:
        sys.exit(f"The app needs PySide6: pip install 'cardsmith[gui]'  ({e})")
    return gui_main([sys.argv[0], *([args.deck] if getattr(args, "deck", None) else [])])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cardsmith", description="3D-printable flashcards from spreadsheets.")
    ap.add_argument("--version", action="version", version=f"cardsmith {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    def deck_args(p):
        p.add_argument("deck", help="CSV / TSV / Anki export / JSON file")
        p.add_argument("-t", "--template", default="kanji", help="template file or built-in name")
        p.add_argument("-p", "--printer", help="printer profile name (see `cardsmith printers`)")
        p.add_argument("--bed", help="custom bed size, e.g. 235x235")
        p.add_argument("--margin", type=float)
        p.add_argument("--gap", type=float)
        p.add_argument("--nozzle", type=float)
        p.add_argument("--layer-height", dest="layer_height", type=float)
        p.add_argument("--first-layer-height", dest="first_layer_height", type=float)
        p.add_argument("--header", choices=["auto", "yes", "no"], default="auto")
        p.add_argument("--limit", type=int, help="only the first N cards")

    b = sub.add_parser("build", help="export plates / cards")
    deck_args(b)
    b.add_argument("-o", "--out", help="output folder")
    b.add_argument("--singles", action="store_true", help="also write one STL per card")
    b.add_argument("--singles-3mf", action="store_true", help="also write one 3MF per card")
    b.add_argument("--stl", action="store_true", help="also write plate STLs")
    b.add_argument("--no-plates", action="store_true")
    b.add_argument("--no-colour-3mf", action="store_true", help="skip per-colour plate 3MFs")
    b.set_defaults(fn=cmd_build)

    c = sub.add_parser("check", help="report layout and printability problems")
    deck_args(c)
    c.add_argument("--fast", action="store_true", help="skip stroke-width analysis")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(fn=cmd_check)

    sub.add_parser("printers", help="list printer profiles").set_defaults(fn=cmd_printers)
    sub.add_parser("templates", help="list built-in templates").set_defaults(fn=cmd_templates)
    f = sub.add_parser("fonts", help="list installed fonts")
    f.add_argument("--ja", action="store_true", help="only fonts with Japanese glyphs")
    f.set_defaults(fn=cmd_fonts)
    sub.add_parser("doctor", help="check fonts, the app and Cura are set up").set_defaults(fn=cmd_doctor)
    g = sub.add_parser("gui", help="open the app (default)")
    g.add_argument("deck", nargs="?")
    g.set_defaults(fn=cmd_gui)

    args = ap.parse_args(argv)
    if not args.cmd:
        return cmd_gui(args)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    sys.exit(main())
