"""Compare a rendered SVG with the source art it was traced from."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from . import render
from .config import BRAND  # brand.toml next to the package, else brand.example.toml

OPAQUE = 128


@dataclass
class Result:
    iou: float
    color_error: float  # mean abs per-channel difference (0-255) over pixels opaque in both
    passed: bool


def _bar(config: Path | None = None) -> dict:
    return tomllib.loads(Path(config or BRAND).read_text())["verify"]


def viewbox_region(svg: str) -> tuple[int, int, int, int]:
    """The (x0, y0, x1, y1) source-pixel region an SVG's viewBox covers.

    The size is the viewBox size rounded as `render.viewbox_pixel_size` does, so the region and
    the rendered image always have the same shape.
    """
    x, y, _, _ = render.viewbox(svg)
    w, h = render.viewbox_pixel_size(svg)
    x0, y0 = round(x), round(y)
    return x0, y0, x0 + w, y0 + h


def _crop(source: Path, region) -> np.ndarray:
    """Source crop; parts of the region outside the canvas count as transparent."""
    x0, y0, x1, y1 = region
    with Image.open(source) as img:
        rgba = np.asarray(img.convert("RGBA"))
    out = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    sx0, sy0 = max(x0, 0), max(y0, 0)
    sx1, sy1 = min(x1, rgba.shape[1]), min(y1, rgba.shape[0])
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = rgba[sy0:sy1, sx0:sx1]
    return out


def compare(svg: str, source: Path, region: tuple[int, int, int, int],
            config: Path | None = None) -> Result:
    """Render `svg` over `region` and compare it with the source; the bar is `[verify]` of
    `config` (default: BRAND)."""
    x0, y0, x1, y1 = region
    src = _crop(Path(source), region)
    out = render.svg_to_png(svg, x1 - x0, y1 - y0)
    a, b = src[..., 3] >= OPAQUE, out[..., 3] >= OPAQUE
    union = int((a | b).sum())
    both = a & b
    iou = float((a & b).sum() / union) if union else 1.0
    if both.any():
        diff = np.abs(src[both][:, :3].astype(int) - out[both][:, :3].astype(int))
        color_error = float(diff.mean())
    else:
        color_error = 255.0
    bar = _bar(config)
    passed = iou >= bar["iou_min"] and color_error <= bar["color_error_max"]
    return Result(iou, color_error, passed)
