"""Load decks from CSV / TSV / Anki "Notes in plain text" exports."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Deck:
    columns: list[str]
    rows: list[dict[str, str]]
    source: str = ""
    name: str = "deck"
    has_header: bool = True
    included: list[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.included) != len(self.rows):
            self.included = [True] * len(self.rows)

    def selected(self) -> list[tuple[int, dict[str, str]]]:
        return [(i, r) for i, r in enumerate(self.rows) if self.included[i]]

    def __len__(self) -> int:
        return len(self.rows)


def _sniff_delimiter(text: str, suffix: str) -> str:
    if suffix in (".tsv", ".tab"):
        return "\t"
    sample = "\n".join(text.splitlines()[:20])
    if sample.count("\t") >= max(1, sample.count("\n")):
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _looks_like_header(first: list[str], rest: list[list[str]]) -> bool:
    if not rest or not first:
        return True
    # Headers are short, mostly ASCII identifiers (duplicates are tolerated).
    ascii_like = sum(1 for c in first if c and c.isascii() and len(c) < 30)
    return ascii_like >= max(1, len(first) // 2 + 1) and not any(c.strip().isdigit() for c in first)


# Header lines Anki writes at the top of a "Notes in Plain Text" export.
ANKI_DIRECTIVES = {"separator", "html", "columns", "tags column", "notetype column", "deck column",
                   "guid column", "notetype", "deck", "tags"}


def _decode(raw: bytes) -> str:
    """UTF-8 (with or without BOM), UTF-16 from Excel's "Unicode Text", else Windows-1252."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _anki_directive(line: str) -> tuple[str, str] | None:
    if not line.startswith("#"):
        return None
    k, sep, v = line[1:].partition(":")
    k = k.strip().lower()
    return (k, v.strip()) if sep and k in ANKI_DIRECTIVES else None


def load_deck(path: str | Path, has_header: bool | None = None) -> Deck:
    p = Path(path)
    text = _decode(p.read_bytes())

    if p.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("cards", data.get("rows", []))
        if not isinstance(data, list) or not all(isinstance(i, dict) for i in data):
            raise ValueError("a JSON deck must be a list of objects, e.g. [{\"word\": \"日\"}, …]")
        rows = [{str(k): "" if v is None else str(v) for k, v in item.items()} for item in data]
        cols: list[str] = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        return Deck(cols, rows, str(p), p.stem, True)

    # Anki exports start with "#key:value" directives.
    lines = text.splitlines()
    directives: dict[str, str] = {}
    while lines and (d := _anki_directive(lines[0])):
        lines.pop(0)
        directives[d[0]] = d[1]
    body = "\n".join(lines)

    sep = {"tab": "\t", "comma": ",", "semicolon": ";", "pipe": "|", "space": " "}.get(
        directives.get("separator", "").lower()
    ) or _sniff_delimiter(body, p.suffix.lower())

    table = [r for r in csv.reader(io.StringIO(body), delimiter=sep) if any(c.strip() for c in r)]
    if not table:
        return Deck([], [], str(p), p.stem, True)

    width = max(len(r) for r in table)
    table = [r + [""] * (width - len(r)) for r in table]

    if "columns" in directives:
        header = [c.strip() for c in directives["columns"].split(sep)]
        header += [f"col{i + 1}" for i in range(len(header), width)]
        has_header, body_rows = False, table
    else:
        if has_header is None:
            has_header = _looks_like_header(table[0], table[1:]) and "separator" not in directives
        if has_header:
            header = [c.strip() or f"col{i + 1}" for i, c in enumerate(table[0])]
            body_rows = table[1:]
        else:
            header = [f"col{i + 1}" for i in range(width)]
            body_rows = table

    # De-duplicate header names.
    seen: dict[str, int] = {}
    for i, h in enumerate(header):
        if h in seen:
            seen[h] += 1
            header[i] = f"{h}_{seen[h]}"
        else:
            seen[h] = 1

    rows = [dict(zip(header, r)) for r in body_rows]
    return Deck(header, rows, str(p), p.stem, has_header)
