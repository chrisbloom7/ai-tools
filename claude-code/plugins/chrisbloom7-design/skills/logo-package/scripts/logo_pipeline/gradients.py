"""Sample a linear gradient from the art inside a mask."""

from typing import Literal

import numpy as np

OPAQUE = 128  # pixels below this alpha (anti-aliased edges, halo) do not set stop colors


def _hex(rgb: np.ndarray) -> str:
    r, g, b = (int(v) for v in np.clip(np.round(rgb), 0, 255))
    return f"#{r:02x}{g:02x}{b:02x}"


def sample(rgba: np.ndarray, mask: np.ndarray, axis: Literal["y"] = "y",
           stops: int = 5) -> list[tuple[float, str]]:
    """Return `stops` evenly spaced (offset, hex) pairs, top (0.0) to bottom (1.0).

    Offsets are relative to the mask's own row extent, which is what an SVG
    `linearGradient` with `gradientUnits="objectBoundingBox"` maps them to, so pass the same
    mask (layer) that will be traced and filled. Each stop is the mean color of the mask's
    opaque pixels in a band of rows centered on that offset; colors are measured, never
    adjusted.
    """
    if axis != "y":
        raise ValueError(f"only axis='y' is supported, got {axis!r}")
    if stops < 2:
        raise ValueError("a gradient needs at least 2 stops")
    solid = mask & (rgba[..., 3] >= OPAQUE)
    if not solid.any():
        raise ValueError("mask has no opaque pixels to sample")
    rows = np.nonzero(mask.any(axis=1))[0]
    top, bottom = int(rows[0]), int(rows[-1])
    height = bottom - top + 1
    half = max(1.0, height / (2 * (stops - 1)))
    rgb = rgba[..., :3].astype(np.float64)
    count = solid.sum(axis=1)
    total = (rgb * solid[..., None]).sum(axis=1)  # per-row channel sums

    out = []
    for i in range(stops):
        offset = i / (stops - 1)
        center = top + offset * (height - 1)
        reach = half
        while True:
            lo = max(top, int(np.floor(center - reach)))
            hi = min(bottom, int(np.ceil(center + reach)))
            n = count[lo:hi + 1].sum()
            if n:
                break
            reach *= 2  # band falls in a gap of the mask: widen until it finds pixels
        out.append((round(offset, 4), _hex(total[lo:hi + 1].sum(axis=0) / n)))
    return out
