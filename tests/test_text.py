from __future__ import annotations

import pytest

from cardsmith import text as tx


def test_render_plain_and_filters():
    row = {"word": "  hello world  ", "list": "one; two, three"}
    assert tx.render("{word}", row) == "hello world"
    assert tx.render("{word|upper}", row) == "HELLO WORLD"
    assert tx.render("{word|strip|title}", row) == "Hello World"
    assert tx.render("{ word | upper | lower }", row) == "hello world"
    assert tx.render("{list|first}", row) == "one"
    assert tx.render("{list|FIRST}", row) == "one"  # filter names are case-insensitive
    assert tx.render("{word|nosuchfilter}", row) == "hello world"


def test_render_first_with_japanese_separators():
    assert tx.render("{m|first}", {"m": "みる、見る"}) == "みる"
    assert tx.render("{m|first}", {"m": "a，b"}) == "a，b"  # full-width comma is not a separator


def test_render_field_names_case_insensitive():
    row = {"Word": "犬", "word": "exact"}
    assert tx.render("{word}", row) == "exact"  # exact match wins
    assert tx.render("{WORD}", {"Word": "犬"}) == "犬"
    assert tx.render("{Meaning}", {"meaning": "dog"}) == "dog"


def test_render_missing_field_is_empty():
    assert tx.render("{nope}", {"a": "1"}) == ""
    assert tx.render("[{nope}]", {}) == "[]"


def test_render_counters():
    assert tx.render("{#}/{##}", {}, index=4, total=10) == "5/10"
    assert tx.render("No. {#}", {"#": "ignored"}, index=0, total=1) == "No. 1"


def test_render_mixed_literal_text():
    assert tx.render("{a} – {b}", {"a": "x", "b": "y"}) == "x – y"


def test_render_strips_html():
    row = {"m": "<b>dog</b>&nbsp;&amp;<br/>cat<br>bird &lt;3"}
    assert tx.render("{m}", row) == "dog & cat bird <3"


def test_strip_html_entities_and_nbsp():
    assert tx.strip_html("a&nbsp;b") == "a b"
    assert tx.strip_html('<span style="x">漢</span>') == "漢"
    assert tx.strip_html("A<BR />B") == "A B"


@pytest.mark.parametrize(
    ("src", "kanji", "kana"),
    [
        ("漢字[かんじ]", "漢字", "かんじ"),
        ("漢字[かんじ]を 見[み]る", "漢字を見る", "かんじをみる"),
        (" 日本[にほん] 語[ご]", "日本語", "にほんご"),
        ("食[た]べ 物[もの]", "食べ物", "たべもの"),
        ("ひらがな", "ひらがな", "ひらがな"),
    ],
)
def test_furigana_filters(src, kanji, kana):
    assert tx.kanji(src) == kanji
    assert tx.kana(src) == kana
    assert tx.render("{e|kanji}", {"e": src}) == kanji
    assert tx.render("{e|kana}", {"e": src}) == kana


def test_furigana_inside_html():
    assert tx.render("{e|kanji}", {"e": "<b>漢字[かんじ]</b>"}) == "漢字"


def test_ruby_segments():
    assert tx.ruby_segments("漢字[かんじ]を 見[み]る") == [
        ("漢字", "かんじ"),
        ("を", None),
        ("見", "み"),
        ("る", None),
    ]
    assert tx.ruby_segments("かな") == [("かな", None)]
    assert tx.ruby_segments("") == []
    assert tx.has_ruby("見[み]る")
    assert not tx.has_ruby("見る")


def test_fields_in():
    assert tx.fields_in("{word|kanji} ({reading}) {#}") == ["word", "reading", "#"]


def test_wrap_tokens_latin_keeps_trailing_space():
    toks = tx.wrap_tokens("to eat a meal")
    assert toks == ["to ", "eat ", "a ", "meal"]
    assert "".join(toks) == "to eat a meal"


def test_wrap_tokens_cjk_per_character_with_punctuation():
    toks = tx.wrap_tokens("日本語、です。")
    assert toks == ["日", "本", "語、", "で", "す。"]
    assert "".join(toks) == "日本語、です。"


def test_wrap_tokens_mixed():
    toks = tx.wrap_tokens("JLPT N5の漢字")
    assert "".join(toks) == "JLPT N5の漢字"
    assert toks[0] == "JLPT "
    assert toks[1] == "N5"
    assert toks[2:] == ["の", "漢", "字"]


def test_wrap_tokens_long_vowel_mark_sticks():
    assert tx.wrap_tokens("コーヒー") == ["コー", "ヒー"]
