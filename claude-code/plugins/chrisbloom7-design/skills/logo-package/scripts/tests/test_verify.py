import re

import numpy as np
import pytest
from PIL import Image

from logo_pipeline import assess, deps, render, verify

pytestmark = pytest.mark.skipif("chrome" in deps.check_tools(),
                                reason="Chrome is not installed (needed to render SVGs)")

RECT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">' \
       '<rect x="100" y="80" width="200" height="140" fill="#1478aa"/></svg>'


def rect_png(path, dx=0):
    a = np.zeros((300, 400, 4), np.uint8)
    a[80:220, 100 + dx:300 + dx] = (20, 120, 170, 255)
    Image.fromarray(a).save(path)
    return path


def test_identical_art_passes(tmp_path):
    r = verify.compare(RECT, rect_png(tmp_path / "s.png"), (0, 0, 400, 300))
    assert r.iou > 0.99
    assert r.color_error < 2
    assert r.passed


def test_shifted_art_fails(tmp_path):
    r = verify.compare(RECT, rect_png(tmp_path / "s.png", dx=20), (0, 0, 400, 300))
    assert r.iou < 0.98
    assert not r.passed


def test_the_bar_comes_from_the_given_config(tmp_path):
    # a shifted rect fails the shipped bar but passes a config whose bar is looser
    cfg = tmp_path / "brand.toml"
    cfg.write_text("[verify]\niou_min = 0.5\ncolor_error_max = 8.0\n")
    src = rect_png(tmp_path / "s.png", dx=20)
    assert not verify.compare(RECT, src, (0, 0, 400, 300)).passed
    assert verify.compare(RECT, src, (0, 0, 400, 300), cfg).passed


def test_pdf_has_no_embedded_image(tmp_path):
    out = tmp_path / "a.pdf"
    render.svg_to_pdf(RECT, out)
    assert assess.pdf_kind(out) == "vector"


def test_pdf_is_exactly_one_page(tmp_path):
    out = tmp_path / "a.pdf"
    render.svg_to_pdf(RECT, out)
    data = out.read_bytes()
    import re
    assert len(re.findall(rb"/Type\s*/Page(?![s\w])", data)) == 1


def test_png_is_rgba_of_requested_size_and_transparent():
    a = render.svg_to_png(RECT, 400, 300)
    assert a.shape == (300, 400, 4) and a.dtype == np.uint8
    assert a[0, 0, 3] == 0 and a[150, 200, 3] == 255
    b = render.svg_to_png(RECT, 400, 300, bg="#ffffff")
    assert tuple(b[0, 0]) == (255, 255, 255, 255)


def _fake_chrome(tmp_path, body):
    script = tmp_path / "fake-chrome"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(0o755)
    return str(script)


def test_chrome_exit_zero_without_output_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "CHROME", _fake_chrome(tmp_path, "exit 0"))
    with pytest.raises(RuntimeError, match="wrote no"):
        render.svg_to_png(RECT, 100, 100)


def test_chrome_failure_surfaces_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "CHROME", _fake_chrome(tmp_path, "echo boom-from-chrome >&2; exit 3"))
    with pytest.raises(RuntimeError, match="boom-from-chrome"):
        render.svg_to_png(RECT, 100, 100)


def test_chrome_gets_a_private_user_data_dir(tmp_path, monkeypatch):
    log = tmp_path / "args.txt"
    monkeypatch.setattr(render, "CHROME", _fake_chrome(tmp_path, f'echo "$@" > {log}; exit 0'))
    with pytest.raises(RuntimeError):
        render.svg_to_png(RECT, 100, 100)
    assert "--user-data-dir=" in log.read_text()


def test_html_wrapper_has_a_doctype(tmp_path, monkeypatch):
    # without one Chrome renders in quirks mode; the fake chrome keeps a copy of the page
    seen = tmp_path / "page.html"
    body = ('for a in "$@"; do case "$a" in file://*) cp "${a#file://}" ' + str(seen)
            + '; esac; done; exit 0')
    monkeypatch.setattr(render, "CHROME", _fake_chrome(tmp_path, body))
    with pytest.raises(RuntimeError):
        render.svg_to_png(RECT, 100, 100)
    assert seen.read_text().lstrip().lower().startswith("<!doctype html>")
    with pytest.raises(RuntimeError):
        render.svg_to_pdf(RECT, tmp_path / "x.pdf")
    assert seen.read_text().lstrip().lower().startswith("<!doctype html>")


def test_render_without_chrome_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(render, "CHROME", None)
    with pytest.raises(RuntimeError, match="LOGO_PIPELINE_CHROME"):
        render.svg_to_png(RECT, 100, 100)


def test_viewbox_region_requires_a_viewbox():
    with pytest.raises(ValueError, match="no viewBox"):
        verify.viewbox_region('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')


@pytest.mark.parametrize("vb", ("0 0 400.5 300.4", "0.5 0.5 400.5 300.4", "-0.6 10.5 400.6 300.5"))
def test_region_and_render_size_agree_for_fractional_viewboxes(vb):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"/>'
    x0, y0, x1, y1 = verify.viewbox_region(svg)
    assert (x1 - x0, y1 - y0) == render.viewbox_pixel_size(svg)


def test_fractional_viewbox_compares_at_the_rounded_size(tmp_path):
    svg = RECT.replace('viewBox="0 0 400 300"', 'viewBox="0 0 400.5 300.4"')
    region = verify.viewbox_region(svg)
    assert region == (0, 0, 400, 300)
    assert verify.compare(svg, rect_png(tmp_path / "s.png"), region).iou > 0.95


def test_color_alone_can_fail_a_same_shape_rectangle(tmp_path):
    red = RECT.replace("#1478aa", "#d0301c")
    r = verify.compare(red, rect_png(tmp_path / "s.png"), (0, 0, 400, 300))
    assert r.iou >= 0.98
    assert r.color_error > 8
    assert not r.passed


def test_no_opaque_overlap_is_the_worst_color_error_and_fails(tmp_path):
    a = np.zeros((300, 400, 4), np.uint8)
    a[10:50, 10:50] = (20, 120, 170, 255)  # far from the SVG's rect
    Image.fromarray(a).save(tmp_path / "s.png")
    r = verify.compare(RECT, tmp_path / "s.png", (0, 0, 400, 300))
    assert r.color_error == 255.0
    assert r.iou == 0.0
    assert not r.passed


def test_pdf_page_matches_the_svg_size_in_points(tmp_path):
    out = tmp_path / "a.pdf"
    render.svg_to_pdf(RECT, out)  # 400 x 300 CSS px = 300 x 225 pt
    data = out.read_bytes()
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    assert len(boxes) == 1  # one page
    x0, y0, x1, y1 = (float(v) for v in boxes[0])
    assert (x1 - x0, y1 - y0) == pytest.approx((300, 225), abs=1)
