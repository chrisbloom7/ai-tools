import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from logo_pipeline import assess, deps


def make_png(path: Path, size: int, *, alpha=True, gradient=False, dots=0) -> Path:
    mode = "RGBA" if alpha else "RGB"
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    lo, hi = size // 4, size * 3 // 4
    if gradient:
        ramp = np.linspace(0, 1, hi - lo)[:, None]
        r = np.full((hi - lo, hi - lo), 255.0)
        g = 220 - 100 * ramp + 0 * r
        arr[lo:hi, lo:hi, 0] = 255
        arr[lo:hi, lo:hi, 1] = g.astype(np.uint8)
        arr[lo:hi, lo:hi, 2] = 20
    else:
        arr[lo:hi, lo:hi] = (255, 200, 0, 255)
    arr[lo:hi, lo:hi, 3] = 255
    for i in range(dots):
        y, x = 20 + i * 40, 20
        arr[y:y + 3, x:x + 3] = (0, 0, 0, 255)
    img = Image.fromarray(arr, "RGBA")
    if not alpha:
        img = img.convert("RGB")
    img.save(path)
    return path


def test_2400_alpha_flat_is_good(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 2400)])
    assert a.tier == "good"
    assert a.files[0].has_alpha


def test_3000_layered_is_best(tmp_path):
    paths = [make_png(tmp_path / f"{n}.png", 3000) for n in "abc"]
    a = assess.assess(paths, layered=True)
    assert a.tier == "best"
    assert a.same_canvas


def test_two_3000px_variants_without_layered_flag_are_good_not_best(tmp_path):
    paths = [make_png(tmp_path / f"{n}.png", 3000) for n in "ab"]
    a = assess.assess(paths)
    assert a.tier == "good"
    assert any("per-element layers" in u for u in a.upgrades)


def test_all_vector_inputs_are_best(tmp_path):
    svg = tmp_path / "a.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    assert assess.assess([svg]).tier == "best"


def test_3000_single_file_is_good_with_upgrade(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 3000)])
    assert a.tier == "good"
    assert any("per-element layers" in u for u in a.upgrades)


def test_small_is_limited(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 1500)])
    assert a.tier == "limited"
    assert a.upgrades


def test_no_alpha_is_limited_and_does_not_raise(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 2400, alpha=False)])
    assert a.tier == "limited"
    assert not a.files[0].has_alpha
    assert any("transparen" in f.lower() or "alpha" in f.lower() for f in a.findings)


def test_mismatched_canvases_flagged(tmp_path):
    a = assess.assess([
        make_png(tmp_path / "a.png", 2400),
        make_png(tmp_path / "b.png", 2500),
    ])
    assert not a.same_canvas
    assert any("2400" in f and "2500" in f for f in a.findings)


def test_gradient_detected(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 2400, gradient=True)])
    assert a.files[0].gradient


def test_flat_has_no_gradient(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 2400)])
    assert not a.files[0].gradient


def test_specks_counted(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 2400, dots=3)])
    assert a.files[0].specks == 3


def _chrome_pdf(tmp_path: Path, html: str) -> Path:
    page = tmp_path / "p.html"
    page.write_text(html)
    pdf = tmp_path / "p.pdf"
    subprocess.run(
        [deps.CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", page.as_uri()],
        check=True, capture_output=True, timeout=60,
    )
    return pdf


def test_pdf_kind_raster(tmp_path):
    png = make_png(tmp_path / "i.png", 200)
    pdf = _chrome_pdf(tmp_path, f'<html><body><img src="{png.name}"></body></html>')
    assert assess.pdf_kind(pdf) == "raster"


def test_pdf_kind_vector(tmp_path):
    svg = '<svg width="200" height="200"><circle cx="100" cy="100" r="80" fill="orange"/></svg>'
    pdf = _chrome_pdf(tmp_path, f"<html><body>{svg}</body></html>")
    assert assess.pdf_kind(pdf) == "vector"


# ---- hardening ------------------------------------------------------------------------------

RASTER_PDF = (b"%PDF-1.4\n1 0 obj\n<< /Type /XObject /Subtype /Image /Width 1 /Height 1 >>\n"
              b"endobj\n%%EOF\n")
VECTOR_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nendobj\n%%EOF\n"


def make_pdf(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_empty_input_raises_clear_error():
    with pytest.raises(ValueError, match="no input files"):
        assess.assess([])


def test_many_color_flat_art_is_not_a_gradient(tmp_path):
    # 8x8 hard-edged blocks, 64 distinct flat colors: lots of colors but no smooth change
    arr = np.zeros((2400, 2400, 4), np.uint8)
    block = 2400 // 8
    for i in range(8):
        for j in range(8):
            arr[i * block:(i + 1) * block, j * block:(j + 1) * block] = (
                i * 30, j * 30, (i * 8 + j) * 3, 255)
    path = tmp_path / "flat.png"
    Image.fromarray(arr, "RGBA").save(path)
    assert not assess.assess([path]).files[0].gradient


def test_band_2000_to_2399_is_good_with_finding_and_upgrade(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 2200)])
    assert a.tier == "good"
    assert any("2200 px, under 2400" in f for f in a.findings)
    assert any("2400 px or larger" in u for u in a.upgrades)


def test_speck_finding_text(tmp_path):
    a = assess.assess([make_png(tmp_path / "a.png", 2400, dots=3)])
    # says what was counted, not that anything was removed
    assert "a.png: counted 3 small opaque blob(s) of 64 px or less (possible stray specks)." \
        in a.findings


def test_speck_labels_are_the_blobs_the_preflight_counts(tmp_path):
    from PIL import Image
    path = make_png(tmp_path / "a.png", 2400, dots=3)
    rgba = np.asarray(Image.open(path).convert("RGBA"))
    labels, ids = assess.speck_labels(rgba)
    assert len(ids) == assess.assess([path]).files[0].specks == 3
    assert all((labels == i).sum() <= assess.SPECK_MAX_AREA for i in ids)


def test_jpeg_input_is_lossy_suspect(tmp_path):
    # Detection is by file format only: a PNG that was re-saved from a JPEG is NOT detected.
    path = tmp_path / "a.jpg"
    Image.fromarray(np.full((2400, 2400, 3), 200, np.uint8), "RGB").save(path, "JPEG")
    a = assess.assess([path])
    assert a.files[0].lossy_suspect
    assert any("looks lossy (JPEG)" in f for f in a.findings)
    assert any("lossless PNG" in u for u in a.upgrades)


def test_png_is_not_lossy_suspect(tmp_path):
    assert not assess.assess([make_png(tmp_path / "a.png", 2400)]).files[0].lossy_suspect


def test_fully_opaque_rgba_gets_truthful_finding_and_limited(tmp_path):
    arr = np.full((2400, 2400, 4), 255, np.uint8)
    path = tmp_path / "a.png"
    Image.fromarray(arr, "RGBA").save(path)
    a = assess.assess([path])
    assert a.tier == "limited"
    assert not a.files[0].has_alpha
    assert any("no transparent pixels: the art is on an opaque background, "
               "or the alpha channel is fully opaque" in f for f in a.findings)
    assert any("transparent background" in u for u in a.upgrades)


def test_raster_pdf_is_flagged_skipped_and_does_not_raise(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", RASTER_PDF)
    a = assess.assess([make_png(tmp_path / "a.png", 2400), pdf])
    assert any("a.pdf" in f and "PDF wraps a raster image: export the artwork as PNG or SVG "
               "instead" in f for f in a.findings)
    assert [f.path.name for f in a.files] == ["a.png"]
    assert a.tier == "good"


def test_only_raster_pdf_is_limited_without_raising(tmp_path):
    a = assess.assess([make_pdf(tmp_path / "a.pdf", RASTER_PDF)])
    assert a.tier == "limited"
    assert a.files == []
    assert any("PDF wraps a raster image" in f for f in a.findings)


def test_vector_pdf_counts_as_vector_input(tmp_path):
    assert assess.assess([make_pdf(tmp_path / "a.pdf", VECTOR_PDF)]).tier == "best"


def test_mixed_vector_and_raster_says_vectors_were_not_graded(tmp_path):
    svg = tmp_path / "a.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    a = assess.assess([svg, make_png(tmp_path / "a.png", 2400)])
    assert any("vector files were not graded as rasters" in f and "a.svg" in f
               for f in a.findings)
    assert [f.path.name for f in a.files] == ["a.png"]
