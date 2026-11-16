import re

import pytest

from logo_pipeline import minify

NSATTR = 'xmlns="http://www.w3.org/2000/svg"'


BODY = '<g transform="translate(5,5)"><path d="M10 10L50 10L50 50Z" fill="url(#g)"/></g>'


def wrap(defs: str, body: str = BODY) -> str:
    return f'<svg {NSATTR} viewBox="0 0 200 100"><defs>{defs}</defs>{body}</svg>'


BBOX_GRADIENT = ('<linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
                 '<stop offset="0" stop-color="#f00"/><stop offset="1" stop-color="#00f"/>'
                 '</linearGradient>')


def test_bounding_box_gradient_round_trips():
    out = minify.minify(wrap(BBOX_GRADIENT), width=100)
    assert 'id="g"' in out and 'stop-color="#f00"' in out and 'stop-color="#00f"' in out
    assert 'fill="url(#g)"' in out
    assert "transform=" not in out


def test_helpers_are_public():
    assert minify.parse_transform("translate(2,3) scale(2)") == (2.0, 2.0, 2.0, 3.0)
    assert minify.compose_transforms((2, 2, 1, 1), (3, 3, 4, 4)) == (6, 6, 9, 9)
    segs = minify.subpaths("M0 0L10 0L10 10Z")
    assert [s[0] for s in segs] == ["M", "L", "L", "Z"]
    assert minify.encode_path(segs, (1.0, 1.0, 0.0, 0.0), 0) == "M0 0l10 0 0 10z"
    for old in ("_matrix", "_compose", "_subpaths", "_encode"):
        assert not hasattr(minify, old)


@pytest.mark.parametrize("defs, what", [
    (BBOX_GRADIENT.replace('<linearGradient ', '<linearGradient gradientUnits="userSpaceOnUse" '),
     "gradientUnits"),
    ('<clipPath id="c"><rect width="5" height="5"/></clipPath>', "clipPath"),
    ('<mask id="m"><rect width="5" height="5"/></mask>', "mask"),
    ('<pattern id="p" width="4" height="4"><rect width="2" height="2"/></pattern>', "pattern"),
])
def test_unsupported_defs_raise(defs, what):
    with pytest.raises(ValueError, match=r"not supported by minify: .*" + what):
        minify.minify(wrap(defs), width=100)


def test_unsupported_defs_nested_inside_a_group_still_raise():
    defs = '<g><clipPath id="c"><rect width="5" height="5"/></clipPath></g>'
    with pytest.raises(ValueError, match="not supported by minify"):
        minify.minify(wrap(defs), width=100)
