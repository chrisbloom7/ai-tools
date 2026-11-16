import numpy as np
import pytest

from logo_pipeline import variants
from logo_pipeline.segment import Element

SHAPE = (100, 100)


def el(mask):
    ys, xs = np.nonzero(mask)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return Element(mask=mask, bbox=bbox, kind="flat", layers={"fill": mask.copy()})


def block(x0, x1, shape=SHAPE):
    m = np.zeros(shape, dtype=bool)
    m[10:30, x0:x1] = True
    return m


def test_identical_pieces_shared():
    r = variants.match({"p": el(block(10, 60))}, {"p": el(block(10, 60))}, 0.95)
    assert r.shared == {"p": 1.0}
    assert r.canonical == {"p": "a"}
    assert r.variant_only == []


def test_near_match_shared_with_difference_reported():
    # 100 vs 97 columns of the same rows: IoU = 97/100
    a = el(block(0, 100))
    b = el(block(0, 97))
    r = variants.match({"p": a}, {"p": b}, 0.95)
    assert "p" in r.shared
    assert abs(r.shared["p"] - 0.97) < 1e-9
    assert r.canonical["p"] == "a"


def test_large_difference_traced_per_variant():
    r = variants.match({"p": el(block(0, 50))}, {"p": el(block(25, 75))}, 0.95)
    assert "p" not in r.shared
    assert "p" not in r.canonical
    assert r.variant_only == []


def test_mismatched_canvas_shares_nothing():
    a = {"p": el(block(10, 60))}
    b = {"p": el(block(10, 60, shape=(120, 100)))}
    r = variants.match(a, b, 0.95)
    assert r.shared == {} and r.canonical == {}
    assert r.variant_only == []


def test_names_in_one_variant_are_variant_only():
    r = variants.match({"p": el(block(10, 60)), "x": el(block(10, 60))},
                       {"p": el(block(10, 60)), "y": el(block(10, 60))}, 0.95)
    assert sorted(r.variant_only) == ["x", "y"]


def test_iou_equal_to_tol_is_shared():
    # 100 vs 95 columns of the same rows: IoU is exactly 0.95, and the comparison is >=
    r = variants.match({"p": el(block(0, 100))}, {"p": el(block(0, 95))}, 0.95)
    assert r.shared == {"p": 0.95}


def test_iou_just_below_tol_is_not_shared():
    r = variants.match({"p": el(block(0, 100))}, {"p": el(block(0, 94))}, 0.95)
    assert r.shared == {}


def test_two_empty_masks_are_not_shared():
    # Empty masks have IoU 1.0 by convention, but there is nothing to trace and reuse (and
    # trace.mask_to_svg refuses an empty mask), so a piece that is empty in both variants is
    # left out of `shared` and `canonical` rather than reported as reusable.
    empty = np.zeros(SHAPE, dtype=bool)
    a = Element(mask=empty, bbox=(0, 0, 0, 0), kind="flat", layers={})
    r = variants.match({"p": a}, {"p": a}, 0.95)
    assert r.shared == {} and r.canonical == {} and r.variant_only == []
    assert variants._iou(empty, empty) == 1.0


def test_integer_masks_are_compared_as_booleans():
    # bitwise & on raw ints (1 & 2 == 0) would report no overlap; masks are cast to bool first
    m = block(0, 100)
    assert variants._iou(m.astype(np.uint8), m.astype(np.uint8) * 2) == 1.0


def test_match_first_compares_the_first_variant_with_each_other():
    els = {"a": {"p": el(block(10, 60))}, "b": {"p": el(block(10, 60))},
           "c": {"p": el(block(40, 90)), "q": el(block(0, 5))}}
    out = variants.match_first(els, 0.0)
    assert list(out) == ["b", "c"]
    assert out["b"].shared == {"p": 1.0}
    assert out["c"].shared == {"p": pytest.approx(20 / 80)}
    assert out["c"].variant_only == ["q"]
    assert variants.match_first({"only": {"p": el(block(10, 60))}}, 0.0) == {}
