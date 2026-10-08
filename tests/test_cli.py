from __future__ import annotations

import pytest

from cardsmith import __version__
from cardsmith.cli import main
from cardsmith.model import Border, Hole, Template


@pytest.fixture
def deck(tmp_path):
    p = tmp_path / "deck.tsv"
    p.write_text("word\treading\tmeaning\tjlpt\n日\tにち\tday\tN5\n月\tつき\tmoon\tN5\n火\tひ\tfire\tN5\n",
                 encoding="utf-8")
    return p


@pytest.fixture
def plain_template(tmp_path):
    """A text-free template so these tests run without CJK fonts."""
    p = tmp_path / "plain.toml"
    Template(name="Plain", border=Border(enabled=True), hole=Hole(enabled=False), slots=[]).save(p)
    return p


def test_build_plain(deck, plain_template, tmp_path, capsys):
    out = tmp_path / "out"
    rc = main(["build", str(deck), "-t", str(plain_template), "-o", str(out), "--bed", "200x200",
               "--layer-height", "0.2", "--first-layer-height", "0.28", "--stl"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "3 cards" in text
    assert (out / "plates" / "plate_01.3mf").exists()
    assert (out / "plates" / "plate_01.stl").exists()
    assert (out / "PRINT_GUIDE.md").exists()
    assert "Custom 200 × 200" in (out / "PRINT_GUIDE.md").read_text(encoding="utf-8")


def test_build_limit_and_no_colour(deck, plain_template, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["build", str(deck), "-t", str(plain_template), "-o", str(out), "--limit", "2",
                 "--no-colour-3mf", "-p", "Prusa MINI"]) == 0
    assert "2 cards" in capsys.readouterr().out
    assert not list((out / "plates").glob("*_colours.3mf"))


@pytest.mark.usefixtures("cjk_face")
def test_build_builtin_kanji(deck, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["build", str(deck), "-t", "kanji", "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Filament Change" in text
    assert (out / "plates" / "plate_01_colours.3mf").exists()


@pytest.mark.usefixtures("cjk_face")
def test_check(deck, capsys):
    rc = main(["check", str(deck), "-t", "kanji", "--fast"])
    text = capsys.readouterr().out
    assert "of 3 cards look fine" in text
    assert rc in (0, 1)


@pytest.mark.usefixtures("cjk_face")
def test_check_reports_bad_card(tmp_path, capsys):
    p = tmp_path / "bad.csv"
    p.write_text("word,meaning\n\U00013000,glyph\n", encoding="utf-8")
    rc = main(["check", str(p), "-t", "kanji", "--fast"])
    text = capsys.readouterr().out
    assert rc == 1
    assert "error" in text
    assert "0 of 1 cards look fine" in text


def test_check_plain_ok(deck, plain_template, capsys):
    assert main(["check", str(deck), "-t", str(plain_template)]) == 0
    assert "3 of 3 cards look fine" in capsys.readouterr().out


def test_printers(capsys):
    assert main(["printers"]) == 0
    text = capsys.readouterr().out
    assert "Prusa MK4" in text and "Bambu Lab A1" in text


def test_templates(capsys):
    assert main(["templates"]) == 0
    assert "kanji" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_unknown_printer(deck):
    with pytest.raises(SystemExit) as e:
        main(["check", str(deck), "-p", "No Such Printer 9000"])
    assert "Unknown printer" in str(e.value.code)


def test_bad_bed(deck, plain_template):
    with pytest.raises(SystemExit) as e:
        main(["check", str(deck), "-t", str(plain_template), "--bed", "huge"])
    assert "--bed" in str(e.value.code)


def test_missing_template(deck):
    with pytest.raises(SystemExit) as e:
        main(["check", str(deck), "-t", "does-not-exist"])
    assert "does-not-exist" in str(e.value.code)


def test_missing_deck(tmp_path, plain_template):
    with pytest.raises(SystemExit):
        main(["check", str(tmp_path / "nope.csv"), "-t", str(plain_template)])
