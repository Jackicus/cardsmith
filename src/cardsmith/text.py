"""Slot text templates: ``{field}``, ``{field|filter|filter}`` and furigana.

Filters:

``kanji``    strip Anki furigana: ``漢字[かんじ]`` -> ``漢字``
``kana``     readings only:       ``漢字[かんじ]を 見[み]る`` -> ``かんじをみる``
``upper`` / ``lower`` / ``title``  change case
``strip``    trim whitespace
``first``    first item of a ``;`` or ``,`` separated list
``html``     strip HTML tags and entities (applied automatically)

Special fields: ``{#}`` is the 1-based card number, ``{##}`` the total.
"""

from __future__ import annotations

import html
import re

FURIGANA = re.compile(r" ?([^ >\[\]]+?)\[([^\]]+)\]")
FIELD = re.compile(r"\{([^{}]*)\}")
TAG = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    return html.unescape(TAG.sub("", s)).replace("\xa0", " ")


def kanji(s: str) -> str:
    return FURIGANA.sub(r"\1", s)


def kana(s: str) -> str:
    return FURIGANA.sub(r"\2", s).replace(" ", "")


def _first(s: str) -> str:
    return re.split(r"[;,、；]", s, maxsplit=1)[0].strip()


FILTERS = {
    "kanji": kanji,
    "kana": kana,
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
    "strip": str.strip,
    "first": _first,
    "html": strip_html,
}


def render(template: str, row: dict[str, str], index: int = 0, total: int = 0) -> str:
    """Fill a slot template from a data row."""
    lower = {k.lower(): v for k, v in row.items()}

    def sub(m: re.Match) -> str:
        expr = m.group(1)
        name, *filters = [p.strip() for p in expr.split("|")]
        if name == "#":
            val = str(index + 1)
        elif name == "##":
            val = str(total)
        else:
            val = row.get(name, lower.get(name.lower(), ""))
            val = strip_html(val)
        for f in filters:
            fn = FILTERS.get(f.lower())
            if fn:
                val = fn(val)
        return val

    return FIELD.sub(sub, template).strip()


def fields_in(template: str) -> list[str]:
    return [m.group(1).split("|")[0].strip() for m in FIELD.finditer(template)]


def ruby_segments(s: str) -> list[tuple[str, str | None]]:
    """Split Anki furigana text into ``(base, reading)`` segments."""
    out: list[tuple[str, str | None]] = []
    pos = 0
    for m in FURIGANA.finditer(s):
        if m.start() > pos:
            out.append((s[pos:m.start()], None))
        out.append((m.group(1), m.group(2)))
        pos = m.end()
    if pos < len(s):
        out.append((s[pos:], None))
    return [(b, r) for b, r in out if b]


def has_ruby(s: str) -> bool:
    return bool(FURIGANA.search(s))


_CJK = re.compile(r"[　-鿿豈-﫿＀-￯]")


def wrap_tokens(s: str) -> list[str]:
    """Break text into wrap units: words for Latin text, characters for CJK.

    Each token keeps its trailing space so widths add up naturally.
    """
    tokens: list[str] = []
    buf = ""
    for ch in s:
        if _CJK.match(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            # Keep closing punctuation with the previous character.
            if tokens and ch in "、。，．）」』】！？ー":
                tokens[-1] += ch
            else:
                tokens.append(ch)
        elif ch == " ":
            buf += ch
            tokens.append(buf)
            buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens
