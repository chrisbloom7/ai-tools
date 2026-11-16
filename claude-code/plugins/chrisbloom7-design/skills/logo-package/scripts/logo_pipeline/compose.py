"""Compose traced elements into the stacked lockup (every element) and a mark (one element).

Layers are drawn as stacked silhouettes, not as abutting rings: each layer's path is the union
of that layer and every layer drawn after it, so later layers cover the inside and no
anti-aliased seam can open between neighbors. The visible shape of every layer is unchanged.
Order: all halos first (so a halo never paints over a neighbor's body), then per element its
other layers from the outside in (mean depth inside the element).

The halo is a uniform-width band: the art's own soft rim is irregular (its faint alpha edge
wanders from 0 to several px off the outline), so it is not traced. Instead each element's
outer body silhouette is drawn again behind the bodies, stroked (round joins) to twice the
halo width, which is the silhouette offset outward by exactly that width everywhere. Width,
color and opacity are measured from the art once per variant (all elements pooled; see
`_halo_params`) and set once on a wrapper group (`n-halos`), whose group `opacity` makes
overlapping halos composite once. White that the body encloses and that is opaque (a white band
inside a mark) is paint, not glow, and is drawn as a solid layer. Every color is measured
from the art: flat layers use the mean of their opaque core, gradient layers
(Element.gradient_layers) a vertical `linearGradient` from `gradients.sample`.

The tracing and halo constants can be overridden in the `[compose]` table of brand.toml
(see `Settings` and `load_settings`).

Output is in source-pixel coordinates (viewBox = art bbox plus an even margin), with no
transforms: potrace's y-flip is applied to the points, because objectBoundingBox gradients are
laid out in the path's own user space and would otherwise paint upside down. Each layer is a
single <path>, so the gradient box is the whole layer. It is not minified (`minify.minify`
rounds it later and copies <defs> unchanged).
"""

import math
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

from . import gradients, minify, trace
from .config import BRAND  # brand.toml next to the package, else brand.example.toml
from .segment import Element
from .variants import SharedReport

HALO = "halo"
HALO_ALPHA = 48  # halo rim threshold: the band's width and opacity are measured from pixels
#                  at or above it (its uniform band of the median width at the median opacity
#                  carries about the same white as a typical art's fading rim)
OPAQUE = 128
HALO_GAP = 3  # px from the body; nearer halo pixels are edge blends, left out of its color
ERODE = 4  # px trimmed off a flat layer before taking its mean (drops edge blends)
MARGIN = 0.04  # share of the art's longer side added on every side of the viewBox
STOPS = 5
PAD = 8  # px of crop padding around an element before tracing (plus 3 sigma of the blur)
# Trace settings for trace.mask_to_svg, as tuned on TRACE_REF_PX (2400 px) art. `up` is the
# resample factor before potrace; `sigma` is in SOURCE px (the blur that smooths the edge
# before potrace); `alpha` and `opt` are potrace's -a (corner threshold) and -O.
# Unless brand.toml [compose] sets them, `up` and `sigma` follow the canvas (see
# `Settings.trace_opts`): up = ref up * 2400 / L and sigma = ref sigma * L / 2400, L being the
# larger side of the source canvas. So every canvas is traced at the same size (the lockup at
# 1200 px, the mark at 2400 px on the larger side) with the same blur in traced px.
TRACE_REF_PX = 2400
# Lockups are shown at 1200 px or less, so tracing at 1200 px is enough.
LOCKUP_TRACE = {"up": 0.5, "sigma": 1.5, "alpha": 1.1, "opt": 1.0}
# Marks are scaled UP (a 255 px mark fills about 370 px of a 512 px icon, 740 of the 1024
# SVG), so the lockup setting's kinks and texture lumps show. Full resolution, a 5 px blur and
# a softer corner threshold give smooth curves with no kinks while pointed shapes keep their
# points (chosen by eye from a sweep of up 0.5-2, sigma 1.5-12, alpha 1.0-1.33, opt 1-5).
MARK_TRACE = {"up": 1.0, "sigma": 5.0, "alpha": 1.2, "opt": 1.0}
TRACE_REF = {"lockup": LOCKUP_TRACE, "mark": MARK_TRACE}
SIMPLIFIED_DROP = ("outline", HALO)  # layers a simplified mark leaves out
DIGITS = 2  # decimals kept in path coordinates (source pixels); minify rounds further


def _fixed(ref: dict) -> dict:
    """The keys of a reference trace table that do not follow the canvas (alpha, opt)."""
    return {k: v for k, v in ref.items() if k not in ("up", "sigma")}


@dataclass(frozen=True)
class Settings:
    """The tunable constants of this module; the defaults are the in-code constants above.

    `load_settings` fills it from the `[compose]` table of brand.toml, whose keys are the
    constant names (HALO_ALPHA, HALO_GAP, ERODE, MARGIN, STOPS, LOCKUP_TRACE, MARK_TRACE).
    """

    halo_alpha: int = HALO_ALPHA
    halo_gap: int = HALO_GAP
    erode: int = ERODE
    margin: float = MARGIN
    stops: int = STOPS
    # alpha and opt, plus `up` and `sigma` only when [compose] sets them; `trace_opts` fills
    # in the canvas-scaled `up` and `sigma` for a given canvas.
    lockup_trace: dict = field(default_factory=lambda: _fixed(LOCKUP_TRACE))
    mark_trace: dict = field(default_factory=lambda: _fixed(MARK_TRACE))

    def trace_opts(self, kind: str, shape: tuple[int, ...]) -> dict:
        """Trace options for `kind` ("lockup" or "mark") on a canvas of `shape` (height, width).

        Keys set in [compose] win. Otherwise `alpha` and `opt` are the reference values and
        `up` and `sigma` scale with L, the larger canvas side: up = ref up * 2400 / L, sigma =
        ref sigma * L / 2400. At 2400 px they are exactly LOCKUP_TRACE and MARK_TRACE.
        """
        ref = TRACE_REF[kind]
        side = max(shape[:2])
        out = dict(ref)  # up and sigma are in every reference table
        out["up"] = ref["up"] * TRACE_REF_PX / side
        out["sigma"] = ref["sigma"] * side / TRACE_REF_PX
        out.update(getattr(self, f"{kind}_trace"))
        return out


def load_settings(path: Path | None = None) -> Settings:
    """Settings from the `[compose]` table of brand.toml; absent keys keep the defaults."""
    table = dict(tomllib.loads(Path(path or BRAND).read_text()).get("compose", {}))
    out = {}
    for f in fields(Settings):
        key = f.name.upper()
        if key not in table:
            continue
        val = table.pop(key)
        if key.endswith("_TRACE"):  # a partial table overrides only the keys it names
            base = TRACE_REF[f.name.removesuffix("_trace")]
            unknown = set(val) - set(base)
            if unknown:
                raise ValueError(f"brand.toml [compose] {key}: unknown key(s) {sorted(unknown)}")
            val = {**_fixed(base), **val}
        out[f.name] = val
    if table:
        raise ValueError(f"brand.toml [compose]: unknown key(s) {sorted(table)}")
    return Settings(**out)


def _resolve(settings: Settings | None, halo_alpha: int | None, trace_opts: dict | None,
             kind: str, shape: tuple[int, ...]) -> tuple[Settings, int, dict]:
    """(settings, halo alpha, trace options): brand.toml unless given; explicit knobs win.

    The trace options are resolved for the source canvas `shape` (see `Settings.trace_opts`).
    """
    st = settings or load_settings()
    return (st, st.halo_alpha if halo_alpha is None else halo_alpha,
            st.trace_opts(kind, shape) if trace_opts is None else trace_opts)


def stacked(variant: str, elements: dict[str, Element], shared: SharedReport | None = None,
            *, rgba: np.ndarray, halo_alpha: int | None = None,
            trace_opts: dict | None = None, settings: Settings | None = None) -> str:
    """Full lockup SVG for one variant: every element in `elements`, drawn in their order.

    The lockup is whatever segmentation returned (a required region that is missing already
    raised in `segment.split_elements`); no elements at all is a ValueError. `rgba` is that
    variant's source art (colors are measured from it). `shared` is accepted
    for pieces that are identical across variants; it is unused, so every
    element is traced from this variant's own masks. `settings` (default: brand.toml's
    `[compose]` table) supplies the tunables; `halo_alpha` and `trace_opts` override it.
    """
    st, halo_alpha, trace_opts = _resolve(settings, halo_alpha, trace_opts, "lockup",
                                          rgba.shape)
    if not elements:
        raise ValueError(f"{variant}: segmentation returned no elements, so there is nothing to "
                         "compose; check [elements] in brand.toml")
    return _compose(variant, elements, list(elements), rgba, halo_alpha, trace_opts, st)


def mark(variant: str, elements: dict[str, Element], *, rgba: np.ndarray,
         element: str, halo_alpha: int | None = None,
         trace_opts: dict | None = None, simplified: bool = False,
         settings: Settings | None = None) -> str:
    """The element named `element` alone (the build passes [brand] mark_element), with its own
    outline and halo.

    Traced finer and smoother than the lockup (MARK_TRACE, scaled to the canvas), because
    icons scale it up. Its
    halo is measured over every element in `elements`, so it matches the lockup's.

    `simplified` draws the body layers only (for example a badge's fill, without
    its outline): no outline, no halo (soft or solid white), and the viewBox hugs the body.
    It is for the 16 px favicon, where the outline would turn the small shapes to mush.
    """
    st, halo_alpha, trace_opts = _resolve(settings, halo_alpha, trace_opts, "mark", rgba.shape)
    return _compose(variant, elements, (element,), rgba, halo_alpha, trace_opts, st, simplified)


def _compose(variant, elements, names, rgba, halo_alpha, trace_opts, st, simplified=False):
    missing = [n for n in names if n not in elements]
    if missing:
        raise ValueError(f"{variant}: element(s) {', '.join(missing)} not found in the art; "
                         "check the regions in brand.toml")
    defs, halos, bodies, drawn = [], [], [], []
    for name in names:
        el = elements[name]
        if el.kind == "flat" and el.gradient_layers:
            raise ValueError(f"{name}: kind is 'flat' but it has gradient layers "
                             f"{list(el.gradient_layers)}")
        if el.kind == "gradient" and not el.gradient_layers:
            raise ValueError(f"{name}: kind is 'gradient' but it has no gradient layers")
        stack, has_halo = _stack(el, rgba, halo_alpha)
        if simplified:
            stack = [t for t in stack if t[0] not in SIMPLIFIED_DROP]
            has_halo = False
        for i, (layer, own, path_mask) in enumerate(stack):
            drawn.append(path_mask)
            attrs = f'class="n-{layer}" data-element="{name}"'
            if layer in el.gradient_layers:
                gid = f"{variant}-{name}-{layer}"
                defs.append(_gradient(gid, rgba, own, path_mask, st.stops))
                attrs += f' fill="url(#{gid})"'
            else:
                attrs += f' fill="{_flat_color(rgba, own, f"{name}/{layer}", st.erode)}"'
            path = _trace(path_mask, trace_opts)
            bodies.append(f"<g {attrs}>{path}</g>")
            if i == 0 and has_halo:  # the outermost silhouette, stroked, is the halo
                halos.append(f'<g class="n-halo" data-element="{name}">{path}</g>')
    halo_xml = ""
    if halos:
        color, opacity, width = _halo_params(elements, rgba, halo_alpha, st.halo_gap)
        halo_xml = (f'<g class="n-halos" fill="{color}" stroke="{color}" '
                    f'stroke-width="{2 * width:.3f}" stroke-linejoin="round" '
                    f'opacity="{opacity:.3f}" data-halo-px="{width:.2f}">{"".join(halos)}</g>')
    if simplified:  # hug the drawn body: bounding box of what is left, no margin
        x, y, w, h = _body_box(drawn)
    else:
        x, y, w, h = _viewbox([elements[n].bbox for n in names], st.margin)
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}">'
    defs_xml = f"<defs>{''.join(defs)}</defs>" if defs else ""
    return head + defs_xml + halo_xml + "".join(bodies) + "</svg>"


def _body_box(masks) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the pixels covered by any of `masks`."""
    both = np.logical_or.reduce(masks)
    rows, cols = np.nonzero(both.any(axis=1))[0], np.nonzero(both.any(axis=0))[0]
    return int(cols[0]), int(rows[0]), int(cols[-1] + 1 - cols[0]), int(rows[-1] + 1 - rows[0])


def _split_halo(el: Element, rgba):
    """(soft rim, enclosed solid white) parts of the halo layer.

    White that the body encloses and that is opaque on average (a white band inside a mark)
    is paint, not a glow: it joins the body stack as a solid layer. The rest is the soft rim.
    """
    halo = el.layers[HALO]
    body = el.mask & ~halo
    enclosed = halo & ndi.binary_fill_holes(body)
    solid = np.zeros_like(halo)
    parts, n = ndi.label(enclosed, structure=np.ones((3, 3)))
    if n:
        means = ndi.mean(rgba[..., 3], parts, range(1, n + 1))
        solid = np.isin(parts, [i + 1 for i, m in enumerate(means) if m >= OPAQUE])
    return halo & ~solid, solid


def _stack(el: Element, rgba, halo_alpha):
    """([(name, own mask, silhouette)] in drawing order, whether the element has a soft halo).

    Each silhouette is its own layer united with every layer drawn after it, so later layers
    cover the inside; they go outside in, so the first silhouette is the whole body. The soft
    halo is not a layer: it is drawn from that first silhouette (see `_compose`).
    """
    layers = {n: m for n, m in el.layers.items() if n != HALO}
    soft = None
    if HALO in el.layers:
        soft, solid = _split_halo(el, rgba)
        if solid.any():
            layers[HALO] = solid
    depth = ndi.distance_transform_edt(el.mask)
    order = sorted(layers, key=lambda n: float(depth[layers[n]].mean()))
    out, union = [], np.zeros(el.mask.shape, bool)
    for n in reversed(order):
        union = union | layers[n]
        out.append((n, layers[n], union))
    out.reverse()
    has_halo = soft is not None and bool((soft & (rgba[..., 3] >= halo_alpha)).any())
    return out, has_halo


def _halo_params(elements: dict[str, Element], rgba, halo_alpha,
                 halo_gap: int = HALO_GAP) -> tuple[str, float, float]:
    """(color, opacity, width in source px) of the art's halo, pooled over all `elements`.

    The rim is the soft halo pixels at or above `halo_alpha`; the body is everything else
    in the element (the drawn silhouette, so the band measured is the band that shows).
    Width: median distance from the body to the rim's outer edge pixels. Opacity: median
    alpha of the rim. Color: alpha-weighted mean of rim pixels at least `halo_gap` px from the
    body, so the blend into the outline does not tint it.
    """
    alpha = rgba[..., 3]
    widths, alphas, colors, weights = [], [], [], []
    for el in elements.values():
        if HALO not in el.layers:
            continue
        left, top, right, bottom = el.bbox
        sl = np.s_[max(0, top - PAD):bottom + PAD, max(0, left - PAD):right + PAD]
        soft, _ = _split_halo(el, rgba)
        a, mask, soft = alpha[sl], el.mask[sl], soft[sl]
        rim = soft & (a >= halo_alpha)
        body = mask & ~soft
        if not rim.any() or not body.any():
            continue
        dist = ndi.distance_transform_edt(~body)
        edge = rim & ~ndi.binary_erosion(rim | body)
        widths.append(dist[edge])
        alphas.append(a[rim])
        core = rim & (dist > halo_gap)
        if not core.any():
            core = rim
        colors.append(rgba[sl][..., :3][core].astype(np.float64))
        weights.append(a[core].astype(np.float64))
    if not alphas:
        raise ValueError("no halo rim in the art to measure")
    rgb, w = np.concatenate(colors), np.concatenate(weights)
    mean = (rgb * w[:, None]).sum(axis=0) / w.sum()
    color = "#" + "".join(f"{int(v):02x}" for v in np.clip(np.round(mean), 0, 255))
    return (color, float(np.median(np.concatenate(alphas)) / 255),
            float(np.median(np.concatenate(widths))))


def _trace(mask: np.ndarray, opts: dict = LOCKUP_TRACE) -> str:
    """Trace a canvas-sized mask (cropped for speed) as ONE path in canvas coordinates."""
    if not mask.any():
        raise ValueError("cannot trace an empty mask (a layer with no pixels)")
    pad = PAD + math.ceil(3 * opts["sigma"])  # room for the blur, so the crop edge never bends it
    ys, xs = np.nonzero(mask.any(axis=1))[0], np.nonzero(mask.any(axis=0))[0]
    y0, x0 = max(0, int(ys[0]) - pad), max(0, int(xs[0]) - pad)
    y1, x1 = min(mask.shape[0], int(ys[-1]) + 1 + pad), min(mask.shape[1], int(xs[-1]) + 1 + pad)
    up = opts["up"]
    g = trace.mask_to_svg(mask[y0:y1, x0:x1], up=up, sigma=opts["sigma"] * up,
                          alpha=opts["alpha"], opt=opts["opt"])
    # Apply potrace's nested transforms (one of them a y flip) to the points: objectBoundingBox
    # gradients are laid out in the path's own user space, so a flipped transform above the
    # path would paint the ramp upside down (and minify, which removes the flip, would not).
    m = minify.parse_transform(f"translate({x0},{y0})")
    for t in re.findall(r'<g transform="([^"]+)"', g):
        m = minify.compose_transforms(m, minify.parse_transform(t))
    # One path per layer, so the gradient box is the whole layer. Holes wind the other way, so
    # nonzero fill still cuts them out.
    segs = [s for d in re.findall(r'<path[^>]*\sd="([^"]+)"', g) for s in minify.subpaths(d)]
    return f'<path d="{minify.encode_path(segs, m, DIGITS)}"/>'


def _mean_rgb(rgba, sel, weights=None) -> str:
    rgb = rgba[..., :3][sel].astype(np.float64)
    if weights is None:
        m = rgb.mean(axis=0)
    else:
        m = (rgb * weights[:, None]).sum(axis=0) / weights.sum()
    return "#" + "".join(f"{int(v):02x}" for v in np.clip(np.round(m), 0, 255))


def _flat_color(rgba, layer, label: str = "layer", erode: int = ERODE) -> str:
    """Mean color of the layer's opaque core (eroded so edge blends do not tint it)."""
    opaque = rgba[..., 3] >= OPAQUE
    for sel in (ndi.binary_erosion(layer, iterations=erode) & opaque, layer & opaque):
        if sel.any():
            return _mean_rgb(rgba, sel)
    weights = rgba[..., 3][layer].astype(np.float64)
    if not weights.sum():
        raise ValueError(f"{label}: cannot measure a color, every pixel of the layer is "
                         "fully transparent")
    return _mean_rgb(rgba, layer, weights)


def _rows(mask):
    rows = np.nonzero(mask.any(axis=1))[0]
    return int(rows[0]), int(rows[-1])


def _gradient(gid, rgba, layer, path_mask, stops=STOPS) -> str:
    """Vertical linearGradient sampled from `layer`, its offsets mapped onto the painted path.

    `gradients.sample` puts offset 0 and 1 on the centers of the layer's top and bottom rows;
    objectBoundingBox spans the traced path's full extent, the rows of `path_mask`.
    """
    top, bottom = _rows(layer)
    ptop, pbottom = _rows(path_mask)
    span = pbottom + 1 - ptop
    out = []
    for off, color in gradients.sample(rgba, layer, stops=stops):
        y = top + 0.5 + off * (bottom - top)
        out.append(f'<stop offset="{(y - ptop) / span:.4f}" stop-color="{color}"/>')
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'{"".join(out)}</linearGradient>')


def _viewbox(bboxes, margin: float = MARGIN) -> tuple[int, int, int, int]:
    b = np.array(bboxes)
    left, top = b[:, :2].min(axis=0)
    right, bottom = b[:, 2:].max(axis=0)
    m = int(round(margin * max(right - left, bottom - top)))
    return int(left - m), int(top - m), int(right - left + 2 * m), int(bottom - top + 2 * m)
