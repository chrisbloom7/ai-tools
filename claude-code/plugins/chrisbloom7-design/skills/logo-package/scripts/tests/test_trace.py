import re

import shutil

import numpy as np
import pytest

from logo_pipeline import minify, trace


def disk(size: int, r: int, hole: int = 0) -> np.ndarray:
    y, x = np.ogrid[:size, :size]
    d2 = (x - size / 2) ** 2 + (y - size / 2) ** 2
    mask = d2 <= r * r
    if hole:
        mask &= d2 > hole * hole
    return mask


def wrap(mask: np.ndarray) -> str:
    h, w = mask.shape
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            f'{trace.mask_to_svg(mask)}</svg>')


needs_potrace = pytest.mark.skipif(shutil.which("potrace") is None,
                                   reason="potrace is not installed (brew install potrace)")


def abs_points(d: str) -> list[tuple[float, float]]:
    """Every absolute (x, y) point (endpoints and control points) in a path `d` of M/L/C/H/V/Z
    commands, upper or lower case. Fails loudly on any other command."""
    pts, cur, start = [], (0.0, 0.0), (0.0, 0.0)
    for cmd, args in re.findall(r"([A-Za-z])([^A-Za-z]*)", d):
        nums = [float(n) for n in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", args)]
        rel = cmd.islower()
        c = cmd.upper()
        if c == "Z":
            cur = start
            continue
        if c == "H":
            for x in [(n + cur[0] if rel else n) for n in nums]:
                cur = (x, cur[1])
                pts.append(cur)
            continue
        if c == "V":
            for y in [(n + cur[1] if rel else n) for n in nums]:
                cur = (cur[0], y)
                pts.append(cur)
            continue
        assert c in "MLC", f"unhandled path command {cmd!r}"
        width = 6 if c == "C" else 2
        assert len(nums) % width == 0 and nums, d
        for i in range(0, len(nums), width):
            group = nums[i:i + width]
            seg = []
            for j in range(0, width, 2):
                x, y = group[j], group[j + 1]
                seg.append((cur[0] + x, cur[1] + y) if rel else (x, y))
            pts.extend(seg)
            cur = seg[-1]
            if c == "M":
                start = cur
    return pts


@needs_potrace
def test_circle_mask_traces_to_one_path():
    g = trace.mask_to_svg(disk(200, 80))
    assert len(re.findall(r"<path\b", g)) == 1
    d = re.search(r'<path[^>]* d="([^"]+)"', g).group(1)
    assert len(re.findall(r"M", d)) == 1
    assert len(re.findall(r"z", d)) == 1


def test_empty_mask_raises_value_error():
    with pytest.raises(ValueError, match="empty"):
        trace.mask_to_svg(np.zeros((50, 50), bool))


def test_mask_too_small_to_survive_smoothing_raises_value_error():
    mask = np.zeros((200, 200), bool)
    mask[100, 100] = True
    with pytest.raises(ValueError, match="too small"):
        trace.mask_to_svg(mask)


def test_missing_potrace_says_how_to_install(monkeypatch):
    monkeypatch.setattr(trace.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="brew install potrace"):
        trace.mask_to_svg(disk(200, 80))


def test_potrace_has_no_default_for_up():
    import inspect
    assert inspect.signature(trace.potrace).parameters["up"].default is inspect.Parameter.empty


@needs_potrace
def test_hole_is_preserved():
    g = trace.mask_to_svg(disk(200, 80, hole=40))
    d = re.search(r'<path[^>]* d="([^"]+)"', g).group(1)
    assert len(re.findall(r"[Mm]", d)) == 2


@needs_potrace
def test_minify_flattens_transforms():
    out = minify.minify(wrap(disk(200, 80, hole=40)))
    assert "transform=" not in out
    d = re.search(r'<path[^>]* d="([^"]+)"', out).group(1)
    assert d.strip()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', out).group(1).split()]
    pts = abs_points(d)
    assert pts
    # the disk (center 100, radius 80 of 200) scaled to the output viewBox stays inside it
    # and still spans most of it
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    tol = 0.01 * vb[2]
    assert vb[0] - tol <= min(xs) and max(xs) <= vb[0] + vb[2] + tol
    assert vb[1] - tol <= min(ys) and max(ys) <= vb[1] + vb[3] + tol
    assert (max(xs) - min(xs)) > 0.7 * vb[2]


@needs_potrace


def test_minify_is_smaller():
    svg = wrap(disk(200, 80, hole=40))
    assert len(minify.minify(svg)) < len(svg)


def test_minify_scales_stroke_width():
    # a halo is a stroke; its width is in user units, so it scales with the drawing
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
           '<g stroke="#fff" stroke-width="4"><path d="M10 10L50 10L50 50Z"/></g></svg>')
    out = minify.minify(svg, width=100)
    assert re.search(r'stroke-width="([0-9.]+)"', out).group(1) == "2"
    nested = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">'
              '<svg x="0" y="0" width="500" height="500" viewBox="0 0 200 200">'
              '<g stroke-width="3"><path d="M10 10L50 10L50 50Z"/></g></svg></svg>')
    out = minify.minify(nested, width=1000)
    assert float(re.search(r'stroke-width="([0-9.]+)"', out).group(1)) == 7.5
