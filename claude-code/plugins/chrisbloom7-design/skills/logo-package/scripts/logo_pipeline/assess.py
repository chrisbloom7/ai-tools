"""Preflight assessment: grade the source art and say what would improve the result."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from scipy import ndimage

LIMITED_BELOW = 2000  # shortest side under this grades Limited
GOOD_AT = 2400  # shortest side at or above this can grade Good
BEST_AT = 3000  # with per-element files, at or above this grades Best
SPECK_MAX_AREA = 64  # opaque blobs this small (px) count as stray specks
GRADIENT_MAX_STEP = 8  # neighbor color step (per channel) that still counts as smooth
GRADIENT_MIN_COLORS = 16  # distinct smooth-region colors that mean a gradient
OPAQUE = 128

_IMAGE_MARKER = re.compile(rb"/Subtype\s*/Image")

# What each tier means for the package, shared by the CLI and the conversion report. The build
# always traces one flat export (or flattened composite) per variant: layered or vector
# originals grade Best but are not consumed by it.
TIER_EXPECT = {
    "best": ("Best means the originals are layered or vector: keep them and hand them on (a vector "
             "original needs no tracing and can be used directly). The build still traces one "
             "flat export (or flattened composite) per variant and does not output per-element "
             "files."),
    "good": ("Good means a full package, but the layer split is inferred from flat art, so expect "
             "some roughness at halos and overlaps."),
    "limited": ("Limited means web-size SVGs and favicons are fine, but print-grade output is not "
                "reliable; re-exported art is advised."),
}
LAYERS_UPGRADE = ("send per-element layers as well (keep them as masters; this build still "
                  "traces one flat export per variant)")


@dataclass
class FileInfo:
    path: Path
    width: int
    height: int
    has_alpha: bool
    gradient: bool
    specks: int
    lossy_suspect: bool


@dataclass
class Assessment:
    tier: Literal["best", "good", "limited"]
    findings: list[str] = field(default_factory=list)
    upgrades: list[str] = field(default_factory=list)
    same_canvas: bool = True
    files: list[FileInfo] = field(default_factory=list)


def speck_labels(rgba: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """(labels, ids) of the small opaque blobs the preflight counts as possible stray specks:
    4-connected blobs of alpha >= OPAQUE with at most SPECK_MAX_AREA px. A blob that touches a
    bigger one only at a corner is counted too, so some of these are part of the art."""
    solid = rgba[..., 3] >= OPAQUE
    labels, count = ndimage.label(solid)
    areas = ndimage.sum(solid, labels, range(1, count + 1)) if count else []
    return labels, [i + 1 for i, a in enumerate(areas) if a <= SPECK_MAX_AREA]


def _inspect(path: Path) -> FileInfo:
    with Image.open(path) as img:
        lossy = (img.format or "").upper() in {"JPEG", "MPO"}
        rgba = np.asarray(img.convert("RGBA"))
        width, height = img.size
    alpha = rgba[..., 3]
    has_alpha = bool((alpha < 255).any())

    specks = len(speck_labels(rgba)[1])

    # Gradient: interior pixels whose neighbors differ by a small, nonzero step.
    interior = ndimage.binary_erosion(alpha == 255, iterations=2)
    rgb = rgba[..., :3].astype(np.int16)
    step = np.zeros(alpha.shape, dtype=np.int16)
    for axis in (0, 1):
        d = np.abs(np.diff(rgb, axis=axis)).max(axis=2)
        pad = [(0, 1), (0, 0)] if axis == 0 else [(0, 0), (0, 1)]
        step = np.maximum(step, np.pad(d, pad))
        pad = [(1, 0), (0, 0)] if axis == 0 else [(0, 0), (1, 0)]
        step = np.maximum(step, np.pad(d, pad))
    # Flat pixels (step 0) are not "smooth": hard-edged flat art with many colors is not a
    # gradient. Pack RGB into one integer so np.unique runs on a 1-D array (fast).
    smooth = interior & (step > 0) & (step <= GRADIENT_MAX_STEP)
    px = rgba[..., :3][smooth].astype(np.uint32)
    packed = (px[:, 0] << 16) | (px[:, 1] << 8) | px[:, 2]
    gradient = len(np.unique(packed)) >= GRADIENT_MIN_COLORS

    return FileInfo(Path(path), width, height, has_alpha, gradient, specks, lossy)


def _is_vector(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix == ".svg" or (suffix == ".pdf" and pdf_kind(path) == "vector")


def assess(paths: list[Path], layered: bool = False) -> Assessment:
    """Grade the inputs. `layered` means the caller says they are per-element layers.

    Vector files (SVG, vector PDF) are the best input and are not graded as rasters. A PDF
    that wraps a raster image is flagged and skipped (it is never opened as an image).
    Raises ValueError for an empty list.
    """
    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("no input files to assess; pass at least one PNG, SVG or PDF")
    vectors = [p for p in paths if _is_vector(p)]
    wrapped = [p for p in paths if p.suffix.lower() == ".pdf" and p not in vectors]
    findings: list[str] = [
        f"{p.name}: PDF wraps a raster image: export the artwork as PNG or SVG instead."
        for p in wrapped]
    upgrades: list[str] = ["export the artwork as PNG or SVG, not a PDF around a bitmap"] \
        if wrapped else []
    rasters = [p for p in paths if p not in vectors and p not in wrapped]
    if vectors and not rasters:
        note = "The other inputs are vector files." if wrapped else "All inputs are vector files."
        return Assessment("best", findings + [note], upgrades, True, [])
    if not rasters:
        return Assessment("limited", findings, upgrades, True, [])
    files = [_inspect(p) for p in rasters]
    limited = False
    if vectors:
        names = ", ".join(p.name for p in vectors)
        findings.append(f"The vector files were not graded as rasters ({names}); they are the best "
                        "input and should be used directly.")

    sizes = {(f.width, f.height) for f in files}
    same_canvas = len(sizes) <= 1
    if not same_canvas:
        listed = ", ".join(f"{w}x{h}" for w, h in sorted(sizes))
        findings.append(f"Files have different canvas sizes ({listed}); layers will not line up.")
        upgrades.append("send every layer on the same canvas size so they stack exactly")

    shortest = min(min(f.width, f.height) for f in files)
    if shortest < LIMITED_BELOW:
        limited = True
        findings.append(f"Shortest side is {shortest} px, under {LIMITED_BELOW}.")
        upgrades.append(f"send art at {GOOD_AT} px or larger for crisp large sizes")
    elif shortest < GOOD_AT:
        findings.append(f"Shortest side is {shortest} px, under {GOOD_AT}.")
        upgrades.append(f"send art at {GOOD_AT} px or larger for crisp large sizes")

    for f in files:
        if not f.has_alpha:
            limited = True
            findings.append(f"{f.path.name} has no transparent pixels: the art is on an opaque "
                            "background, or the alpha channel is fully opaque.")
            upgrades.append("send PNGs with a transparent background so edges separate cleanly")
        if f.lossy_suspect:
            findings.append(f"{f.path.name} looks lossy (JPEG); edges may be noisy.")
            upgrades.append("send a lossless PNG or vector file instead of a JPEG")
        if f.specks:
            findings.append(f"{f.path.name}: counted {f.specks} small opaque blob(s) of "
                            f"{SPECK_MAX_AREA} px or less (possible stray specks).")

    if not layered:
        upgrades.append(LAYERS_UPGRADE)

    if limited:
        tier = "limited"
    elif layered and shortest >= BEST_AT and same_canvas:
        tier = "best"
    else:
        tier = "good"
        if shortest < BEST_AT:
            upgrades.append(f"send art at {BEST_AT} px or larger for the best result")

    return Assessment(tier, findings, list(dict.fromkeys(upgrades)), same_canvas, files)


def pdf_kind(path: Path) -> Literal["vector", "raster"]:
    """Byte-scan a PDF for an image XObject: present means raster, else vector.

    This is a plain byte scan of the file. It cannot see images inside compressed object
    streams (PDF 1.5+), so a raster wrapper that hides its image dictionary there reads as
    "vector".
    """
    return "raster" if _IMAGE_MARKER.search(Path(path).read_bytes()) else "vector"
