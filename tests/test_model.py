from __future__ import annotations

import pytest

from cardsmith.model import (
    Border,
    Hole,
    Printer,
    Slot,
    Template,
    colour_changes,
    height_bands,
)

# ---------------------------------------------------------------------------
# Layer maths


@pytest.mark.parametrize(
    ("h0", "h", "thickness", "expected"),
    [
        (0.2, 0.2, 1.2, 1.2),
        (0.2, 0.2, 1.0, 1.0),
        (0.2, 0.2, 0.05, 0.2),  # never less than one layer
        (0.28, 0.2, 1.2, 1.28),
        (0.28, 0.2, 1.0, 1.08),
        (0.3, 0.2, 1.3, 1.3),
        (0.3, 0.2, 1.0, 1.1),  # exact tie rounds up
        (0.2, 0.12, 1.2, 1.16),
    ],
)
def test_snap_base(h0, h, thickness, expected):
    p = Printer(first_layer_height=h0, layer_height=h)
    assert p.snap_base(thickness) == pytest.approx(expected)


@pytest.mark.parametrize("h0", [0.2, 0.28, 0.3])
def test_snap_base_lands_on_layer_boundary(h0):
    p = Printer(first_layer_height=h0, layer_height=0.2)
    for t in (0.4, 0.8, 1.2, 1.6, 2.0):
        z = p.snap_base(t)
        n = (z - h0) / 0.2
        assert n == pytest.approx(round(n), abs=1e-6)
        assert abs(z - t) <= 0.1 + 1e-6


@pytest.mark.parametrize(
    ("h", "height", "expected"),
    [(0.2, 0.05, 0.2), (0.2, 0.4, 0.4), (0.2, 0.6, 0.6), (0.2, 0.65, 0.6), (0.12, 0.6, 0.6), (0.12, 0.4, 0.36)],
)
def test_snap_relief(h, height, expected):
    assert Printer(layer_height=h).snap_relief(height) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("h0", "z", "below"),
    [
        (0.2, 0.0, 0),
        (0.2, 0.2, 1),
        (0.2, 1.2, 6),
        (0.2, 1.6, 8),
        (0.28, 0.28, 1),
        (0.28, 1.28, 6),
        (0.28, 1.68, 8),
        (0.3, 0.3, 1),
        (0.3, 1.1, 5),
        (0.3, 1.5, 7),
    ],
)
def test_layers_below_and_starting_at(h0, z, below):
    p = Printer(first_layer_height=h0, layer_height=0.2)
    assert p.layers_below(z) == below
    # Cura's FilamentChange takes the 1-based preview layer; the change happens
    # at the start of that layer, i.e. the first layer printed above z.
    assert p.layer_starting_at(z) == below + 1


def test_layer_starting_at_matches_layer_z_table():
    """Cross-check against an explicit list of layer bottoms."""
    for h0 in (0.2, 0.28, 0.3):
        p = Printer(first_layer_height=h0, layer_height=0.2)
        bottoms = [0.0] + [round(h0 + i * 0.2, 4) for i in range(20)]  # bottom of layer k+1
        for k, z in enumerate(bottoms):
            assert p.layer_starting_at(z) == k + 1


# ---------------------------------------------------------------------------
# Height bands / colour changes


def _tpl(slots, border=True, palette=None) -> Template:
    t = Template(border=Border(enabled=border, height=0.4), hole=Hole(enabled=False), slots=slots)
    if palette is not None:
        t.palette = palette
    return t


def test_height_bands_group_equal_heights():
    t = _tpl([Slot("A", height=0.6), Slot("B", height=0.6), Slot("C", height=1.0)])
    p = Printer()
    bands = height_bands(t, p)
    assert [b.index for b in bands] == [0, 1, 2, 3]
    assert bands[0].features == ["Card"]
    assert bands[0].z_top == pytest.approx(1.2)
    assert bands[0].z_bottom == 0.0
    assert bands[1].features == ["Border"]
    assert bands[1].z_top == pytest.approx(1.6)
    assert bands[2].features == ["A", "B"]
    assert bands[2].z_bottom == pytest.approx(1.6)
    assert bands[2].z_top == pytest.approx(1.8)
    assert bands[3].features == ["C"]
    assert bands[3].z_top == pytest.approx(2.2)
    # Bands stack without gaps.
    for lo, hi in zip(bands, bands[1:], strict=False):
        assert hi.z_bottom == pytest.approx(lo.z_top)


def test_height_bands_heights_snapping_to_same_layer_share_band():
    t = _tpl([Slot("A", height=0.6), Slot("B", height=0.62)], border=False)
    bands = height_bands(t, Printer())
    assert len(bands) == 2
    assert bands[1].features == ["A", "B"]


def test_height_bands_border_shares_with_slot():
    t = _tpl([Slot("A", height=0.4)])
    bands = height_bands(t, Printer())
    assert len(bands) == 2
    assert bands[1].features == ["Border", "A"]


def test_height_bands_ignore_disabled_slots_and_border():
    t = _tpl([Slot("A", height=0.6), Slot("Off", height=1.0, enabled=False)], border=False)
    bands = height_bands(t, Printer())
    assert [b.features for b in bands] == [["Card"], ["A"]]


def test_height_bands_palette_cycles_past_end():
    t = _tpl([Slot(f"S{i}", height=0.2 * (i + 1)) for i in range(4)], border=False, palette=["#111111"])
    bands = height_bands(t, Printer())
    assert bands[0].colour == "#111111"
    assert all(b.colour.startswith("#") for b in bands)


def test_colour_changes_skip_equal_colours():
    t = _tpl(
        [Slot("A", height=0.6), Slot("B", height=1.0)],
        palette=["#FFFFFF", "#ff0000", "#FF0000", "#0000FF"],
    )
    p = Printer()
    changes = colour_changes(t, p)
    # Border (band 1) is red, A (band 2) also red -> no swap, B (band 3) blue.
    assert [c.band for c in changes] == [1, 3]
    assert changes[0].z == pytest.approx(1.2)
    assert changes[0].layer == 7  # layers 1-6 are the 1.2 mm base
    assert changes[1].z == pytest.approx(1.8)
    assert changes[1].layer == 10
    assert changes[1].colour == "#0000FF"


def test_colour_changes_first_layer_differs():
    t = _tpl([Slot("A", height=0.6)], border=False, palette=["#FFFFFF", "#000000"])
    p = Printer(first_layer_height=0.28, layer_height=0.2)
    (c,) = colour_changes(t, p)
    assert c.z == pytest.approx(1.28)
    assert c.layer == 7


def test_colour_changes_none_when_single_colour():
    t = _tpl([Slot("A", height=0.6)], palette=["#AAAAAA"] * 3)
    assert colour_changes(t, Printer()) == []


# ---------------------------------------------------------------------------
# Serialisation


def test_template_toml_round_trip(tmp_path):
    t = Template(
        name="Round trip",
        border=Border(enabled=True, width=1.5, inset=0.5, height=0.6, around_hole=False),
        hole=Hole(enabled=True, diameter=4.0, position="top-right", offset=6.0),
        slots=[
            Slot("Word", "{word|kanji}", size=20, y=30, ruby=True),
            Slot("Meaning", "{meaning}", fit="wrap", max_lines=3, align="left", x_offset=1.5, enabled=False),
        ],
        palette=["#000000", "#FFFFFF"],
        fallback_fonts=["DejaVu Sans:Bold"],
    )
    path = tmp_path / "t.toml"
    t.save(path)
    loaded = Template.load(path)
    assert loaded == t
    assert loaded is not t


def test_template_from_dict_ignores_unknown_keys():
    d = Template(slots=[Slot("A")]).to_dict()
    d["future_thing"] = 42
    d["card"]["sparkle"] = True
    d["slots"][0]["glow"] = "yes"
    t = Template.from_dict(d)
    assert t == Template(slots=[Slot("A")])


def test_template_from_dict_defaults_and_slot_alias():
    t = Template.from_dict({"name": "X", "slot": [{"name": "A", "text": "{a}"}]})
    assert t.name == "X"
    assert t.slots == [Slot("A", "{a}")]
    assert t.palette == Template().palette


def test_template_copy_is_deep():
    t = Template(slots=[Slot("A")])
    c = t.copy()
    c.slots[0].name = "B"
    c.palette.append("#123456")
    assert t.slots[0].name == "A"
    assert "#123456" not in t.palette


def test_printer_round_trip_and_feature_limit():
    p = Printer(name="X", bed_width=300, nozzle=0.6, min_feature=0.0)
    assert Printer.from_dict({**p.to_dict(), "unknown": 1}) == p
    assert p.feature_limit == 0.6
    p.min_feature = 0.45
    assert p.feature_limit == 0.45


def test_builtin_template_loads():
    from cardsmith.settings import builtin_templates, default_template

    assert "kanji" in builtin_templates()
    t = default_template()
    assert t.slots and t.name


def test_half_layer_ties_round_consistently():
    p = Printer()
    assert [p.snap_relief(x) for x in (0.3, 0.5, 0.7, 0.9)] == pytest.approx([0.4, 0.6, 0.8, 1.0])
    assert [p.snap_base(x) for x in (0.9, 1.1, 1.3)] == pytest.approx([1.0, 1.2, 1.4])


def test_from_dict_coerces_whole_numbers_to_float():
    t = Template.from_dict({"card": {"width": 50, "height": 70}, "slots": [{"size": 8, "y": 40, "max_lines": 2.0}]})
    assert isinstance(t.card.width, float) and isinstance(t.slots[0].size, float)
    assert isinstance(t.slots[0].max_lines, int)
