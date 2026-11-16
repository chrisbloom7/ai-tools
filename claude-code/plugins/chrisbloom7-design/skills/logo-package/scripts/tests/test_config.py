from pathlib import Path

import pytest

from logo_pipeline import config

SCRIPTS = Path(__file__).resolve().parents[1]

GOOD = """
[brand]
name = "Test Brand"
mark_element = "symbol"
share_card_variant = "light"

[variants.light]
source = "source/light.png"
mark_name = "pip"
tile = "#AABBCC"

[variants.dark]
source = "source/dark.png"
mark_name = "orb"
tile = "#112233"
"""


def _brand(tmp_path, text, sources=("light", "dark")):
    (tmp_path / "source").mkdir(exist_ok=True)
    for s in sources:
        (tmp_path / "source" / f"{s}.png").write_bytes(b"")
    cfg = tmp_path / "brand.toml"
    cfg.write_text(text)
    return cfg


def test_default_config_is_the_example_when_no_brand_toml_is_next_to_the_package():
    # the plugin ships brand.example.toml, not a brand.toml; callers pass the brand's own
    assert not (SCRIPTS / "brand.toml").exists()
    assert config.BRAND == config.EXAMPLE == SCRIPTS / "brand.example.toml"


def test_good_config_loads_in_order_with_tiles_as_given(tmp_path):
    b = config.load_brand(tmp_path, _brand(tmp_path, GOOD))
    assert list(b.variants) == ["light", "dark"]
    assert b.variants["light"].tile == "#AABBCC"
    assert b.variants["light"].source == tmp_path / "source/light.png"


def test_no_mark_element_and_no_mark_name_is_fine(tmp_path):
    text = """
[brand]
name = "Plain"
[variants.default]
source = "source/light.png"
tile = "#ffffff"
"""
    b = config.load_brand(tmp_path, _brand(tmp_path, text))
    assert b.mark_element is None
    assert b.variants["default"].mark_name is None
    assert b.share_card_variant == "default"  # defaults to the first variant


def _bad(tmp_path, text, match):
    cfg = _brand(tmp_path, text)
    with pytest.raises(ValueError, match=match):
        config.load_brand(tmp_path, cfg)


def test_brand_name_is_required(tmp_path):
    _bad(tmp_path, GOOD.replace('name = "Test Brand"\n', ""), r"\[brand\].*name")


def test_no_variants_table_raises(tmp_path):
    _bad(tmp_path, '[brand]\nname = "X"\n', r"no \[variants\.\*\]")


def test_missing_source_file_names_the_path(tmp_path):
    _bad(tmp_path, GOOD.replace("source/dark.png", "source/gone.png"), r"source/gone\.png")


def test_missing_source_key_raises(tmp_path):
    _bad(tmp_path, GOOD.replace('source = "source/dark.png"\n', ""), r"dark.*source")


@pytest.mark.parametrize("tile", ["#abc", "112233", "#11223g", "#1122334", "red"])
def test_tile_must_be_rrggbb(tmp_path, tile):
    _bad(tmp_path, GOOD.replace("#112233", tile), r"tile")


def test_share_card_variant_must_name_a_variant(tmp_path):
    _bad(tmp_path, GOOD.replace('share_card_variant = "light"', 'share_card_variant = "other"'),
         r"share_card_variant.*other")


def test_two_variants_with_one_mark_name_raise(tmp_path):
    _bad(tmp_path, GOOD.replace('mark_name = "orb"', 'mark_name = "pip"'), r"mark_name.*pip")


def test_mark_name_is_required_when_mark_element_is_set(tmp_path):
    _bad(tmp_path, GOOD.replace('mark_name = "orb"\n', ""), r"dark.*mark_name")


def test_unknown_key_in_brand_raises(tmp_path):
    _bad(tmp_path, GOOD.replace('name = "Test Brand"', 'name = "Test Brand"\nmark_elemnt = "x"'),
         r"\[brand\].*mark_elemnt")


def test_unknown_key_in_a_variant_raises(tmp_path):
    _bad(tmp_path, GOOD.replace('tile = "#112233"', 'tile = "#112233"\ntitle = "#000000"'),
         r"\[variants\.dark\].*title")


def test_mark_element_must_be_a_region_when_regions_are_given(tmp_path):
    text = GOOD + '\n[elements.regions.other]\ncenter = [0.0, 0.0, 1.0, 1.0]\n'
    _bad(tmp_path, text, r"mark_element.*symbol")


# --- [report] and the per-variant background ---------------------------------------------------

def test_report_table_is_optional(tmp_path):
    b = config.load_brand(tmp_path, _brand(tmp_path, GOOD))
    assert b.notes == ()
    assert b.variants["light"].background is None


def test_report_notes_are_read_in_order(tmp_path):
    text = GOOD + '\n[report]\nnotes = ["First fact.", "Second fact."]\n'
    b = config.load_brand(tmp_path, _brand(tmp_path, text))
    assert b.notes == ("First fact.", "Second fact.")


@pytest.mark.parametrize("table, match", [
    ('notes = ["ok"]\nnote = ["typo"]', r"\[report\].*unknown.*note"),
    ('notes = "one sentence"', r"\[report\] notes.*list"),
    ('notes = ["ok", 3]', r"\[report\] notes.*3.*string"),
    ('notes = ["ok", "  "]', r"\[report\] notes.*empty"),
])
def test_report_table_is_validated(tmp_path, table, match):
    cfg = _brand(tmp_path, GOOD + "\n[report]\n" + table + "\n")
    with pytest.raises(ValueError, match=match):
        config.load_brand(tmp_path, cfg)


def test_report_must_be_a_table(tmp_path):
    cfg = _brand(tmp_path, 'report = "x"\n' + GOOD)
    with pytest.raises(ValueError, match=r"\[report\].*table"):
        config.load_brand(tmp_path, cfg)


def test_variant_background_is_read_and_validated(tmp_path):
    text = GOOD.replace('tile = "#AABBCC"', 'tile = "#AABBCC"\nbackground = "light"')
    b = config.load_brand(tmp_path, _brand(tmp_path, text))
    assert b.variants["light"].background == "light"
    bad = GOOD.replace('tile = "#AABBCC"', 'tile = "#AABBCC"\nbackground = 1')
    with pytest.raises(ValueError, match=r"\[variants.light\].*background"):
        config.load_brand(tmp_path, _brand(tmp_path, bad))
