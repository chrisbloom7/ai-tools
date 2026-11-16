import dataclasses
import re
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from logo_pipeline import assess, compose, config, deps, report, segment
from logo_pipeline.build import BuildResult
from logo_pipeline.verify import Result

DOCS = ("README.md", "logo-package/README.txt", "report/conversion-report.md")
NEEDS_BUILD = pytest.mark.skipif(
    "chrome" in deps.check_tools() or "potrace" in deps.check_tools(),
    reason="Chrome and potrace are needed to build")

# A two-variant brand with a mark, written into each test's folder (an invented logo: the names
# only need to be distinct from the synthetic one-variant brand in generic_brand.py).
TWO_VARIANTS = """
[brand]
name = "Placeholder Goods"
mark_element = "emblem"
share_card_variant = "primary"

[variants.primary]
source = "source/art-primary.png"
mark_name = "pip"
tile = "#efd27a"
background = "light"

[variants.alt]
source = "source/art-alt.png"
mark_name = "orb"
tile = "#3a2a7e"
background = "dark"

[report]
notes = [
  "The paper grain is not reproduced.",
  "The alt fill loses a soft highlight.",
]

[elements]
outline = "teal"

[elements.palette]
teal = ["#1f8a9e"]
warm = ["#f2c94c", "#f2994a"]
cool = ["#5b3a9e", "#9b51e0"]

[elements.regions.emblem]
center = [0.0, 0.0, 1.0, 0.5]

[elements.regions.lettering]
center = [0.0, 0.5, 1.0, 1.0]

[verify]
iou_min = 0.98
color_error_max = 8.0

[compose]
HALO_ALPHA = 48
STOPS = 5
"""


def _brand_dir(root: Path, text: str = TWO_VARIANTS, where: str = "brand.toml") -> Path:
    """Write the two-variant config at `root`/`where` and tiny source PNGs under `root`;
    return the config path."""
    (root / "source").mkdir(exist_ok=True)
    for v in ("primary", "alt"):
        Image.new("RGBA", (10, 10)).save(root / "source" / f"art-{v}.png")
    cfg = root / where
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text(text)
    return cfg


def _element(kind="flat", gradient_layers=(), shift=0):
    m = np.zeros((10, 10), bool)
    m[2 + shift:5 + shift, 2:5] = True
    return segment.Element(m, (2, 2 + shift, 5, 5 + shift), kind, {"outline": m},
                           list(gradient_layers))


def _data(root, brand=None, cfg=None):
    """Assessment and BuildResult shaped like a two-variant build (small fake masks: alt's are
    shifted, so no piece is shared). Writes the brand under `root` unless `cfg` is given."""
    cfg = cfg or _brand_dir(root)
    fi = [assess.FileInfo(Path(f"source/art-{v}.png"), 2400, 2400, True, True, 9, False)
          for v in ("primary", "alt")]
    a = assess.Assessment("good", ["Shortest side is 2400 px."],
                          [assess.LAYERS_UPGRADE,
                           "send art at 3000 px or larger for the best result"], True, fi)
    r = BuildResult(
        files=[Path("svg/logo-stacked-primary.svg")],
        verify={"logo-stacked-primary.svg": Result(0.9871, 5.12, True),
                "logo-stacked-alt.svg": Result(0.9862, 6.05, True)},
        contrast={"icon-primary": 2.74, "icon-alt": 2.92},
        elements={"primary": {"emblem": _element("gradient", ["warm"]), "lettering": _element()},
                  "alt": {"emblem": _element("gradient", ["cool"], 1),
                           "lettering": _element(shift=2)}},
        brand=brand or config.load_brand(root, cfg), config=cfg,
        settings=compose.load_settings(cfg),
        dropped={"primary": [segment.Dropped(240, 30, (1200, 900), "#ffffff"),
                          segment.Dropped(58, 40, (1650, 500), "#fefefe"),
                          segment.Dropped(6, 130, (1600, 700), "#2b7f8a")],
                 "alt": []})
    return a, r


@pytest.fixture
def docs(tmp_path):
    a, r = _data(tmp_path)
    report.write_all(tmp_path, a, r)
    return tmp_path


def _flat(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_report_names_tier_and_upgrade(docs):
    text = (docs / "report/conversion-report.md").read_text()
    assert "**Good**" in text
    assert "2400" in text
    assert assess.LAYERS_UPGRADE in " ".join(text.split())
    assert "transparent PNGs at 3000 px or more" in text  # designer ask from the spec
    assert "No pieces are shared" in text


def test_report_lists_verify_numbers_per_file(docs):
    text = (docs / "report/conversion-report.md").read_text()
    for name, iou, err in (("logo-stacked-primary.svg", "0.9871", "5.12"),
                           ("logo-stacked-alt.svg", "0.9862", "6.05")):
        row = next(l for l in text.splitlines() if name in l and "|" in l)
        assert iou in row and err in row
    assert "2.74:1" in text and "2.92:1" in text
    assert "flat plus gradient" in text and "emblem" in text


def test_report_lists_the_dropped_pieces_per_variant(docs):
    text = _flat(docs / "report/conversion-report.md")
    assert "art-primary.png: 3 detached pieces dropped (1 speck, 2 faint wisps)" in text
    assert ("about 240 px (max alpha 30, mean color `#ffffff`, near x=1200, y=900)" in text)
    assert "58 px (max alpha 40" in text
    assert "art-alt.png: nothing dropped" in text


def test_report_says_what_the_preflight_counted_not_what_was_dropped(docs):
    text = _flat(docs / "report/conversion-report.md")
    assert "what the preflight counted, not what was dropped" in text


def _bad_lines(path: Path) -> list[str]:
    """Rule: a line starting with `#` (after spaces) is bad when it is in a .txt file or follows a
    non-blank line (a wrapped continuation). After a blank line it is a real markdown heading."""
    lines = path.read_text().splitlines()
    bad = []
    for i, line in enumerate(lines):
        if re.match(r"^\s*#", line) and (path.suffix == ".txt" or (i > 0 and lines[i - 1].strip())):
            bad.append(line)
    return bad


def test_no_wrapped_line_starts_with_hash(docs):
    for d in DOCS:
        assert (docs / d).exists()
        assert _bad_lines(docs / d) == [], d
    # a hash-number written into data must be escaped, not wrapped to a line start
    a, r = _data(docs)
    a.findings = ["x " * 45 + "#198 follows"]
    report.write_all(docs, a, r)
    for d in DOCS:
        assert _bad_lines(docs / d) == [], d


def test_package_readme_states_rgb_only_and_no_print_masters(docs):
    text = (docs / "logo-package/README.txt").read_text().lower()
    assert "rgb only" in text
    for word in ("cmyk", "eps", "original"):
        assert word in text
    assert "vector" in text and "pdf" in text
    for tool in ("website", "print shop", "etsy", "cutting machine", "email", "social"):
        assert tool in text


def test_package_readme_wording(docs):
    text = _flat(docs / "logo-package/README.txt")
    assert "ready to use as it is" not in text
    assert "ready to use on screen" in text and "WHAT IS NOT INCLUDED" in text
    assert "CMYK is the four-ink color mode print shops use" in text
    assert "print-industry file formats" in text
    # signs go with the designer's original art, not with the PDFs for stickers
    shop = next(l for l in text.split("* ") if l.startswith("Print shop"))
    assert "signs" not in shop
    signs = next(l for l in text.split("* ") if l.startswith("Signs"))
    assert "original art" in signs
    title, rule = (docs / "logo-package/README.txt").read_text().splitlines()[:2]
    assert title == "PLACEHOLDER GOODS LOGO PACKAGE" and rule == "=" * len(title)
    assert "PRIMARY is for light backgrounds" in text and "ALT is for dark backgrounds" in text
    assert "Files marked primary and alt are different drawings" in text


def test_readme_rebuild_overwrites_report_and_code_spans_hold_one_path(docs):
    text = (docs / "README.md").read_text()
    flat = " ".join(text.split())
    assert "deletes and regenerates `svg/`, `png/` and `logo-package/`" in flat
    assert "overwrites `report/conversion-report.md`" in flat
    for span in re.findall(r"`([^`]+)`", text):
        assert ", " not in span, span  # one path per code span
    # each source in its own span, relative to the brand folder
    assert "`source/art-primary.png`, `source/art-alt.png`" in text
    assert ("Use the primary files on light backgrounds and the alt files on dark backgrounds"
            in flat)


def test_report_notes_appear_under_known_limits_and_nowhere_else(docs):
    notes = config.load_brand(docs, docs / "brand.toml").notes
    assert notes
    rep = _flat(docs / "report/conversion-report.md")
    limits = rep.split("## Known limits of this conversion")[1].split("## ")[0]
    for note in notes:
        assert note in limits, note
        assert rep.count(note) == 1, note
        for d in ("README.md", "logo-package/README.txt"):
            assert note not in _flat(docs / d), (d, note)


def test_report_describes_the_halo_band_from_the_built_svgs(tmp_path):
    # width and opacity come from the lockups' n-halos group, not from fixed text
    (tmp_path / "svg").mkdir()
    for v, px, op in (("primary", "2.24", "0.341"), ("alt", "3.5", "0.318")):
        (tmp_path / "svg" / f"logo-stacked-{v}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            f'<g class="n-halos" fill="#fff" stroke="#fff" stroke-width="1" opacity="{op}" '
            f'data-halo-px="{px}"><g class="n-halo"><path d="M0 0h1v1z"/></g></g></svg>')
    a, r = _data(tmp_path)
    report.write_all(tmp_path, a, r)
    text = _flat(tmp_path / "report/conversion-report.md")
    assert "uniform-width" in text
    assert "primary 2.24 px of source art at opacity 0.34" in text
    assert "alt 3.5 px of source art at opacity 0.32" in text
    assert "0.39" not in text
    assert "(alpha 48 and up)" in text


def test_halo_threshold_text_follows_the_compose_override(tmp_path):
    # [compose] has no halo opacity (it is measured from the art and read from the SVG); its
    # halo knob is HALO_ALPHA, the rim threshold the report quotes
    cfg = _brand_dir(tmp_path, TWO_VARIANTS.replace("HALO_ALPHA = 48", "HALO_ALPHA = 60"))
    (tmp_path / "svg").mkdir()
    (tmp_path / "svg" / "logo-stacked-primary.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g class="n-halos" '
        'fill="#fff" opacity="0.3" data-halo-px="2"><path d="M0 0h1v1z"/></g></svg>')
    a, r = _data(tmp_path, cfg=cfg)
    report.write_all(tmp_path, a, r)
    text = _flat(tmp_path / "report/conversion-report.md")
    assert "(alpha 60 and up)" in text and "alpha 48" not in text


def test_verify_bar_and_gradient_stops_come_from_the_config(tmp_path):
    cfg = _brand_dir(tmp_path, TWO_VARIANTS.replace("STOPS = 5", "STOPS = 7")
                     .replace("iou_min = 0.98", "iou_min = 0.97"))
    a, r = _data(tmp_path, cfg=cfg)
    report.write_all(tmp_path, a, r)
    text = _flat(tmp_path / "report/conversion-report.md")
    assert "linearGradient with 7 stops" in text
    assert "IoU at least 0.97" in text


def test_docs_have_no_stale_transparent_email_header_statement(docs):
    for d in DOCS:
        low = _flat(docs / d).lower()
        assert "email headers, transparent" not in low
        assert "email header is transparent" not in low
        assert "see-through background" not in low
        assert "client's own background" not in low
        assert "dark email background" not in low
    assert "white background" in _flat(docs / "logo-package/README.txt")
    rep = _flat(docs / "report/conversion-report.md")
    assert "opaque white" in rep and "transparent version" in rep and "not shipped" in rep


@pytest.mark.parametrize("tier", ["best", "good", "limited"])
def test_input_grade_explains_its_own_tier_only(tmp_path, tier):
    a, r = _data(tmp_path)
    a.tier = tier
    report.write_all(tmp_path, a, r)
    rep = _flat(tmp_path / "report/conversion-report.md")
    for t, text in assess.TIER_EXPECT.items():
        assert (text in rep) == (t == tier), t
    assert "one canvas size across variants" in rep and "placement" not in rep


def test_best_tier_does_not_promise_per_element_output():
    best = assess.TIER_EXPECT["best"]
    assert "does not output per-element files" in best and "flat export" in best


def test_verify_section_says_only_the_lockup_is_compared(docs):
    rep = _flat(docs / "report/conversion-report.md")
    assert "set in `brand.toml` `[verify]`" in rep and "set once" not in rep
    assert "The stacked lockup is the only file compared with the source" in rep
    assert "checked by eye only: look at them" in rep
    assert "are not compared separately" not in rep


def test_package_readme_says_untagged_srgb_and_readme_says_headers_are_white(docs):
    pkg = _flat(docs / "logo-package/README.txt")
    assert "untagged sRGB" in pkg and "check a proof" in pkg
    readme = _flat(docs / "README.md")
    usage = readme.split("## Usage rules")[1].split("## ")[0]
    assert "email headers are always on an opaque white background" in usage


def test_docs_do_not_overstate_the_trace(docs):
    rep = _flat(docs / "report/conversion-report.md")
    pkg = _flat(docs / "logo-package/README.txt")
    for old in ("edges are clean at any size", "match closely"):
        assert old not in rep and old not in pkg, old
    assert "curves stay smooth at any size" in rep
    assert "sharp corners and perfectly straight edges are softened slightly" in rep
    assert "sharp corners and perfectly straight edges are softened slightly" in pkg
    limits = rep.split("## Known limits of this conversion")[1].split("## ")[0]
    assert "scores are averages over the whole lockup" in limits and "look at the outputs" in limits


def test_docs_describe_the_simplified_16px_favicon(docs):
    readme = _flat(docs / "README.md")
    rep = _flat(docs / "report/conversion-report.md")
    for text in (readme, rep):
        assert "16 px" in text and "simplified" in text
        assert "outline" in text and "halo" in text
    assert "at 16 px the mark is just scaled down" not in rep


def test_names_come_from_the_brand(tmp_path):
    brand = dataclasses.replace(config.load_brand(tmp_path, _brand_dir(tmp_path)),
                                name="Other Name", share_card_variant="alt")
    a, r = _data(tmp_path, brand=brand)
    report.write_all(tmp_path, a, r)
    readme = _flat(tmp_path / "README.md")
    assert readme.startswith("# Other Name brand assets")
    assert "Placeholder Goods" not in readme
    assert (tmp_path / "logo-package/README.txt").read_text().startswith("OTHER NAME LOGO PACKAGE")
    assert "The share card is the alt lockup" in _flat(tmp_path / "report/conversion-report.md")


def test_three_variants_render_and_are_all_listed(tmp_path):
    base = config.load_brand(tmp_path, _brand_dir(tmp_path))
    primary, alt = base.variants["primary"], base.variants["alt"]
    third = config.Variant(tmp_path / "source/art-third.png", "star", "#123456", None)
    brand = dataclasses.replace(base, variants={"primary": primary, "alt": alt, "third": third})
    a, r = _data(tmp_path, brand=brand)
    r.elements["third"] = {"emblem": _element("gradient", ["cool"]), "lettering": _element()}
    r.verify["logo-stacked-third.svg"] = Result(0.99, 3.0, True)
    r.contrast["icon-third"] = 4.5
    r.dropped["third"] = []
    report.write_all(tmp_path, a, r)
    rep = _flat(tmp_path / "report/conversion-report.md")
    readme = _flat(tmp_path / "README.md")
    pkg = _flat(tmp_path / "logo-package/README.txt")
    for v in ("primary", "alt", "third"):
        assert f"logo-stacked-{v}" in pkg
        assert f"| {v} |" in (tmp_path / "report/conversion-report.md").read_text()
    assert "{primary,alt,third}" in readme and "mark-{pip,orb,star}" in readme
    assert "three versions" in pkg
    # the first variant is compared with each other variant
    assert "Primary vs alt IoU" in rep and "Primary vs third IoU" in rep
    assert "between primary and third" in rep
    # primary's pieces equal third's, so they are shared; alt's are not
    assert "Pieces shared between primary and third" in rep
    assert "`#123456`" in rep and "4.50:1 (third)" in rep


def test_one_variant_has_nothing_to_compare(tmp_path):
    base = config.load_brand(tmp_path, _brand_dir(tmp_path))
    brand = dataclasses.replace(base, variants={"primary": base.variants["primary"]})
    a, r = _data(tmp_path, brand=brand)
    del r.elements["alt"], r.dropped["alt"], r.verify["logo-stacked-alt.svg"]
    del r.contrast["icon-alt"]
    report.write_all(tmp_path, a, r)
    rep = _flat(tmp_path / "report/conversion-report.md")
    assert "only one variant (primary), so there is nothing to compare" in rep
    assert "alt" not in _flat(tmp_path / "README.md")
    assert "different drawings" not in _flat(tmp_path / "logo-package/README.txt")


def test_build_notes_are_rendered(tmp_path):
    a, r = _data(tmp_path)
    r.notes.append("A note from the build about the icons.")
    report.write_all(tmp_path, a, r)
    rep = (tmp_path / "report/conversion-report.md").read_text()
    icons = rep.split("## Icons, headers and share card")[1].split("\n## ")[0]
    assert "A note from the build about the icons." in " ".join(icons.split())
    assert "A note from the build about the icons." in _flat(tmp_path / "README.md")


# --- what the documents say about the config and the rebuild -----------------------------------

def _all_docs(root: Path) -> str:
    return "\n".join((root / d).read_text() for d in DOCS)


def test_top_level_brand_toml_docs_name_cli_build_and_never_tools(tmp_path):
    a, r = _data(tmp_path)  # config at tmp_path/brand.toml
    report.write_all(tmp_path, a, r)
    text = _all_docs(tmp_path)
    # a complete, runnable command: the scripts folder this build ran from and this folder
    scripts = report.SCRIPTS_DIR.as_posix()
    assert f"uv run --project {scripts} python {scripts}/cli.py build {tmp_path.resolve()}" in text
    assert "`logo-package` skill" in text and "`brand.toml`" in text
    for stale in ("tools/build.py", "tools/brand.toml", "`tools/`"):
        assert stale not in text, stale


def test_tools_brand_toml_docs_name_the_tools_layout(tmp_path):
    cfg = _brand_dir(tmp_path, where="tools/brand.toml")
    a, r = _data(tmp_path, cfg=cfg)
    report.write_all(tmp_path, a, r)
    text = _all_docs(tmp_path)
    assert "`tools/brand.toml`" in text and "uv run --project tools python tools/build.py" in text
    assert "Generated by `tools/build.py`" in text
    assert "cli.py" not in text


def test_explicit_layout_wins_over_where_the_config_sits(tmp_path):
    a, r = _data(tmp_path)
    report.write_all(tmp_path, a, r, layout=config.LAYOUT_TOOLS)
    assert "uv run --project tools python tools/build.py" in _all_docs(tmp_path)


def test_layout_of_reads_where_the_config_sits(tmp_path):
    assert config.layout_of(tmp_path, tmp_path / "tools" / "brand.toml") == config.LAYOUT_TOOLS
    assert config.layout_of(tmp_path, tmp_path / "brand.toml") == config.LAYOUT_SKILL
    assert config.layout_of(tmp_path, tmp_path / "x" / "brand.toml") == config.LAYOUT_SKILL


# --- a second, synthetic brand (ring and bar, one variant, no mark) ----------------------------

# Words that only belong to the two-variant brand above: none may leak into another brand's
# docs (the documents must take every name from the brand they describe).
OTHER_BRAND_WORDS = {
    "pip": "the primary mark's name",
    "orb": "the alt mark's name",
    "placeholder": "the brand name",
    "emblem": "an element name and the mark element",
    "lettering": "an element name",
    "primary": "a variant name",
    "alt": "a variant name",
}


def _generic_docs(generic_brand, tmp_path):
    """The docs written into a copy of the shared build (the build itself stays untouched)."""
    built, res = generic_brand
    brand_dir = tmp_path / "brand"
    shutil.copytree(built, brand_dir)
    a = assess.assess([v.source for v in res.brand.variants.values()])
    report.write_all(brand_dir, a, res)
    return brand_dir


@pytest.mark.slow
@NEEDS_BUILD
def test_generic_brand_docs_name_its_variant_and_none_of_another_brand(generic_brand, tmp_path):
    brand_dir = _generic_docs(generic_brand, tmp_path)
    for d in DOCS:
        text = (brand_dir / d).read_text()
        for word, why in OTHER_BRAND_WORDS.items():
            # the whole word only, not part of a longer word or a number
            hits = re.findall(rf"(?<![\w.]){word}\b", text, re.IGNORECASE)
            assert not hits, (d, word, why)
    readme = _flat(brand_dir / "README.md")
    assert "default" in readme and "Ring and Bar" in readme
    assert "`svg/logo-stacked-default.svg`" in readme
    assert "mark-" not in readme  # no mark row without a mark element
    rep = _flat(brand_dir / "report/conversion-report.md")
    assert "only one variant (default), so there is nothing to compare" in rep
    note = generic_brand[1].notes[0]
    assert note in rep and note in readme  # the lockup-as-icon fallback note
    # the synthetic brand keeps its config in tools/, so the docs describe that layout
    assert "`tools/brand.toml`" in rep and "uv run --project tools python tools/build.py" in readme


@pytest.mark.slow
@NEEDS_BUILD
def test_generic_brand_docs_have_no_wrapped_hash_lines(generic_brand, tmp_path):
    brand_dir = _generic_docs(generic_brand, tmp_path)
    for d in DOCS:
        assert _bad_lines(brand_dir / d) == [], d
