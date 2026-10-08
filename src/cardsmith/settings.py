"""Per-user storage: saved printer profiles and resources."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

import tomli_w

from .model import PRINTER_PRESETS, Printer, Template

PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "cardsmith"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _printers_file() -> Path:
    return config_dir() / "printers.toml"


def load_printers() -> list[Printer]:
    """Saved printer profiles, followed by built-in presets not overridden."""
    saved: list[Printer] = []
    f = _printers_file()
    if f.exists():
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
            saved = [Printer.from_dict(d) for d in data.get("printer", [])]
        except (OSError, tomllib.TOMLDecodeError):
            saved = []
    names = {p.name for p in saved}
    return saved + [p for p in PRINTER_PRESETS if p.name not in names]


def save_printer(printer: Printer) -> None:
    f = _printers_file()
    existing = []
    if f.exists():
        try:
            existing = tomllib.loads(f.read_text(encoding="utf-8")).get("printer", [])
        except (OSError, tomllib.TOMLDecodeError):
            existing = []
    existing = [d for d in existing if d.get("name") != printer.name]
    existing.insert(0, printer.to_dict())
    f.write_text(tomli_w.dumps({"printer": existing}), encoding="utf-8")


def delete_printer(name: str) -> None:
    f = _printers_file()
    if not f.exists():
        return
    data = tomllib.loads(f.read_text(encoding="utf-8")).get("printer", [])
    f.write_text(tomli_w.dumps({"printer": [d for d in data if d.get("name") != name]}), encoding="utf-8")


def find_printer(name: str) -> Printer | None:
    for p in load_printers():
        if p.name.lower() == name.lower():
            return p
    for p in load_printers():
        if name.lower() in p.name.lower():
            return p
    return None


def builtin_templates() -> dict[str, Path]:
    return {p.stem: p for p in sorted(TEMPLATES_DIR.glob("*.toml"))}


def default_template() -> Template:
    p = TEMPLATES_DIR / "kanji.toml"
    return Template.load(p) if p.exists() else Template()


def resolve_template(spec: str) -> Template:
    """A path to a template file, or the name of a built-in one."""
    p = Path(spec).expanduser()
    if p.exists():
        return Template.load(p)
    builtin = builtin_templates()
    if spec in builtin:
        return Template.load(builtin[spec])
    raise FileNotFoundError(f"No template file or built-in template called {spec!r} "
                            f"(built-in: {', '.join(builtin) or 'none'})")
