"""Split a flat RGBA logo into named elements, each with per-color layers.

Pipeline: opaque connected components (8-connected, so 1 px textured-edge pixels stay with their
body) -> drop specks under an area floor -> attach soft pixels (anti-aliased edges, halo) that
touch a kept component to the nearest one -> group components into elements by where their
bbox center falls (`regions` in brand.toml) -> classify each element pixel to the nearest
palette entry (a palette entry is a ramp of one or more anchor colors) -> mode-filter the
classes and fold islands under `island_floor` (all size knobs are fractions of the canvas)
into their surround, to clean texture flecks -> decide flat or gradient per fill layer from a
real vertical color ramp (`_is_ramp`).

`dropped_components` lists what this leaves out (specks and detached wisps), for the report.
"""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

# Same numbers as brand.toml [elements], which overrides these. The four size knobs are
# fractions of the canvas, so they scale with the image; the values below reproduce 2000 px,
# 32 px, 7 px and 64 px on a 2400 x 2400 canvas.
DEFAULTS = {
    "alpha_solid": 128,  # alpha at or above this forms components (and is "opaque")
    "alpha_min": 16,  # soft pixels at or above this can join a nearby component
    "area_floor": 3.47222e-4,  # fraction of canvas area; smaller opaque components are specks
    "reach": 0.0133333,  # fraction of the canvas side; soft pixels farther than this from a
    #                      kept component are dropped
    "smooth": 0.0029167,  # fraction of the canvas side; mode-filter window, rounded to an odd
    #                       pixel count (at least 1; 1 disables)
    "island_floor": 1.11111e-5,  # fraction of canvas area; smaller same-class islands take
    #                              their surrounding class
    "ramp_bands": 16,  # row bands used to measure a fill's vertical color profile
    "ramp_min": 30.0,  # RGB distance the band means must span to count as a gradient
    "jump_max": 0.4,  # largest single band step, as a share of the path, still "smooth"
    "erode": 4,  # px trimmed off a fill layer before measuring (drops edge blends)
}


@dataclass
class Element:
    """One named piece of the art.

    mask: every pixel of the element with alpha >= alpha_min (body, anti-aliased edge and
        halo), canvas-sized bool array.
    bbox: (left, top, right, bottom) of `mask`, right and bottom exclusive (PIL crop order).
    kind: "gradient" when any fill layer carries a smooth vertical color ramp, else "flat".
    layers: an exclusive partition of `mask` by palette name; the palette entry named by
        `outline` in the rules is stored under the key "outline". Canvas-sized bool arrays.
    gradient_layers: the layer names that carry a ramp (empty when kind is "flat"); compose
        fills these with a linearGradient sampled from that same layer, the rest solid.
    """

    mask: np.ndarray
    bbox: tuple[int, int, int, int]
    kind: Literal["flat", "gradient"]
    layers: dict[str, np.ndarray]
    gradient_layers: list[str] = field(default_factory=list)


def pixel_knobs(cfg: dict, shape: tuple[int, int]) -> dict[str, int]:
    """Turn the fractional size knobs into pixels for a canvas of `shape` (height, width).

    `area_floor` and `island_floor` are fractions of the canvas area; `reach` and `smooth` are
    fractions of the shorter side. `smooth` is rounded to an odd count of at least 1. A value
    outside [0, 1) raises ValueError (it is probably an old pixel count).
    """
    h, w = shape
    side, area = min(h, w), h * w
    for key in ("area_floor", "reach", "smooth", "island_floor"):
        if not 0 <= cfg[key] < 1:
            raise ValueError(f"{key} is {cfg[key]!r}: it must be a fraction of the canvas "
                             "(0 up to, not including, 1), not a pixel count")
    smooth = round(cfg["smooth"] * side)
    smooth = max(1, smooth + 1 if smooth % 2 == 0 else smooth)
    return {"area_floor": round(cfg["area_floor"] * area), "reach": round(cfg["reach"] * side),
            "smooth": smooth, "island_floor": round(cfg["island_floor"] * area)}


def _rgb(hex_color: str) -> np.ndarray:
    h = hex_color.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)


def _ramp_distance(px: np.ndarray, anchors: list[str]) -> np.ndarray:
    """Distance from each RGB pixel (n, 3) to the polyline through the anchor colors."""
    pts = [_rgb(a) for a in anchors]
    if len(pts) == 1:
        return np.linalg.norm(px - pts[0], axis=1)
    best = np.full(len(px), np.inf)
    for a, b in zip(pts, pts[1:]):
        ab = b - a
        t = np.clip(((px - a) @ ab) / (ab @ ab), 0.0, 1.0)
        best = np.minimum(best, np.linalg.norm(px - (a + t[:, None] * ab), axis=1))
    return best


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys = np.nonzero(mask.any(axis=1))[0]
    xs = np.nonzero(mask.any(axis=0))[0]
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


def _region_for(center: tuple[float, float], regions: dict, bbox) -> str:
    cx, cy = center
    hits = [name for name, r in regions.items()
            if r["center"][0] <= cx < r["center"][2] and r["center"][1] <= cy < r["center"][3]]
    if not hits:
        raise ValueError(f"no element rule matches the component at bbox {bbox} "
                         f"(center {cx:.3f}, {cy:.3f} of canvas); add or widen a region")
    if len(hits) > 1:
        raise ValueError(f"component at bbox {bbox} matches several regions {hits}; "
                         "make the regions not overlap")
    return hits[0]


def _is_ramp(rgba: np.ndarray, layer: np.ndarray, cfg: dict) -> bool:
    """True when the layer's mean color per row band changes smoothly and substantially."""
    body = ndi.binary_erosion(layer, iterations=cfg["erode"]) if cfg["erode"] else layer
    body = body & (rgba[..., 3] >= cfg["alpha_solid"])
    profile = ramp_profile(rgba, body, cfg["ramp_bands"])
    if len(profile) < 3:
        return False
    steps = np.linalg.norm(np.diff(profile, axis=0), axis=1)
    path = steps.sum()
    span = max(np.linalg.norm(p - q) for p in profile for q in profile)
    return bool(span >= cfg["ramp_min"] and steps.max() <= cfg["jump_max"] * path)


def ramp_profile(rgba: np.ndarray, body: np.ndarray, bands: int) -> np.ndarray:
    """Mean RGB per row band of `body`, top to bottom; bands with too few pixels skipped."""
    rows = np.nonzero(body.any(axis=1))[0]
    if len(rows) < bands:
        return np.empty((0, 3))
    rgb = rgba[..., :3].astype(np.float64)
    count = body.sum(axis=1)
    total = (rgb * body[..., None]).sum(axis=1)
    floor = max(1, int(body.sum() / bands * 0.05))
    out = []
    for chunk in np.array_split(np.arange(rows[0], rows[-1] + 1), bands):
        n = count[chunk].sum()
        if n >= floor:
            out.append(total[chunk].sum(axis=0) / n)
    return np.array(out)


def _layers(rgba: np.ndarray, mask: np.ndarray, palette: dict, names: list[str],
            outline: str, smooth: int, island_floor: int) -> dict[str, np.ndarray]:
    left, top, right, bottom = _bbox(mask)
    crop = mask[top:bottom, left:right]
    px = rgba[top:bottom, left:right, :3][crop].astype(np.float64)
    dist = np.stack([_ramp_distance(px, palette[n]) for n in names])
    cls = np.full(crop.shape, -1, dtype=np.int16)
    cls[crop] = dist.argmin(axis=0)
    if smooth > 1 and len(names) > 1:  # mode filter: each pixel takes its neighborhood's class
        votes = np.stack([ndi.uniform_filter((cls == k).astype(np.float32), smooth)
                          for k in range(len(names))])
        cls[crop] = votes.argmax(axis=0)[crop]
    if island_floor and len(names) > 1:  # flecks too big for the filter join their surround
        for k in range(len(names)):
            islands, n = ndi.label(cls == k, structure=np.ones((3, 3)))
            if not n:
                continue
            sizes = ndi.sum(cls == k, islands, range(1, n + 1))
            for i, sl in enumerate(ndi.find_objects(islands), start=1):
                if sizes[i - 1] >= island_floor:
                    continue
                pad = tuple(slice(max(0, s.start - 2), s.stop + 2) for s in sl)
                island = islands[pad] == i
                ring = ndi.binary_dilation(island, iterations=2) & ~island
                around = cls[pad][ring]
                around = around[around >= 0]
                if len(around):
                    cls[pad][island] = np.bincount(around).argmax()
    out = {}
    for k, name in enumerate(names):
        layer = np.zeros(mask.shape, bool)
        layer[top:bottom, left:right] = cls == k
        if layer.any():
            out["outline" if name == outline else name] = layer
    return out


@dataclass(frozen=True)
class Dropped:
    """One detached piece of the art that segmentation leaves out of every element.

    area: pixels (alpha at or above alpha_min); max_alpha: its most opaque pixel (at or above
    alpha_solid it holds a speck under the area floor, else it is a faint wisp); centroid:
    (x, y) mean pixel position, rounded; color: "#rrggbb" plain mean of its pixels' color.
    """

    area: int
    max_alpha: int
    centroid: tuple[int, int]
    color: str


def _ownership(rgba: np.ndarray, cfg: dict, px: dict) -> tuple[np.ndarray, np.ndarray, set]:
    """(owner, labels, kept): each pixel's owning opaque component (0: none), the component
    labels, and the ids of the components kept (at or above the area floor)."""
    alpha = rgba[..., 3]
    solid = alpha >= cfg["alpha_solid"]
    labels, count = ndi.label(solid, structure=np.ones((3, 3)))
    ids = np.arange(1, count + 1)
    areas = ndi.sum(solid, labels, ids) if count else []
    kept = {int(i) for i, a in zip(ids, areas) if a >= px["area_floor"]}

    # Attach every soft pixel to its nearest component (specks included, so a speck's own
    # fringe goes with it), then drop specks, anything beyond reach, and soft pixels that do
    # not touch a kept component through other soft pixels (detached wisps).
    soft = alpha >= cfg["alpha_min"]
    dist, (iy, ix) = ndi.distance_transform_edt(labels == 0, return_indices=True)
    owner = labels[iy, ix]
    owner[~soft | (dist > px["reach"])] = 0
    owner[~np.isin(owner, list(kept))] = 0
    patches, _ = ndi.label(soft, structure=np.ones((3, 3)))
    attached = np.unique(patches[np.isin(labels, list(kept))])
    owner[~np.isin(patches, attached)] = 0
    return owner, labels, kept


@dataclass(frozen=True)
class Blob:
    """One kept opaque component, as `split_elements` sees it before grouping into regions.

    area: opaque pixels (alpha at or above alpha_solid); bbox: (left, top, right, bottom) in
    pixels, right and bottom exclusive; center: the bbox center as fractions of the canvas
    (x, y), the point a region's `center` box must hold; color: "#rrggbb" mean of its opaque
    pixels.
    """

    area: int
    bbox: tuple[int, int, int, int]
    center: tuple[float, float]
    color: str


def blobs(rgba: np.ndarray, rules: dict | None = None) -> list[Blob]:
    """The opaque components `split_elements` keeps (at or above the area floor), in label
    order (top to bottom, then left to right), for writing `[elements.regions]` boxes."""
    cfg = {**DEFAULTS, **(rules or {})}
    h, w = rgba.shape[:2]
    _, labels, kept = _ownership(rgba, cfg, pixel_knobs(cfg, (h, w)))
    solid = rgba[..., 3] >= cfg["alpha_solid"]
    out = []
    for i, sl in enumerate(ndi.find_objects(labels), start=1):
        if i not in kept:
            continue
        box = (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop)
        m = (labels[sl] == i) & solid[sl]
        rgb = rgba[sl][..., :3][m].astype(np.float64).mean(axis=0)
        color = "#" + "".join(f"{int(v):02x}" for v in np.clip(np.round(rgb), 0, 255))
        out.append(Blob(int(m.sum()), box,
                        ((box[0] + box[2]) / 2 / w, (box[1] + box[3]) / 2 / h), color))
    return out


def dropped_mask(rgba: np.ndarray, rules: dict) -> np.ndarray:
    """The soft pixels (alpha at or above alpha_min) that `split_elements` puts in no element:
    specks under the area floor with their fringe, pixels beyond reach and detached wisps."""
    cfg = {**DEFAULTS, **rules}
    owner, _, _ = _ownership(rgba, cfg, pixel_knobs(cfg, rgba.shape[:2]))
    return (rgba[..., 3] >= cfg["alpha_min"]) & (owner == 0)


def dropped_components(rgba: np.ndarray, rules: dict) -> list[Dropped]:
    """The connected (8-neighbor) pieces of `dropped_mask`, largest first."""
    mask = dropped_mask(rgba, rules)
    labels, n = ndi.label(mask, structure=np.ones((3, 3)))
    out = []
    for i, sl in enumerate(ndi.find_objects(labels), start=1):
        m = labels[sl] == i
        ys, xs = np.nonzero(m)
        rgb = rgba[sl][..., :3][m].astype(np.float64).mean(axis=0)
        color = "#" + "".join(f"{int(v):02x}" for v in np.clip(np.round(rgb), 0, 255))
        out.append(Dropped(int(m.sum()), int(rgba[sl][..., 3][m].max()),
                           (int(round(xs.mean() + sl[1].start)),
                            int(round(ys.mean() + sl[0].start))), color))
    return sorted(out, key=lambda d: (-d.area, d.centroid[1], d.centroid[0]))


def split_elements(rgba: np.ndarray, rules: dict) -> dict[str, "Element"]:
    """Split the art into the elements named in `rules["regions"]` (brand.toml [elements]).

    Raises ValueError when a region matches no component of the art (name the element; set
    `optional = true` on the region to allow its absence), and when a kept component matches
    no region or several. The size knobs are fractions of the canvas (see `pixel_knobs`).
    What it leaves out is `dropped_mask` / `dropped_components`.
    """
    cfg = {**DEFAULTS, **rules}
    palette, regions, outline = cfg["palette"], cfg["regions"], cfg["outline"]
    h, w = rgba.shape[:2]
    px = pixel_knobs(cfg, (h, w))
    owner, labels, kept = _ownership(rgba, cfg, px)

    groups: dict[str, list[int]] = {}
    for i, sl in enumerate(ndi.find_objects(labels), start=1):
        if i not in kept:
            continue
        box = (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop)
        center = ((box[0] + box[2]) / 2 / w, (box[1] + box[3]) / 2 / h)
        groups.setdefault(_region_for(center, regions, box), []).append(i)

    elements = {}
    for name in regions:
        if name not in groups:
            if regions[name].get("optional", False):
                continue
            raise ValueError(
                f"element {name!r}: no component of the art has its bbox center in the region "
                f"{regions[name]['center']}; fix the region in brand.toml or set "
                "`optional = true` on it")
        mask = np.isin(owner, groups[name])
        names = list(regions[name].get("palette", palette))
        layers = _layers(rgba, mask, palette, names, outline, px["smooth"],
                         px["island_floor"])
        ramps = [n for n, layer in layers.items() if n != "outline" and _is_ramp(rgba, layer, cfg)]
        elements[name] = Element(mask, _bbox(mask), "gradient" if ramps else "flat", layers,
                                 ramps)
    return elements


def overlay(rgba: np.ndarray, elements: dict[str, Element], width: int = 1200) -> Image.Image:
    """Art on gray with each element tinted, boxed and labeled with its name and kind."""
    hues = [(230, 60, 60), (60, 120, 230), (240, 180, 0), (160, 60, 200), (0, 170, 110),
            (240, 110, 180), (90, 90, 90)]
    h, w = rgba.shape[:2]
    base = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    base.alpha_composite(Image.fromarray(rgba))
    tint = np.zeros((h, w, 4), np.uint8)
    for k, el in enumerate(elements.values()):
        tint[el.mask] = (*hues[k % len(hues)], 110)
    base.alpha_composite(Image.fromarray(tint))
    draw = ImageDraw.Draw(base)
    font = ImageFont.load_default(size=max(12, h // 40))
    for k, (name, el) in enumerate(elements.items()):
        color = hues[k % len(hues)]
        draw.rectangle(el.bbox, outline=(*color, 255), width=max(2, h // 400))
        label = f"{name} ({el.kind})"
        draw.text((el.bbox[0] + 6, el.bbox[1] + 4), label, font=font, fill=(0, 0, 0, 255),
                  stroke_width=max(2, h // 600), stroke_fill=(255, 255, 255, 255))
    scale = width / w
    return base.resize((width, int(h * scale)), Image.LANCZOS)
