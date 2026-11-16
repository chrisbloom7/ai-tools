"""A synthetic second brand for the tests: one variant `default`, a teal ring over an orange bar,
no mark element. Shared by test_generic_brand.py and test_report.py (fixture `generic_brand` in
conftest.py)."""

from PIL import Image, ImageDraw

SIDES = (600, 1200)  # canvas side; the shapes are drawn in 600 px units and scaled
RING = (31, 138, 158)
BAR = (240, 120, 30)
TILE = "#fdf6e3"

BRAND_TOML = f"""
[brand]
name = "Ring and Bar"
share_card_variant = "default"

[variants.default]
source = "source/ring-bar.png"
tile = "{TILE}"

[elements]
alpha_solid = 128
alpha_min = 16
area_floor = 3.47222e-4
reach = 0.0133333
smooth = 0.0029167
island_floor = 1.11111e-5
outline = "ring"

[elements.palette]
ring = ["#1f8a9e"]
bar = ["#f0781e"]

[elements.regions.ring]
center = [0.0, 0.0, 1.0, 0.6]
palette = ["ring"]

[elements.regions.bar]
center = [0.0, 0.6, 1.0, 1.0]
palette = ["bar"]

[verify]
iou_min = 0.98
color_error_max = 8.0
"""


def _art(side: int) -> Image.Image:
    """A thick teal ring over a filled orange bar on a transparent canvas, anti-aliased (4x).

    Coordinates are in 600 px units, scaled to `side`."""
    k = 4 * side / 600
    im = Image.new("RGBA", (side * 4, side * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([150 * k, 50 * k, 450 * k, 350 * k], outline=(*RING, 255), width=round(60 * k))
    d.rectangle([100 * k, 420 * k, 500 * k, 520 * k], fill=(*BAR, 255))
    return im.resize((side, side), Image.BOX)


def make_brand(root, side: int):
    """Write the synthetic brand (source art and tools/brand.toml) under `root`; return the
    config path."""
    (root / "source").mkdir()
    _art(side).save(root / "source" / "ring-bar.png")
    (root / "tools").mkdir()
    cfg = root / "tools" / "brand.toml"
    cfg.write_text(BRAND_TOML)
    return cfg
