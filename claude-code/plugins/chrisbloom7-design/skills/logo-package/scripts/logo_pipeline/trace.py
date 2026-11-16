"""Trace a binary mask to a vector layer with potrace.

Ported from an earlier logo pipeline's trace.py (smooth_up, potrace). The result is an SVG
<g> in the source's pixel space: potrace's own transform is kept, nested in a scale(1/up)
group. potrace must be on PATH.
"""
import pathlib
import re
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage as ndi


def smooth_up(mask: np.ndarray, up: float = 0.5, sigma: float | None = None) -> np.ndarray:
    """Binary mask -> resampled by `up`, lightly blurred, re-thresholded (sub-pixel smooth edges)."""
    if sigma is None:
        sigma = 3.0 * up / 2
    im = Image.fromarray((mask * 255).astype(np.uint8)).resize(
        (int(mask.shape[1] * up), int(mask.shape[0] * up)), Image.LANCZOS)
    a = ndi.gaussian_filter(np.asarray(im, dtype=np.float32), float(sigma))
    return a > 127


def potrace(mask_up: np.ndarray, up: float, *, alpha: float = 1.1, opt: float = 1.0,
            unit: int = 2) -> str:
    if shutil.which("potrace") is None:
        raise RuntimeError("potrace is not installed or not on PATH; install it with "
                           "`brew install potrace`")
    with tempfile.TemporaryDirectory() as d:
        pbm = pathlib.Path(d) / "m.pbm"
        svg = pathlib.Path(d) / "m.svg"
        Image.fromarray(~mask_up).convert("1").save(pbm)  # potrace traces black pixels
        subprocess.run(["potrace", "-s", "-t", "60", "-a", str(alpha), "-O", str(opt),
                        "-u", str(unit), "-o", str(svg), str(pbm)], check=True)
        s = svg.read_text()
    m = re.search(r'<g transform="([^"]+)"[^>]*>(.*?)</g>', s, re.S)
    inner = re.sub(r'\s+', ' ', m.group(2)).strip() if m else ""
    if not inner:
        raise ValueError("mask is too small to trace: nothing is left after smoothing")
    # nest potrace's transform in a scale(1/up) group: result lives in source-pixel coordinates
    return f'<g transform="scale({1 / up})"><g transform="{m.group(1)}">{inner}</g></g>'


def mask_to_svg(mask: np.ndarray, *, up: float = 0.5, sigma: float | None = None,
                alpha: float = 1.1, opt: float = 1.0, unit: int = 2) -> str:
    """Trace a boolean mask to an SVG <g> in the mask's own pixel coordinates.

    Raises ValueError for an empty mask (or one that vanishes when smoothed) and RuntimeError
    when potrace is not installed.
    """
    if not np.any(mask):
        raise ValueError("cannot trace an empty mask (no True pixels)")
    return potrace(smooth_up(mask, up, sigma), up, alpha=alpha, opt=opt, unit=unit)
