"""Rasterize and print SVGs with headless Chrome."""

import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor

from .deps import CHROME, ENV_CHROME, INSTALL_HINTS

CHROME_MIN = 640  # Chrome's headless window floor (px)
TIMEOUT = 120


def viewbox(svg: str) -> tuple[float, float, float, float]:
    """The (x, y, width, height) of the svg's viewBox; ValueError when it has none."""
    num = r"([-+\d.eE]+)"
    m = re.search(rf'viewBox="\s*{num}[\s,]+{num}[\s,]+{num}[\s,]+{num}\s*"', svg)
    if not m:
        raise ValueError("svg has no viewBox; cannot size the page")
    return tuple(float(v) for v in m.groups())


def viewbox_pixel_size(svg: str) -> tuple[int, int]:
    """The viewBox's size rounded to whole pixels: the size a render of it is made at."""
    _, _, w, h = viewbox(svg)
    return round(w), round(h)


def _viewbox_size(svg: str) -> tuple[float, float]:
    _, _, w, h = viewbox(svg)
    return w, h


def _run(args: list[str], out: Path) -> None:
    """Run headless Chrome and require that it wrote `out`.

    Each call gets its own throwaway --user-data-dir: without one, Chrome can hand the request
    to a running Chrome using the default profile and exit 0 having written nothing.
    """
    if CHROME is None:
        raise RuntimeError(f"Chrome not found: {INSTALL_HINTS['chrome']}; env var {ENV_CHROME}")
    with tempfile.TemporaryDirectory() as profile:
        p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--user-data-dir={profile}", *args],
                           capture_output=True, text=True, timeout=TIMEOUT)
    if p.returncode != 0:
        raise RuntimeError(f"Chrome exited {p.returncode}: {p.stderr.strip()[-2000:]}")
    if not Path(out).is_file():
        raise RuntimeError(f"Chrome exited 0 but wrote no {Path(out).name}. "
                           f"stderr: {p.stderr.strip()[-2000:]}")


def svg_to_png(svg: str, w: int, h: int, bg: str | None = None) -> np.ndarray:
    """Render `svg` to an (h, w, 4) RGBA uint8 array; transparent unless `bg` is a CSS color.

    Chrome will not open a window under 640 px, so small targets are rendered at an integer
    multiple and downsampled.
    """
    f = max(1, -(-CHROME_MIN // min(w, h)))
    W, H = w * f, h * f
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "a.svg").write_text(svg)
        (d / "a.html").write_text(
            '<!DOCTYPE html><html><body style="margin:0;background:transparent">'
            f'<img src="a.svg" width="{W}" height="{H}" style="display:block"></body></html>')
        _run(["--default-background-color=00000000", f"--window-size={W},{H}",
              f"--screenshot={d / 'o.png'}", f"file://{d / 'a.html'}"], d / "o.png")
        im = Image.open(d / "o.png").convert("RGBA")
        im.load()
    if im.size != (W, H):
        raise RuntimeError(f"Chrome rendered {im.size}, expected {(W, H)}")
    if f > 1:
        im = im.resize((w, h), Image.LANCZOS)
    if bg:
        flat = Image.new("RGBA", (w, h), _css_rgba(bg))
        flat.alpha_composite(im)
        im = flat
    return np.asarray(im).copy()


def _css_rgba(color: str):
    return ImageColor.getcolor(color, "RGBA")


def svg_to_pdf(svg: str, out: Path) -> None:
    """Print `svg` to a one-page vector PDF with a transparent background.

    The page is the SVG's viewBox size in CSS px (1 user unit = 1 px), with no margins,
    headers or footers.
    """
    vw, vh = _viewbox_size(svg)
    out = Path(out)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "a.svg").write_text(svg)
        (d / "a.html").write_text(
            f'<!DOCTYPE html><html><head><style>@page{{size:{vw}px {vh}px;margin:0}}'
            'html,body{margin:0;padding:0;background:transparent;overflow:hidden}'
            f'img{{display:block;width:{vw}px;height:{vh}px}}</style></head>'
            '<body><img src="a.svg"></body></html>')
        _run(["--default-background-color=00000000", "--no-pdf-header-footer",
              f"--print-to-pdf={d / 'o.pdf'}", f"file://{d / 'a.html'}"], d / "o.pdf")
        out.write_bytes((d / "o.pdf").read_bytes())
