import tomllib

import numpy as np
import pytest
from PIL import Image

from logo_pipeline import config, segment

TEAL = (20, 120, 170)
TOP = (240, 205, 70)
BOTTOM = (245, 125, 15)
GREEN = (70, 160, 90)

SIDE = 600  # the fixture canvas; the pixel-valued knobs are fractions of it
RULES = {
    "area_floor": 200 / SIDE**2,  # 200 px
    "alpha_solid": 128,
    "alpha_min": 16,
    "reach": 32 / SIDE,  # 32 px
    "outline": "teal",
    "smooth": 5 / SIDE,  # 5 px
    "island_floor": 64 / SIDE**2,  # 64 px
    "palette": {
        "teal": ["#1478aa"],
        "halo": ["#ffffff"],
        "warm": ["#f0cd46", "#f57d0f"],
        "green": ["#46a05a"],
        "brick": ["#c83c3c", "#e65a3c"],
    },
    "regions": {
        "part-a": {"center": [0.0, 0.0, 0.5, 0.6]},
        "badge": {"center": [0.5, 0.0, 1.0, 0.6]},
        "stripes": {"center": [0.0, 0.6, 1.0, 1.0]},
    },
}


def framed(canvas, x0, y0, x1, y1, inset=20, halo=6):
    """Teal box with a soft white halo; returns the inner (fill) slice."""
    canvas[y0 - halo:y1 + halo, x0 - halo:x1 + halo] = (255, 255, 255, 60)
    canvas[y0:y1, x0:x1] = (*TEAL, 255)
    return np.s_[y0 + inset:y1 - inset, x0 + inset:x1 - inset]


def ramp(h, w, top, bottom):
    t = np.linspace(0, 1, h)[:, None, None]
    rgb = (1 - t) * np.array(top) + t * np.array(bottom)
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = np.broadcast_to(np.round(rgb), (h, w, 3)).astype(np.uint8)
    out[..., 3] = 255
    return out


@pytest.fixture
def canvas():
    c = np.zeros((600, 600, 4), np.uint8)
    inner = framed(c, 40, 40, 200, 300)  # part-a: vertical yellow-to-orange ramp
    h, w = c[inner].shape[:2]
    c[inner] = ramp(h, w, TOP, BOTTOM)
    inner = framed(c, 320, 40, 520, 300)  # badge: flat green
    c[inner] = (*GREEN, 255)
    inner = framed(c, 40, 380, 560, 560)  # stripes: 20 distinct flat colors in columns
    region = c[inner]
    for i, cols in enumerate(np.array_split(np.arange(region.shape[1]), 20)):
        region[:, cols] = (200 + i * 2, 40 + i * 3, 60, 255)
    # speck within reach of the part-a; its soft fringe runs into the part-a's halo, so
    # only nearest-component ownership keeps the fringe out of the part-a
    c[146:155, 205:220] = (255, 255, 255, 60)
    c[149:152, 214:217] = (*TEAL, 255)
    # far speck
    c[340:342, 300:302] = (*TEAL, 255)
    # soft-only island (never solid), far from every blob
    c[320:330, 575:585] = (255, 255, 255, 50)
    return c


def covered(elements):
    out = np.zeros((600, 600), bool)
    for el in elements.values():
        out |= el.mask
        for layer in el.layers.values():
            out |= layer
    return out


def test_specks_below_floor_dropped(canvas):
    els = segment.split_elements(canvas, RULES)
    assert len(els) == 3
    cov = covered(els)
    assert not cov[146:155, 211:220].any()  # near speck and its fringe
    assert not cov[340:342, 300:302].any()  # far speck


def test_soft_only_island_dropped(canvas):
    cov = covered(segment.split_elements(canvas, RULES))
    assert not cov[320:330, 575:585].any()


def test_detached_soft_wisp_near_blob_dropped(canvas):
    # faint pixels within reach of the badge but not touching it are not part of it
    canvas[312:315, 400:404] = (255, 255, 255, 30)
    el = segment.split_elements(canvas, RULES)["badge"]
    assert not el.mask[312:315, 400:404].any()
    assert el.bbox == (314, 34, 526, 306)


def test_elements_named_by_rules(canvas):
    els = segment.split_elements(canvas, RULES)
    assert set(els) == {"part-a", "badge", "stripes"}
    assert els["part-a"].mask[150, 100] and not els["part-a"].mask[150, 400]
    assert els["badge"].mask[150, 400]
    # bbox is (left, top, right, bottom), right/bottom exclusive; halo included
    assert els["badge"].bbox == (314, 34, 526, 306)


def test_unmatched_component_raises(canvas):
    rules = {**RULES, "regions": {k: v for k, v in RULES["regions"].items() if k != "badge"}}
    with pytest.raises(ValueError, match="no element rule"):
        segment.split_elements(canvas, rules)


def test_layers_are_outline_halo_and_fill(canvas):
    el = segment.split_elements(canvas, RULES)["part-a"]
    assert set(el.layers) == {"outline", "halo", "warm"}
    assert el.layers["outline"][45, 100] and el.layers["warm"][150, 100]
    assert el.layers["halo"][37, 100]
    # the whole ramp is one fill layer: no seam at mid-height
    assert el.layers["warm"][61:279, 61:179].all()
    # layers partition the mask
    stack = np.stack(list(el.layers.values())).astype(int).sum(axis=0)
    assert (stack[el.mask] == 1).all() and (stack[~el.mask] == 0).all()


def test_tiny_off_color_fleck_joins_surrounding_layer(canvas):
    # a 6x6 fleck survives the mode filter but is too small to be a layer of its own
    canvas[150:156, 400:406] = (240, 205, 70, 255)
    el = segment.split_elements(canvas, RULES)["badge"]
    assert set(el.layers) == {"outline", "halo", "green"}
    assert el.layers["green"][150:156, 400:406].all()


def test_gradient_element_marked_gradient(canvas):
    el = segment.split_elements(canvas, RULES)["part-a"]
    assert el.kind == "gradient"
    assert el.gradient_layers == ["warm"]


def test_flat_element_marked_flat(canvas):
    el = segment.split_elements(canvas, RULES)["badge"]
    assert el.kind == "flat"
    assert el.gradient_layers == []


def test_many_color_flat_element_is_flat(canvas):
    # 20 distinct flat colors would pass a "count the smooth colors" test; there is no ramp
    el = segment.split_elements(canvas, RULES)["stripes"]
    assert el.kind == "flat"


def test_two_tone_split_is_flat():
    c = np.zeros((600, 600, 4), np.uint8)
    inner = framed(c, 40, 380, 560, 560)
    region = c[inner]
    half = region.shape[0] // 2
    region[:half] = (200, 60, 60, 255)
    region[half:] = (230, 90, 60, 255)  # both tones fall in the one "brick" layer
    el = segment.split_elements(c, only(RULES, "stripes"))["stripes"]
    assert el.layers["brick"].sum() > 0
    assert el.kind == "flat"


def only(rules, keep):
    """Rules with every region but `keep` marked optional (the scene lacks those pieces)."""
    regions = {k: {**v, **({} if k == keep else {"optional": True})}
               for k, v in rules["regions"].items()}
    return {**rules, "regions": regions}


# ---- hardening ------------------------------------------------------------------------------

def test_region_matching_nothing_raises_naming_the_element(canvas):
    canvas[:300, 300:] = 0  # the badge is gone
    with pytest.raises(ValueError, match="badge"):
        segment.split_elements(canvas, RULES)


def test_optional_region_matching_nothing_is_left_out(canvas):
    canvas[:300, 300:] = 0
    rules = {**RULES, "regions": {**RULES["regions"],
                                  "badge": {**RULES["regions"]["badge"], "optional": True}}}
    assert set(segment.split_elements(canvas, rules)) == {"part-a", "stripes"}


def test_blank_art_raises_for_required_regions():
    with pytest.raises(ValueError, match="part-a"):
        segment.split_elements(np.zeros((SIDE, SIDE, 4), np.uint8), RULES)


def test_component_matching_several_regions_raises(canvas):
    overlap = {**RULES["regions"], "stripes": {"center": [0.0, 0.0, 1.0, 1.0]}}
    with pytest.raises(ValueError, match="several regions"):
        segment.split_elements(canvas, {**RULES, "regions": overlap})


def test_grouping_uses_bbox_center_not_bbox_extent():
    # a wide blob whose bbox starts at x=250 (inside the part-a region, x < 300) but whose
    # center (x=395) is in the badge region: it belongs to the badge
    c = np.zeros((SIDE, SIDE, 4), np.uint8)
    c[40:300, 40:200] = (*TEAL, 255)  # part-a
    c[40:300, 250:540] = (*TEAL, 255)  # wide blob
    regions = {k: v for k, v in RULES["regions"].items() if k != "stripes"}
    els = segment.split_elements(c, {**RULES, "regions": regions})
    assert set(els) == {"part-a", "badge"}
    assert els["badge"].bbox[0] < 0.5 * SIDE  # the bbox reaches into the part-a's region
    assert els["badge"].mask[100, 260]
    assert not els["part-a"].mask[100, 260]


def test_pixel_knobs_are_fractions_of_the_canvas():
    real = tomllib.loads(config.EXAMPLE.read_text())  # the shipped brand.example.toml
    knobs = segment.pixel_knobs({**segment.DEFAULTS, **real["elements"]}, (2400, 2400))
    assert knobs == {"area_floor": 2000, "reach": 32, "smooth": 7, "island_floor": 64}
    small = segment.pixel_knobs({**segment.DEFAULTS, **real["elements"]}, (600, 600))
    assert small == {"area_floor": 125, "reach": 8, "smooth": 3, "island_floor": 4}


def test_defaults_match_the_example_brand_toml():
    real = tomllib.loads(config.EXAMPLE.read_text())  # the shipped brand.example.toml
    for key in ("alpha_solid", "alpha_min", "area_floor", "reach", "smooth", "island_floor"):
        assert segment.DEFAULTS[key] == pytest.approx(real["elements"][key]), key


def test_knob_that_is_not_a_fraction_raises(canvas):
    with pytest.raises(ValueError, match="area_floor"):
        segment.split_elements(canvas, {**RULES, "area_floor": 2000})


def scene(n):
    """The three-piece fixture drawn on an n x n canvas (coordinates scale with n)."""
    k = n / SIDE
    c = np.zeros((n, n, 4), np.uint8)

    def box(x0, y0, x1, y1, inset=20, halo=6):
        x0, y0, x1, y1, inset, halo = (round(v * k) for v in (x0, y0, x1, y1, inset, halo))
        c[y0 - halo:y1 + halo, x0 - halo:x1 + halo] = (255, 255, 255, 60)
        c[y0:y1, x0:x1] = (*TEAL, 255)
        return np.s_[y0 + inset:y1 - inset, x0 + inset:x1 - inset]

    inner = box(40, 40, 200, 300)
    h, w = c[inner].shape[:2]
    c[inner] = ramp(h, w, TOP, BOTTOM)
    c[box(320, 40, 520, 300)] = (*GREEN, 255)
    return c


def test_scene_segments_the_same_at_600_and_2400():
    big = scene(2400)
    small = np.asarray(Image.fromarray(big).resize((600, 600), Image.BOX)).copy()
    regions = {k: v for k, v in RULES["regions"].items() if k != "stripes"}
    rules = {**RULES, "regions": regions}
    a = segment.split_elements(big, rules)
    b = segment.split_elements(small, rules)
    assert list(a) == list(b) == ["part-a", "badge"]
    assert {n: e.kind for n, e in a.items()} == {n: e.kind for n, e in b.items()} == {
        "part-a": "gradient", "badge": "flat"}
    assert {n: set(e.layers) for n, e in a.items()} == {n: set(e.layers) for n, e in b.items()}


# --- what segmentation drops ------------------------------------------------------------------

def test_dropped_components_lists_specks_and_wisps(canvas):
    drops = segment.dropped_components(canvas, RULES)
    assert [d.area for d in drops] == sorted((d.area for d in drops), reverse=True)
    by_pos = {d.centroid: d for d in drops}
    island = by_pos[(580, 324)]  # soft-only island: 10 x 10 px, alpha 50, white
    assert (island.area, island.max_alpha, island.color) == (100, 50, "#ffffff")
    far = by_pos[(300, 340)]  # far speck: 2 x 2 opaque teal px
    assert (far.area, far.max_alpha, far.color) == (4, 255, "#1478aa")
    # the near speck goes with its own fringe as one piece
    near = [d for d in drops if 205 <= d.centroid[0] < 220 and 146 <= d.centroid[1] < 155]
    assert len(near) == 1 and near[0].max_alpha == 255
    assert len(drops) == 3


def test_dropped_and_kept_pixels_partition_the_soft_pixels(canvas):
    canvas[312:315, 400:404] = (255, 255, 255, 30)  # a detached wisp within reach of the badge
    els = segment.split_elements(canvas, RULES)
    kept = np.logical_or.reduce([e.mask for e in els.values()])
    dropped = segment.dropped_mask(canvas, RULES)
    soft = canvas[..., 3] >= RULES["alpha_min"]
    assert not (dropped & kept).any()  # a dropped pixel is in no element
    assert ((dropped | kept) == soft).all()  # and every soft pixel is one or the other
    drops = segment.dropped_components(canvas, RULES)
    assert sum(d.area for d in drops) == int(dropped.sum())
    assert any(d.area == 12 and d.max_alpha == 30 for d in drops)


def test_nothing_dropped_from_clean_art():
    c = np.zeros((600, 600, 4), np.uint8)
    framed(c, 40, 40, 200, 300)
    rules = {**RULES, "regions": {"part-a": {"center": [0.0, 0.0, 1.0, 1.0]}}}
    assert segment.dropped_components(c, rules) == []
