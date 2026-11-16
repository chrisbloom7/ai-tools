import numpy as np

from logo_pipeline import gradients


def rgb(hex_color: str) -> np.ndarray:
    return np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)])


def ramp_canvas(top, bottom):
    c = np.zeros((300, 200, 4), np.uint8)
    t = np.linspace(0, 1, 200)[:, None, None]
    c[50:250, 40:160, :3] = np.round((1 - t) * np.array(top) + t * np.array(bottom))
    c[50:250, 40:160, 3] = 255
    mask = np.zeros((300, 200), bool)
    mask[50:250, 40:160] = True
    return c, mask


def test_sample_returns_ordered_stops():
    top, bottom = (240, 205, 70), (245, 125, 15)
    c, mask = ramp_canvas(top, bottom)
    stops = gradients.sample(c, mask)
    assert len(stops) == 5
    offsets = [o for o, _ in stops]
    assert offsets == sorted(offsets) and offsets[0] == 0.0 and offsets[-1] == 1.0
    assert all(h.startswith("#") and len(h) == 7 for _, h in stops)
    assert np.abs(rgb(stops[0][1]) - top).max() <= 12
    assert np.abs(rgb(stops[-1][1]) - bottom).max() <= 12
    # the middle stop sits between the ends
    mid = rgb(stops[2][1])
    assert np.abs(mid - (np.array(top) + bottom) / 2).max() <= 6


def test_sample_stop_count():
    c, mask = ramp_canvas((0, 0, 255), (255, 0, 0))
    stops = gradients.sample(c, mask, stops=3)
    assert [o for o, _ in stops] == [0.0, 0.5, 1.0]


def test_sample_ignores_opaque_pixels_outside_mask_in_the_same_rows():
    c, mask = ramp_canvas((0, 0, 255), (255, 0, 0))
    # opaque green beside the mask, spanning exactly the mask's rows: a missing `mask &`
    # in sample() would average it into every stop
    c[50:250, 0:40] = (0, 255, 0, 255)
    c[50:250, 160:200] = (0, 255, 0, 255)
    stops = gradients.sample(c, mask)
    assert all(rgb(h)[1] == 0 for _, h in stops)
    assert np.abs(rgb(stops[0][1]) - (0, 0, 255)).max() <= 20
    assert np.abs(rgb(stops[-1][1]) - (255, 0, 0)).max() <= 20
