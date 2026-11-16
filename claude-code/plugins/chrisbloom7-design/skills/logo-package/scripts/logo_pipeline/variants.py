"""Match pieces across two variants (for example a light and a dark version) of the same art.

Compares each named piece's full mask by IoU on the shared canvas, so a piece that is
identical in both variants can be traced once and reused.
"""

from dataclasses import dataclass, field

import numpy as np

from .segment import Element


@dataclass
class SharedReport:
    """Result of `match`.

    shared: piece name to IoU, for pieces present in both variants with IoU >= tol.
    canonical: piece name to the variant whose trace is used; always "a" for shared pieces.
    variant_only: names present in only one variant (sorted). A piece present in both
        variants but below tol is NOT listed here: it is simply absent from `shared` and
        `canonical`, and is traced per variant.

    Pieces whose mask shapes differ between variants (different canvas) are never shared.
    A piece whose mask is empty in both variants is never shared either: `_iou` of two empty
    masks is 1.0, but there is nothing to trace and reuse (and `trace.mask_to_svg` refuses an
    empty mask), so it is simply absent from `shared` and `canonical`.
    """

    shared: dict[str, float] = field(default_factory=dict)
    canonical: dict[str, str] = field(default_factory=dict)
    variant_only: list[str] = field(default_factory=list)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    """Intersection over union of two masks (cast to bool). Two empty masks give 1.0."""
    a, b = a.astype(bool), b.astype(bool)
    union = np.count_nonzero(a | b)
    return 1.0 if union == 0 else np.count_nonzero(a & b) / union


def match(a: dict[str, Element], b: dict[str, Element], tol: float) -> SharedReport:
    report = SharedReport(variant_only=sorted(set(a) ^ set(b)))
    for name in sorted(set(a) & set(b)):
        ma, mb = a[name].mask, b[name].mask
        if ma.shape != mb.shape:
            continue
        if not (ma.any() or mb.any()):
            continue
        iou = _iou(ma, mb)
        if iou >= tol:
            report.shared[name] = iou
            report.canonical[name] = "a"
    return report


def match_first(elements: dict[str, dict[str, Element]], tol: float) -> dict[str, SharedReport]:
    """The first variant matched with each other variant, keyed by the other's name, in order.

    One variant gives {}; two give one pair (for example primary vs alt); with more, every other
    variant is compared with the first, not with each other.
    """
    names = list(elements)
    return {o: match(elements[names[0]], elements[o], tol) for o in names[1:]}
