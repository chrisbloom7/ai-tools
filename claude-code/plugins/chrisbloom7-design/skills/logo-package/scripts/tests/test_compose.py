import dataclasses
import re
import shutil
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from logo_pipeline import compose, gradients, minify, render, segment
from logo_pipeline.variants import SharedReport

pytestmark = pytest.mark.skipif(shutil.which("potrace") is None,
                                reason="potrace is needed to trace")

NS = {"s": "http://www.w3.org/2000/svg"}
TEAL = (20, 120, 170)
TOP = (240, 205, 70)
BOTTOM = (245, 125, 15)
GREEN = (70, 160, 90)
ORANGE = (220, 140, 60)

SIDE = 600  # fixture canvas; segment's size knobs are fractions of the canvas
RULES = {
    "area_floor": 200 / SIDE**2,  # 200 px
    "outline": "teal",
    "smooth": 5 / SIDE,  # 5 px
    "reach": 32 / SIDE,  # 32 px (the pixel values these fixtures were written against)
    "island_floor": 64 / SIDE**2,  # 64 px
    "palette": {
        "teal": ["#1478aa"],
        "halo": ["#ffffff"],
        "warm": ["#f0cd46", "#f57d0f"],
        "green": ["#46a05a"],
        "accent": ["#dc8c3c"],
    },
    # a 2 x 2 grid: flat green panel, flat accent badge (the mark), gradient seal, outline bar
    "regions": {
        "panel": {"center": [0.0, 0.0, 0.5, 0.45]},
        "badge": {"center": [0.5, 0.0, 1.0, 0.45]},
        "seal": {"center": [0.0, 0.45, 0.5, 1.0]},
        "bar": {"center": [0.5, 0.45, 1.0, 1.0]},
    },
}
MARK = "badge"  # the element the mark tests draw alone


def _mark(variant, elements, **kw):
    return compose.mark(variant, elements, element=MARK, **kw)


# Scenes that draw only some of the pieces: every region not drawn is optional.
PARTIAL = {**RULES, "regions": {k: {**v, "optional": True} for k, v in RULES["regions"].items()}}


def framed(c, x0, y0, x1, y1, inset=16, halo=8):
    """Teal box with a soft white halo; returns the inner (fill) slice."""
    c[y0 - halo:y1 + halo, x0 - halo:x1 + halo] = (255, 255, 255, 70)
    c[y0:y1, x0:x1] = (*TEAL, 255)
    return np.s_[y0 + inset:y1 - inset, x0 + inset:x1 - inset]


def ramp(h, w):
    t = np.linspace(0, 1, h)[:, None, None]
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = np.round((1 - t) * np.array(TOP) + t * np.array(BOTTOM))
    out[..., 3] = 255
    return out


@pytest.fixture(scope="module")
def art():
    c = np.zeros((600, 600, 4), np.uint8)
    c[framed(c, 40, 40, 260, 240)] = (*GREEN, 255)  # panel: flat green
    c[framed(c, 400, 60, 520, 180)] = (*ORANGE, 255)  # badge: flat accent
    inner = framed(c, 40, 320, 260, 560)  # seal: vertical yellow-to-orange ramp
    h, w = c[inner].shape[:2]
    c[inner] = ramp(h, w)
    framed(c, 340, 380, 560, 500)  # bar: outline only
    return c


@pytest.fixture(scope="module")
def elements(art):
    els = segment.split_elements(art, RULES)
    assert set(els) == set(RULES["regions"])
    return els


@pytest.fixture(scope="module")
def stacked_svg(art, elements):
    return compose.stacked("primary", elements, SharedReport(), rgba=art)


def groups(svg, element):
    root = ET.fromstring(svg)
    return [g for g in root.iter("{http://www.w3.org/2000/svg}g")
            if g.get("class", "").startswith("n-") and g.get("data-element") == element]


def test_gradient_element_has_linear_gradient_fill(art, elements, stacked_svg):
    root = ET.fromstring(stacked_svg)
    (fill,) = [g for g in groups(stacked_svg, "seal") if g.get("class") == "n-warm"]
    ref = re.fullmatch(r"url\(#([\w-]+)\)", fill.get("fill"))
    assert ref, fill.get("fill")
    grad = root.find(f".//s:linearGradient[@id='{ref.group(1)}']", NS)
    assert grad is not None
    assert grad.get("gradientUnits", "objectBoundingBox") == "objectBoundingBox"
    # vertical: top of the layer to its bottom
    assert (grad.get("x1"), grad.get("y1"), grad.get("x2"), grad.get("y2")) == ("0", "0", "0", "1")
    stops = [(float(s.get("offset")), s.get("stop-color")) for s in grad.findall("s:stop", NS)]
    expected = gradients.sample(art, elements["seal"].layers["warm"], stops=5)
    assert [c for _, c in stops] == [c for _, c in expected]
    assert stops[0][0] == pytest.approx(0.0, abs=0.02)
    assert stops[-1][0] == pytest.approx(1.0, abs=0.02)
    # the fill layer is one path, so objectBoundingBox spans the whole layer
    assert len(fill.findall(".//s:path", NS)) == 1
    # ids are unique per variant, element and layer
    assert ref.group(1) == "primary-seal-warm"


def test_flat_element_has_solid_fill_only(stacked_svg):
    gs = groups(stacked_svg, "panel")
    assert {g.get("class") for g in gs} == {"n-halo", "n-outline", "n-green"}
    fills = {g.get("class"): g.get("fill") for g in gs}
    assert fills.pop("n-halo") is None  # painted by the n-halos wrapper
    for f in fills.values():
        assert re.fullmatch(r"#[0-9a-f]{6}", f), f
    assert fills["n-green"] == "#46a05a"  # measured mean of the green fill
    assert fills["n-outline"] == "#1478aa"
    assert "linearGradient" not in "".join(ET.tostring(g, encoding="unicode") for g in gs)


def halo_wrapper(svg):
    (wrap,) = [g for g in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}g")
               if g.get("class") == "n-halos"]
    return wrap


def test_halo_has_measured_color_and_opacity(stacked_svg):
    wrap = halo_wrapper(stacked_svg)
    # measured away from the outline, so the teal edge blend does not tint the halo
    assert wrap.get("fill") == "#ffffff" and wrap.get("stroke") == "#ffffff"
    assert float(wrap.get("opacity")) == pytest.approx(70 / 255, abs=0.01)
    (halo,) = [g for g in groups(stacked_svg, "panel") if g.get("class") == "n-halo"]
    assert halo.findall(".//s:path", NS)


def test_halo_opacity_is_one_value_on_one_group(art):
    # elements whose rims differ in brightness still get ONE halo opacity (the median of the
    # art's halo pixels), set once as group opacity so overlapping halos composite once
    c = art.copy()
    c[312:320, 32:268] = (255, 255, 255, 140)  # seal: a brighter rim along its top
    els = segment.split_elements(c, RULES)
    svg = compose.stacked("primary", els, SharedReport(), rgba=c)
    root = ET.fromstring(svg)
    (wrap,) = [g for g in root.iter("{http://www.w3.org/2000/svg}g") if g.get("class") == "n-halos"]
    # the median of the art's rim alphas: most rims are 70, so the bright seal top does not move it
    assert float(wrap.get("opacity")) == pytest.approx(70 / 255, abs=0.01)
    halos = [g for g in root.iter("{http://www.w3.org/2000/svg}g")
             if g.get("class") == "n-halo" and g.get("fill") is None]
    assert {g.get("data-element") for g in halos} == set(RULES["regions"])
    assert all(g.get("fill-opacity") is None and g.get("opacity") is None for g in halos)
    assert all(g in list(wrap) for g in halos)
    assert "fill-opacity" not in svg


def _disc_art(widths):
    """Teal disc with an accent center and a soft white rim whose width varies with angle."""
    c = np.zeros((600, 600, 4), np.uint8)
    cy, cx, R = 110, 520, 50
    y, x = np.ogrid[:600, :600]
    r = np.hypot(y - cy, x - cx)
    theta = np.arctan2(y - cy, x - cx)
    c[r <= R + widths(theta)] = (255, 255, 255, 90)
    c[r <= R] = (*TEAL, 255)
    c[r <= R - 16] = (*ORANGE, 255)
    return c, (cx, cy)


def test_halo_is_a_uniform_band_around_the_outline():
    # the art's rim is 2 px wide on the left and 10 px on the right; the halo is drawn as the
    # outline silhouette offset by ONE measured width (median), so the band is even all round
    def widths(t):
        return 2 + 8 * np.abs(np.cos(t / 2))
    c, (cx, cy) = _disc_art(widths)
    els = segment.split_elements(c, PARTIAL)
    svg = _mark("primary", els, rgba=c)
    root = ET.fromstring(svg)
    wrap = halo_wrapper(svg)
    w = float(wrap.get("data-halo-px"))
    assert float(wrap.get("stroke-width")) == pytest.approx(2 * w)
    assert wrap.get("stroke-linejoin") == "round"
    # the halo is the outline silhouette itself, stroked: same path, so the offset is exact
    (halo,) = [g for g in wrap if g.get("data-element") == MARK]
    (outline,) = [g for g in root.iter("{http://www.w3.org/2000/svg}g")
                  if g.get("class") == "n-outline"]
    assert halo.find("s:path", NS).get("d") == outline.find("s:path", NS).get("d")
    # the width is the median of the art's rim widths
    t = np.linspace(-np.pi, np.pi, 3600, endpoint=False)
    assert w == pytest.approx(np.median(widths(t)), abs=1.0)
    # rendered: count translucent band pixels along rays; the band is even all round
    x, y, vw, vh = (float(v) for v in root.get("viewBox").split())
    k = 4  # px per source px
    a = render.svg_to_png(svg, int(vw * k), int(vh * k))[..., 3].astype(int)
    bands = []
    for ang in np.linspace(-np.pi, np.pi, 24, endpoint=False):
        rr = np.arange(40, 63, 1 / k)  # body edge at 50, band ends near 58
        px = np.round((cx - x + rr * np.cos(ang)) * k).astype(int)
        py = np.round((cy - y + rr * np.sin(ang)) * k).astype(int)
        line = a[py, px]
        band = (line > 0.5 * 90) & (line < 0.5 * (90 + 255))
        bands.append(band.sum() / k)
    assert max(bands) - min(bands) <= 1.5, bands
    assert np.median(bands) == pytest.approx(w, abs=1.0)


def _bending_energy(d):
    """Sum of squared turning (radians) per 1 px step along every contour of a path.

    This is the discrete bending energy (integral of curvature squared over arc length). For
    the same overall shape, every lump or wobble adds curvature, so a smoother trace of the
    same art scores lower; a smooth curve is the shape that minimizes it.
    """
    total, contours, pts, cur = 0.0, [], [], None
    for sg in minify.subpaths(d):
        if sg[0] == "M":
            if len(pts) > 2:
                contours.append(np.array(pts))
            pts, cur = [], np.array(sg[1])
        elif sg[0] in "LC":
            ctrl = [cur] + [np.array(p) for p in sg[1:]]
            if sg[0] == "L":
                ctrl = [cur, cur, ctrl[1], ctrl[1]]
            t = np.linspace(0, 1, 25)[1:, None]
            p0, p1, p2, p3 = ctrl
            pts += list((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
                        + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)
            cur = p3
    if len(pts) > 2:
        contours.append(np.array(pts))
    for p in contours:  # resample at 1 px steps, then sum the squared turning
        q = np.vstack([p, p[:1]])
        s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(q, axis=0).T))])
        u = np.arange(0, s[-1], 1.0)
        r = np.stack([np.interp(u, s, q[:, 0]), np.interp(u, s, q[:, 1])], 1)
        v = np.roll(r, -1, 0) - r
        a = np.arctan2(v[:, 1], v[:, 0])
        da = (np.roll(a, -1) - a + np.pi) % (2 * np.pi) - np.pi
        total += float((da ** 2).sum())
    return total


def test_trace_rejects_an_empty_mask():
    with pytest.raises(ValueError, match="empty"):
        compose._trace(np.zeros((20, 20), bool))


def test_mark_contains_only_the_mark_element_paths(art, elements):
    svg = _mark("primary", elements, rgba=art)
    root = ET.fromstring(svg)
    tagged = {g.get("data-element") for g in root.iter("{http://www.w3.org/2000/svg}g")
              if g.get("data-element")}
    assert tagged == {MARK}
    paths = root.findall(".//s:path", NS)
    assert paths
    in_mark = [p for g in root.iter("{http://www.w3.org/2000/svg}g")
                    if g.get("data-element") == MARK
                    for p in g.iter("{http://www.w3.org/2000/svg}path")]
    assert len(in_mark) == len(paths)
    x, y, w, h = (float(v) for v in root.get("viewBox").split())
    left, top, right, bottom = elements[MARK].bbox
    assert x < left and y < top and x + w > right and y + h > bottom
    assert w < 200 and h < 200  # framed to the mark element, not the canvas


def test_stacked_viewbox_has_margin(elements, stacked_svg):
    root = ET.fromstring(stacked_svg)
    x, y, w, h = (float(v) for v in root.get("viewBox").split())
    boxes = np.array([e.bbox for e in elements.values()])
    left, top = boxes[:, :2].min(axis=0)
    right, bottom = boxes[:, 2:].max(axis=0)
    margins = (left - x, top - y, x + w - right, y + h - bottom)
    assert min(margins) > 0
    assert max(margins) - min(margins) <= 1  # even on every side


def _drawn(svg):
    return [g.get("data-element") for g in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}g")
            if g.get("class", "").startswith("n-") and g.get("data-element")
            and g.get("class") != "n-halo"]


@pytest.mark.parametrize("missing", ["panel", "badge", "seal", "bar"])
def test_stacked_draws_every_element_it_is_given_in_order(art, elements, missing):
    # no fixed element list: whatever segmentation returned is the lockup (a required region
    # that is missing already raised in segment)
    els = {k: v for k, v in elements.items() if k != missing}
    drawn = _drawn(compose.stacked("primary", els, SharedReport(), rgba=art))
    assert list(dict.fromkeys(drawn)) == list(els)


def test_stacked_with_no_elements_raises(art):
    with pytest.raises(ValueError, match="no elements"):
        compose.stacked("primary", {}, SharedReport(), rgba=art)


def test_mark_draws_the_element_named_by_the_keyword(art, elements):
    svg = compose.mark("primary", elements, rgba=art, element="panel")
    assert set(_drawn(svg)) == {"panel"}
    left, top, right, bottom = elements["panel"].bbox
    x, y, w, h = (float(v) for v in ET.fromstring(svg).get("viewBox").split())
    assert x < left and y < top and x + w > right and y + h > bottom
    assert w < right - left + 100  # framed to the panel, not the canvas


def test_mark_missing_named_element_raises(art, elements):
    with pytest.raises(ValueError, match="symbol"):
        compose.mark("primary", elements, rgba=art, element="symbol")


def test_mark_requires_the_element_keyword(art, elements):
    # no default element: the build always passes [brand] mark_element
    with pytest.raises(TypeError, match="element"):
        compose.mark("primary", elements, rgba=art)


def test_output_survives_minify(stacked_svg):
    small = minify.minify(stacked_svg)
    root = ET.fromstring(small)
    assert root.find(".//s:linearGradient", NS) is not None
    assert 'fill="url(#primary-seal-warm)"' in small
    assert "transform=" not in small


def _path_y_extent(d):
    """Exact-enough y extent of a path: endpoints plus sampled cubic curves."""
    ys = []
    cur = (0.0, 0.0)
    for sg in minify.subpaths(d):
        if sg[0] == "Z":
            continue
        if sg[0] == "C":
            t = np.linspace(0, 1, 33)[:, None]
            p0, p1, p2, p3 = (np.array(p) for p in (cur, *sg[1:]))
            ys.extend((((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1
                       + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)[:, 1])
        else:
            ys.append(sg[1][1])
        cur = sg[-1]
    return min(ys), max(ys)


def test_gradient_spans_its_layer_top_to_bottom(elements, stacked_svg):
    # objectBoundingBox is measured in the path's own user space: a flipped (potrace
    # y-up) transform above the path would turn the gradient upside down, so compose writes
    # paths in canvas coordinates with no transforms at all
    assert "transform=" not in stacked_svg
    (fill,) = [g for g in groups(stacked_svg, "seal") if g.get("class") == "n-warm"]
    lo, hi = _path_y_extent(fill.find("s:path", NS).get("d"))
    rows = np.nonzero(elements["seal"].layers["warm"].any(axis=1))[0]
    assert lo == pytest.approx(rows[0], abs=2) and hi == pytest.approx(rows[-1] + 1, abs=2)


def test_enclosed_opaque_white_is_solid_not_halo():
    # a mark can have an opaque white band inside its teal outline: it is drawn as a solid
    # layer in the body, while the soft white rim outside stays a translucent halo
    c = np.zeros((600, 600, 4), np.uint8)
    framed(c, 440, 60, 580, 200)
    c[80:180, 460:560] = (255, 255, 255, 255)  # opaque white band inside the outline
    c[96:164, 476:544] = (*ORANGE, 255)
    els = segment.split_elements(c, PARTIAL)
    svg = _mark("alt", els, rgba=c)
    root = ET.fromstring(svg)
    halos = [g for g in root.iter("{http://www.w3.org/2000/svg}g") if g.get("class") == "n-halo"]
    assert len(halos) == 2
    soft, solid = halos
    (wrap,) = [g for g in root.iter("{http://www.w3.org/2000/svg}g") if g.get("class") == "n-halos"]
    assert float(wrap.get("opacity")) == pytest.approx(70 / 255, abs=0.01)
    assert soft in list(wrap)
    assert solid.get("fill") == "#ffffff" and solid.get("fill-opacity") is None
    assert solid.get("opacity") is None
    order = [g.get("class") for g in root.iter("{http://www.w3.org/2000/svg}g") if g.get("class")]
    assert order == ["n-halos", "n-halo", "n-outline", "n-halo", "n-accent"]


def _classes(svg):
    return [g.get("class") for g in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}g")
            if g.get("class")]


def test_simplified_mark_drops_outline_and_halo_and_keeps_the_body(art, elements):
    full = _mark("primary", elements, rgba=art)
    simple = _mark("primary", elements, rgba=art, simplified=True)
    assert "n-outline" in _classes(full) and "n-halos" in _classes(full)
    assert _classes(simple) == ["n-accent"]
    # the body layer is painted with the same color as in the full mark
    fill = lambda svg: [g.get("fill")
                        for g in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}g")
                        if g.get("class") == "n-accent"]
    assert fill(simple) == fill(full)


def test_simplified_viewbox_hugs_the_body_not_the_halo(art, elements):
    def vb(svg):
        return [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    full = vb(_mark("primary", elements, rgba=art))
    simple = vb(_mark("primary", elements, rgba=art, simplified=True))
    assert simple[2] < full[2] and simple[3] < full[3]
    # the accent fill is inside 400..520 x 60..180 minus the 16 px inset
    assert simple[2] == pytest.approx(120 - 32, abs=3)


def test_default_mark_is_not_simplified(art, elements):
    full = _mark("primary", elements, rgba=art)
    assert 'class="n-outline"' in full and 'class="n-halos"' in full
    simple = _mark("primary", elements, rgba=art, simplified=True)
    assert "n-outline" not in simple and "n-halos" not in simple and "n-halo" not in simple


def test_flat_element_with_gradient_layers_is_rejected(art, elements):
    bad = {**elements, MARK: dataclasses.replace(
        elements[MARK], kind="flat", gradient_layers=["accent"])}
    with pytest.raises(ValueError, match=f"{MARK}.*flat"):
        _mark("primary", bad, rgba=art)


def test_gradient_element_without_gradient_layers_is_rejected(art, elements):
    bad = {**elements, MARK: dataclasses.replace(
        elements[MARK], kind="gradient", gradient_layers=[])}
    with pytest.raises(ValueError, match=f"{MARK}.*gradient"):
        _mark("primary", bad, rgba=art)


def test_flat_color_with_no_alpha_names_the_layer_instead_of_dividing_by_zero():
    rgba = np.zeros((10, 10, 4), np.uint8)
    layer = np.zeros((10, 10), bool)
    layer[2:5, 2:5] = True
    with pytest.raises(ValueError, match="panel.*green"):
        compose._flat_color(rgba, layer, "panel/green")


def test_shipped_brand_toml_reproduces_the_in_code_defaults(art, elements):
    assert compose.load_settings() == compose.Settings()
    assert (_mark("primary", elements, rgba=art)
            == _mark("primary", elements, rgba=art, settings=compose.Settings()))


def test_brand_toml_compose_table_overrides_defaults(tmp_path, art, elements):
    cfg = tmp_path / "brand.toml"
    cfg.write_text("[compose]\nMARGIN = 0.2\nERODE = 2\n"
                   "MARK_TRACE = { sigma = 2.0 }\n")
    st = compose.load_settings(cfg)
    assert st.margin == 0.2 and st.erode == 2
    # the fixed keys plus what the table names; up stays unset (it follows the canvas)
    assert st.mark_trace == {"alpha": 1.2, "opt": 1.0, "sigma": 2.0}
    # partial tables merge with the canvas-derived defaults
    assert st.trace_opts("mark", (2400, 2400)) == {**compose.MARK_TRACE, "sigma": 2.0}
    assert st.halo_alpha == compose.HALO_ALPHA  # absent key keeps the in-code default
    base = compose.stacked("primary", elements, rgba=art)
    over = compose.stacked("primary", elements, rgba=art, settings=st)
    assert base != over
    vb = lambda svg: [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    assert vb(over)[2] > vb(base)[2]
    assert (_mark("primary", elements, rgba=art)
            != _mark("primary", elements, rgba=art, settings=st))


def test_trace_settings_at_2400_px_are_todays_values():
    st = compose.Settings()
    assert st.trace_opts("lockup", (2400, 2400)) == {"up": 0.5, "sigma": 1.5, "alpha": 1.1,
                                                     "opt": 1.0}
    assert st.trace_opts("mark", (2400, 2400)) == {"up": 1.0, "sigma": 5.0, "alpha": 1.2,
                                                   "opt": 1.0}
    assert st.trace_opts("lockup", (2400, 2400)) == compose.LOCKUP_TRACE
    assert st.trace_opts("mark", (2400, 2400)) == compose.MARK_TRACE


@pytest.mark.parametrize("shape", [(600, 600), (1200, 1200), (600, 1200), (1200, 900)])
def test_trace_settings_follow_the_larger_canvas_side(shape):
    side = max(shape)
    st = compose.Settings()
    lockup, mark = st.trace_opts("lockup", shape), st.trace_opts("mark", shape)
    assert lockup["up"] == pytest.approx(1200 / side)
    assert mark["up"] == pytest.approx(2400 / side)
    # the blur is a length in source px: it scales with the art, so it is the same number of
    # traced px at every size
    assert lockup["sigma"] == pytest.approx(1.5 * side / 2400)
    assert mark["sigma"] == pytest.approx(5.0 * side / 2400)
    assert (lockup["alpha"], lockup["opt"], mark["alpha"], mark["opt"]) == (1.1, 1.0, 1.2, 1.0)


def test_explicit_trace_settings_win_over_the_canvas_defaults(tmp_path):
    cfg = tmp_path / "brand.toml"
    cfg.write_text("[compose]\nLOCKUP_TRACE = { up = 1.0 }\nMARK_TRACE = { sigma = 3.0 }\n")
    st = compose.load_settings(cfg)
    lockup, mark = st.trace_opts("lockup", (600, 600)), st.trace_opts("mark", (600, 600))
    assert lockup["up"] == 1.0  # set: wins
    assert lockup["sigma"] == pytest.approx(1.5 * 600 / 2400)  # not set: scaled
    assert mark["sigma"] == 3.0  # set: wins
    assert mark["up"] == pytest.approx(4.0)  # not set: from the canvas


def test_stacked_and_mark_trace_at_the_canvas_scale(monkeypatch, art, elements):
    seen = []
    real = compose.trace.mask_to_svg

    def spy(mask, **kw):
        seen.append(kw["up"])
        return real(mask, **kw)

    monkeypatch.setattr(compose.trace, "mask_to_svg", spy)
    compose.stacked("primary", elements, rgba=art)
    assert set(seen) == {1200 / 600}
    seen.clear()
    _mark("primary", elements, rgba=art)
    assert set(seen) == {2400 / 600}


def test_unknown_compose_key_is_rejected(tmp_path):
    cfg = tmp_path / "brand.toml"
    cfg.write_text("[compose]\nMARGN = 0.2\n")
    with pytest.raises(ValueError, match="MARGN"):
        compose.load_settings(cfg)
