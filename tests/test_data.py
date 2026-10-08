from __future__ import annotations

import json

import pytest

from cardsmith.data import Deck, load_deck


def _write(tmp_path, name: str, content: str | bytes):
    p = tmp_path / name
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return p


def test_csv_with_header(tmp_path):
    p = _write(tmp_path, "vocab.csv", "word,reading,meaning\n犬,いぬ,dog\n猫,ねこ,cat\n")
    d = load_deck(p)
    assert d.columns == ["word", "reading", "meaning"]
    assert d.has_header
    assert d.rows == [
        {"word": "犬", "reading": "いぬ", "meaning": "dog"},
        {"word": "猫", "reading": "ねこ", "meaning": "cat"},
    ]
    assert d.name == "vocab"
    assert len(d) == 2


def test_csv_quoted_fields(tmp_path):
    p = _write(tmp_path, "q.csv", 'word,meaning\n見る,"to see, to look"\n食べる,"to eat"\n')
    d = load_deck(p)
    assert d.rows[0]["meaning"] == "to see, to look"


def test_semicolon_csv_sniffed(tmp_path):
    p = _write(tmp_path, "s.csv", "word;meaning\n犬;dog\n猫;cat\n鳥;bird\n")
    d = load_deck(p)
    assert d.columns == ["word", "meaning"]
    assert d.rows[2] == {"word": "鳥", "meaning": "bird"}


def test_tsv_by_suffix_and_by_content(tmp_path):
    body = "word\tmeaning\n犬\tdog, hound\n猫\tcat\n"
    for name in ("a.tsv", "a.txt", "a.csv"):
        d = load_deck(_write(tmp_path, name, body))
        assert d.columns == ["word", "meaning"], name
        assert d.rows[0]["meaning"] == "dog, hound", name


def test_headerless_detected(tmp_path):
    p = _write(tmp_path, "n.tsv", "犬\tいぬ\tdog\n猫\tねこ\tcat\n")
    d = load_deck(p)
    assert not d.has_header
    assert d.columns == ["col1", "col2", "col3"]
    assert len(d) == 2


def test_numeric_first_row_is_not_header(tmp_path):
    p = _write(tmp_path, "n.csv", "1,dog\n2,cat\n")
    d = load_deck(p)
    assert not d.has_header
    assert d.rows[0] == {"col1": "1", "col2": "dog"}


def test_has_header_override(tmp_path):
    p = _write(tmp_path, "n.tsv", "犬\tいぬ\n猫\tねこ\n")
    d = load_deck(p, has_header=True)
    assert d.columns == ["犬", "いぬ"]
    assert d.rows == [{"犬": "猫", "いぬ": "ねこ"}]
    d = load_deck(_write(tmp_path, "h.csv", "word,meaning\nx,y\n"), has_header=False)
    assert d.columns == ["col1", "col2"]
    assert len(d) == 2


def test_anki_export_directives(tmp_path):
    content = (
        "#separator:tab\n"
        "#html:true\n"
        "#notetype column:1\n"
        "Basic\t<b>犬</b>\tdog\n"
        "Basic\t猫\tcat<br>kitty\n"
    )
    p = _write(tmp_path, "anki.txt", content)
    d = load_deck(p)
    # #separator present -> no header auto-detection
    assert not d.has_header
    assert d.columns == ["col1", "col2", "col3"]
    assert d.rows[0]["col2"] == "<b>犬</b>"  # raw html kept; text.render strips it
    assert len(d) == 2


def test_anki_export_columns_directive(tmp_path):
    content = "#separator:semicolon\n#html:false\n#columns:Front;Back;Tags\n犬;dog;n5\n猫;cat\n"
    d = load_deck(_write(tmp_path, "anki.txt", content))
    assert d.columns == ["Front", "Back", "Tags"]
    assert d.rows[1] == {"Front": "猫", "Back": "cat", "Tags": ""}
    assert not d.has_header


def test_anki_columns_shorter_than_data(tmp_path):
    content = "#separator:tab\n#columns:Front\n犬\tdog\n"
    d = load_deck(_write(tmp_path, "anki.txt", content))
    assert d.columns == ["Front", "col2"]
    assert d.rows == [{"Front": "犬", "col2": "dog"}]


def test_ragged_rows_padded(tmp_path):
    p = _write(tmp_path, "r.csv", "a,b,c\n1x,2x\n1y,2y,3y,4y\n")
    d = load_deck(p)
    assert d.columns == ["a", "b", "c", "col4"]
    assert d.rows[0] == {"a": "1x", "b": "2x", "c": "", "col4": ""}
    assert d.rows[1]["col4"] == "4y"


def test_blank_lines_skipped(tmp_path):
    d = load_deck(_write(tmp_path, "b.csv", "a,b\n\nx,y\n , \n"))
    assert d.rows == [{"a": "x", "b": "y"}]


def test_duplicate_headers_deduplicated(tmp_path):
    p = _write(tmp_path, "d.csv", "word,note,note,word\n犬,a,b,c\n")
    d = load_deck(p, has_header=True)
    assert d.columns == ["word", "note", "note_2", "word_2"]
    assert d.rows[0] == {"word": "犬", "note": "a", "note_2": "b", "word_2": "c"}


def test_empty_header_cells_named(tmp_path):
    d = load_deck(_write(tmp_path, "e.csv", "word,,meaning\n犬,x,dog\n"), has_header=True)
    assert d.columns == ["word", "col2", "meaning"]


def test_utf8_bom_removed(tmp_path):
    p = _write(tmp_path, "bom.csv", "﻿word,meaning\n犬,dog\n".encode())
    d = load_deck(p)
    assert d.columns == ["word", "meaning"]
    assert d.rows[0]["word"] == "犬"


def test_empty_file(tmp_path):
    d = load_deck(_write(tmp_path, "e.csv", ""))
    assert d.columns == [] and d.rows == []


def test_json_list(tmp_path):
    data = [{"word": "犬", "n": 1}, {"word": "猫", "extra": None}]
    d = load_deck(_write(tmp_path, "d.json", json.dumps(data, ensure_ascii=False)))
    assert d.columns == ["word", "n", "extra"]
    assert d.rows == [{"word": "犬", "n": "1"}, {"word": "猫", "extra": ""}]
    assert d.has_header


@pytest.mark.parametrize("key", ["cards", "rows"])
def test_json_object_with_cards(tmp_path, key):
    d = load_deck(_write(tmp_path, "d.json", json.dumps({key: [{"a": "x"}]})))
    assert d.rows == [{"a": "x"}]


def test_deck_selected_respects_included():
    d = Deck(["a"], [{"a": "1"}, {"a": "2"}, {"a": "3"}])
    assert d.included == [True, True, True]
    d.included[1] = False
    assert d.selected() == [(0, {"a": "1"}), (2, {"a": "3"})]


def test_example_deck_loads():
    from pathlib import Path

    p = Path(__file__).parents[1] / "examples" / "japanese" / "jlpt-n5-kanji.tsv"
    if not p.exists():
        pytest.skip("example deck missing")
    d = load_deck(p)
    assert d.columns == ["word", "reading", "meaning", "jlpt"]
    assert len(d) > 10


def test_duplicate_headers_auto_detected(tmp_path):
    p = _write(tmp_path, "d.csv", "word,note,note\n犬,a,b\n猫,c,d\n")
    d = load_deck(p)
    assert d.has_header
    assert d.columns == ["word", "note", "note_2"]
