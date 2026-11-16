"""The build is driven by brand.toml, not by any one logo's art: a second, synthetic brand.

One variant named `default`, two elements (a ring and a bar), no mark element. Proves that
variant names, source names, element names, the share-card variant and the mark all come from
the config, and that without a mark element the icons fall back to the stacked lockup.

The same shapes are drawn on a 600 px and a 1200 px canvas (`SIDES`). There is no `[compose]`
table: the trace scale follows the canvas, and both pass the shipped `[verify]` bar by
themselves.
"""

import numpy as np
import pytest
from PIL import Image

from generic_brand import TILE
from logo_pipeline import deps, render

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif("chrome" in deps.check_tools() or "potrace" in deps.check_tools(),
                                 reason="Chrome and potrace are needed to build")]


@pytest.fixture
def built(generic_brand):
    return generic_brand


def test_lockup_is_built_and_verified(built):
    brand, res = built
    assert (brand / "svg/logo-stacked-default.svg").is_file()
    assert set(res.verify) == {"logo-stacked-default.svg"}
    # the shipped [verify] bar, with no [compose] override: the trace scale follows the canvas
    result = res.verify["logo-stacked-default.svg"]
    print(f"iou={result.iou:.4f} color_error={result.color_error:.2f}")
    assert result.iou >= 0.98 and result.passed
    assert set(res.elements) == {"default"} and set(res.elements["default"]) == {"ring", "bar"}


def test_no_marks_without_a_mark_element(built):
    brand, res = built
    assert not [p for p in brand.rglob("mark-*")]
    assert any("lockup" in n and "mark" in n for n in res.notes), res.notes


def test_icons_and_favicons_exist_at_their_sizes(built):
    brand, _ = built
    sizes = {"png/icon-default-192.png": 192, "png/icon-default-512.png": 512,
             "png/icon-default-maskable-512.png": 512, "png/apple-touch-icon-default-180.png": 180,
             "png/favicon-default-16.png": 16, "png/favicon-default-32.png": 32,
             "png/favicon-default-48.png": 48}
    for f, s in sizes.items():
        assert Image.open(brand / f).size == (s, s), f
    ico = Image.open(brand / "png/favicon-default.ico")
    assert sorted(ico.ico.sizes()) == [(16, 16), (32, 32), (48, 48)]


def test_icons_are_built_from_the_lockup(built):
    brand, _ = built
    icon = (brand / "svg/icon-default.svg").read_text()
    assert 'data-element="ring"' in icon and 'data-element="bar"' in icon
    assert f'fill="{TILE}"' in icon
    # the 16 px favicon is the icon scaled down, not a simplified drawing
    for s in (16, 32, 48):
        want = render.svg_to_png(icon, s, s)
        got = np.asarray(Image.open(brand / f"png/favicon-default-{s}.png").convert("RGBA"))
        assert (got == want).all(), s


def test_maskable_lockup_stays_inside_the_safe_circle(built):
    brand, _ = built
    im = Image.open(brand / "png/icon-default-maskable-512.png").convert("RGBA")
    a = np.asarray(im).astype(int)
    tile = np.array([int(TILE[i:i + 2], 16) for i in (1, 3, 5)])
    art = np.abs(a[..., :3] - tile).sum(axis=-1) > 30
    ys, xs = np.nonzero(art)
    assert len(xs) > 1000
    assert np.hypot(xs + 0.5 - 256, ys + 0.5 - 256).max() / 512 <= 0.40


def test_share_card_is_1200x630(built):
    brand, _ = built
    im = Image.open(brand / "png/share-card-1200x630.png")
    assert im.size == (1200, 630) and im.mode == "RGB"


def test_logo_package_is_built_from_the_variants(built):
    brand, _ = built
    found = {p.relative_to(brand).as_posix()
             for p in (brand / "logo-package").rglob("*") if p.is_file()}
    assert found == {
        "logo-package/svg/logo-stacked-default.svg",
        "logo-package/pdf/logo-stacked-default.pdf",
        "logo-package/png/logo-stacked-default-1200.png",
        "logo-package/png/email-header-default-1200.png",
        "logo-package/png/icon-default-512.png",
        "logo-package/png/icon-default-192.png",
        "logo-package/README.txt",  # build.run writes the documents too
    }
