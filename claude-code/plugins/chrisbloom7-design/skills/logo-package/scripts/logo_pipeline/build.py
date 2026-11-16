"""Build every output from the source art: svg/, png/, the logo-package/ handoff folder and
the three documents (README.md, logo-package/README.txt, report/conversion-report.md).

  from logo_pipeline import build
  result = build.run(Path("."))                     # config: tools/brand.toml (config.BRAND)
  result = build.run(brand_dir, config=Path("..."))  # another logo

The build is all or nothing: everything is built into a staging folder inside the brand folder
and swapped into place only when the build, the lockup verification and the documents all
succeed. A failed build leaves the previous outputs exactly as they were.

What is built comes from brand.toml (see `config.load_brand`): one set of outputs per
`[variants.<name>]` table, named after the variant; the mark is `[brand] mark_element`, written
as svg/mark-<mark_name>.svg; the share card shows `[brand] share_card_variant`.

Owner decisions applied here (the spec left them open):
- Icon and favicon tiles are the variant's `tile` color (usually taken from the art).
  The mark sits centered on the tile. The maskable icon is a full-bleed square with the mark
  inside the 80% safe circle.
- Without a mark element (a logo with no separable symbol), no marks are built and the stacked
  lockup takes the mark's place on every icon and favicon; `BuildResult.notes` says so.
- Email header: the stacked lockup fitted to the height and centered on an opaque white canvas
  (RGB, no alpha) of W x round(W * 0.5). Share card: the share-card variant's lockup centered
  on opaque white, 1200 x 630.
- The 16 px favicon is a simplified drawing when there is a mark, not a scaled-down icon: the
  mark's body layers only (no outline, no halo), enlarged to fill the tile (SMALL_FIT). Without
  a mark it is the icon scaled down. The 32 and 48 px favicons are the full icon scaled down.
- Every lockup must pass `verify.compare` against its source or the build raises.
- Never one-color, CMYK, EPS or AI files.
"""

import os
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import assess, compose, deps, minify, render, segment, verify
from . import config as config_mod

Result = verify.Result

STACKED_W, MARK_W, ICON_S = 1000, 800, 1024
TILE_RADIUS = 0.2  # share of the tile side; rounded tile for icon and favicon
SMALL_FIT = 0.84  # simplified 16 px favicon: share of the tile the body's bounding box fills
SMALL_PX = 16  # favicon size drawn from the simplified mark
ICON_FIT = 0.72  # share of the tile the mark fills in the "any" icon
# Maskable: farthest mark pixel, as a share of the canvas side, from the center. The ruling is
# 0.40 (an 80% safe circle); this is deliberately a little below it, as a margin for the
# traced-versus-source difference (the drawn mark is a smoothed trace, whose outline can sit
# slightly outside the source pixels the radius is measured from).
SAFE_R = 0.39
SHARE_H = 540
WHITE = "#ffffff"
OUT_DIRS = ("svg", "png", "logo-package")
# Everything a build writes into the brand folder, each replaced as a whole on success. Of
# report/ only the report itself is managed: other files there stay. Nothing else in the brand
# folder (source/, brand.toml, tools/, the user's own files) is touched.
MANAGED = (*OUT_DIRS, "README.md", "report/conversion-report.md")
STAGING = ".build-staging-"  # + pid: the new outputs, built here
PREVIOUS = ".build-previous-"  # + pid: the old outputs, moved here during the swap
DISCARD = ".build-discard-"  # + pid: the old outputs after a successful swap, being deleted
# Our own folders, by exact name (a user's ".build-previous-1.bak" never matches). Staging and
# discard folders never hold the only copy of anything, so a later build removes them.
DISPOSABLE = re.compile(r"\.build-(staging|discard)-\d+")
INTERRUPTED = re.compile(r"\.build-previous-\d+")


@dataclass
class BuildResult:
    files: list[Path] = field(default_factory=list)
    verify: dict[str, Result] = field(default_factory=dict)  # keyed by svg file name
    # icon name -> outline-on-tile contrast ratio (absent when the art has no outline layer)
    contrast: dict[str, float] = field(default_factory=dict)
    # variant -> pieces
    elements: dict[str, dict[str, segment.Element]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # plain sentences for the report
    # variant -> the detached pieces segmentation dropped, largest first
    dropped: dict[str, list[segment.Dropped]] = field(default_factory=dict)
    brand: config_mod.Brand | None = None  # what was built (config.load_brand)
    config: Path | None = None  # the brand.toml the build read
    settings: compose.Settings | None = None  # its [compose] settings
    layout: str | None = None  # config.LAYOUT_TOOLS or LAYOUT_SKILL: what the docs say


def _lum(hex_color: str) -> float:
    c = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio of two #rrggbb colors."""
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _viewbox(svg: str) -> tuple[float, float, float, float]:
    m = re.search(r'viewBox="([^"]+)"', svg)
    x, y, w, h = (float(v) for v in m.group(1).replace(",", " ").split())
    return x, y, w, h


def _nest(svg: str, x: float, y: float, w: float, h: float) -> str:
    """The svg as a nested <svg> placed at (x, y) with size w x h (viewBox kept)."""
    head = re.search(r"<svg(?=[\s>/])[^>]*>", svg)
    if not head:
        raise ValueError("cannot nest: no <svg> opening tag found")
    vb = re.search(r'viewBox="([^"]+)"', head.group(0))
    if not vb:
        raise ValueError("cannot nest: the opening <svg> tag has no viewBox")
    nested = (f'<svg x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" '
              f'viewBox="{vb.group(1)}">')
    return svg[:head.start()] + nested + svg[head.end():]


def _canvas(w: float, h: float, inner: str, bg: str | None = None, rx: float = 0) -> str:
    rect = ""
    if bg:
        r = f' rx="{rx:.0f}"' if rx else ""
        rect = f'<rect width="{w}" height="{h}"{r} fill="{bg}"/>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">{rect}{inner}</svg>'


def _fit(svg: str, w: float, h: float,
         box_h: float | None = None) -> tuple[float, float, float, float]:
    """(x, y, width, height) of `svg` scaled to fit inside w x h (or to height box_h), centered."""
    _, _, vw, vh = _viewbox(svg)
    s = (box_h / vh) if box_h else min(w / vw, h / vh)
    return (w - vw * s) / 2, (h - vh * s) / 2, vw * s, vh * s


def _tile_icon(mark_svg: str, color: str, *, rounded: bool, fit: float = ICON_FIT) -> str:
    """Mark fitted to `fit` of the tile (ICON_FIT by default), centered; rounded or full-bleed
    tile."""
    S = ICON_S
    x, y, w, h = _fit(mark_svg, S * fit, S * fit)
    inner = _nest(mark_svg, x + S * (1 - fit) / 2, y + S * (1 - fit) / 2, w, h)
    return _canvas(S, S, inner, color, S * TILE_RADIUS if rounded else 0)


def _maskable_icon(mark_svg: str, mask: np.ndarray, bbox, color: str) -> str:
    """Full-bleed tile; the mark's farthest art pixel sits at SAFE_R of the canvas from the center.

    `mask` and `bbox` are the drawn art's pixels and their (left, top, right, bottom) box in
    source pixels: the mark element's, or every element's when the lockup stands in for a mark.
    """
    S = ICON_S
    ys, xs = np.nonzero(mask)
    pts = np.stack([xs + 0.5, ys + 0.5], 1)
    left, top, right, bottom = bbox
    c = np.array([(left + right) / 2, (top + bottom) / 2])
    r = float(np.hypot(*(pts - c).T).max())
    u = SAFE_R * S / r  # icon px per source px
    vx, vy, vw, vh = _viewbox(mark_svg)
    inner = _nest(mark_svg, S / 2 - u * (c[0] - vx), S / 2 - u * (c[1] - vy), vw * u, vh * u)
    return _canvas(S, S, inner, color)


def _outline_color(svg: str) -> str | None:
    """Fill of the first flat outline layer, or None when the art has none."""
    m = re.search(r'class="n-outline"[^>]*fill="(#[0-9a-f]{6})"', svg)
    return m.group(1) if m else None


def _write_png(path: Path, a: np.ndarray, opaque: bool = False) -> Path:
    im = Image.fromarray(a)
    if opaque:
        im = im.convert("RGB")
    im.save(path, optimize=True)
    return path


def _ico(path: Path, frames: dict[int, np.ndarray]) -> Path:
    ims = {s: Image.fromarray(a) for s, a in frames.items()}
    big = ims[max(ims)]
    big.save(path, format="ICO", sizes=[(s, s) for s in ims],
             append_images=[i for s, i in ims.items() if s != max(ims)])
    return path


NO_MARK_NOTE = ("No mark element is set in brand.toml ([brand] mark_element), so no marks were "
                "built; the icons, maskable icons, apple-touch icons and favicons use the stacked "
                "lockup as the mark, and the 16 px favicon is the icon scaled down.")


def _union(elements: dict[str, segment.Element]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Every element's pixels and their joint (left, top, right, bottom) box."""
    mask = np.logical_or.reduce([e.mask for e in elements.values()])
    b = np.array([e.bbox for e in elements.values()])
    return mask, (int(b[:, 0].min()), int(b[:, 1].min()), int(b[:, 2].max()), int(b[:, 3].max()))


HELD_SHOWN = 20  # held files listed by name in a recovery message


def _held_files(held: Path) -> str:
    """The files in a held `.build-previous-<pid>` folder, by path relative to it."""
    files = sorted(p.relative_to(held).as_posix() for p in held.rglob("*")
                   if p.is_symlink() or not p.is_dir())
    shown = ", ".join(files[:HELD_SHOWN]) or "nothing"
    more = len(files) - HELD_SHOWN
    return shown + (f" and {more} more" if more > 0 else "")


def _move_back(held: Path) -> str:
    """How to put the held files back by hand. report/ is not swapped as a folder (it holds the
    user's own files), so a whole-folder move or replace would fail or lose them."""
    return ("Move each file to the same path in the brand folder, replacing what is there. "
            "`report/conversion-report.md` goes into the existing `report/` folder; never "
            "replace the whole `report/` folder (it holds your own files). Then delete "
            f"{held}.")


def _check_interrupted(brand_dir: Path) -> None:
    """Refuse to build while a `.build-previous-<pid>` folder exists. A swap that was killed
    (SIGKILL, a second Ctrl-C) or could not roll back leaves the only copy of the earlier
    outputs there, so a build must never remove it."""
    left = sorted(p for p in brand_dir.iterdir() if INTERRUPTED.fullmatch(p.name))
    if left:
        held = left[0]
        others = f" (and {', '.join(str(p) for p in left[1:])})" if left[1:] else ""
        raise RuntimeError(
            f"A previous build was interrupted and left {held}{others} holding your earlier "
            f"outputs: {_held_files(held)}. To get the earlier outputs back: "
            f"{_move_back(held)} If you no longer need them, just delete it. Then build "
            "again.")


def _check_report_folder(brand_dir: Path) -> None:
    """The build writes report/conversion-report.md, so report must be a folder (or absent)."""
    rp = brand_dir / "report"
    if _exists(rp) and not rp.is_dir():
        raise RuntimeError(
            f"{rp} is not a folder, but the build writes report/conversion-report.md into a "
            "report/ folder. Move it out of the brand folder (or rename it), then build again.")


def _remove_stale(brand_dir: Path) -> None:
    """Remove staging and discard folders left by a build that crashed or was killed. They are
    ours (DISPOSABLE: matched by exact name), never the user's, and never the only copy of
    anything. Two builds of one brand folder at the same time are not supported."""
    for p in brand_dir.iterdir():
        if DISPOSABLE.fullmatch(p.name):
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)


def _exists(p: Path) -> bool:
    return p.exists() or p.is_symlink()


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


def _prune(root: Path, keep_root: bool = False) -> None:
    """Remove the empty folders under `root`, deepest first, then `root` (unless `keep_root`)."""
    for d in sorted((p for p in root.rglob("*") if p.is_dir() and not p.is_symlink()),
                    key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    if not keep_root:
        root.rmdir()


def _swap(brand_dir: Path, staging: Path, previous: Path, discard: Path) -> None:
    """Move the old MANAGED items into `previous`, then the staged ones into `brand_dir`, then
    rename `previous` to `discard` (which any later build may delete). All renames stay on one
    filesystem (both folders are inside `brand_dir`), so each is atomic. The last rename is
    inside the same try, so the only window in which `previous` outlives a complete swap is
    between two renames.

    If anything fails or is interrupted, the rollback works from what is actually on disk (not
    from a record of finished renames, which an interrupt can leave one step behind): a new
    item in place is removed, each old item in `previous` is moved back, folders the swap
    made are removed, and the error is raised again. If the rollback itself fails, `previous`
    is kept, and the next build refuses to start until it is dealt with."""
    existed = {n for n in MANAGED if _exists(brand_dir / n)}  # before any rename
    made = [d for d in {(brand_dir / n).parent for n in MANAGED} if not _exists(d)]
    previous.mkdir()
    try:
        for name in MANAGED:
            if name in existed:
                (previous / name).parent.mkdir(parents=True, exist_ok=True)
                os.rename(brand_dir / name, previous / name)
        for name in MANAGED:
            if _exists(staging / name):
                (brand_dir / name).parent.mkdir(parents=True, exist_ok=True)
                os.rename(staging / name, brand_dir / name)
        os.rename(previous, discard)  # done: the old outputs are now disposable
    except BaseException as exc:
        if not _exists(previous) and _exists(discard):
            raise  # interrupted after the last rename: the swap is complete, keep the new build
        stuck = []
        for name in MANAGED:
            here, old = brand_dir / name, previous / name
            try:
                if name not in existed:  # whatever is here now is new
                    if _exists(here):
                        _remove(here)
                elif _exists(old):  # moved aside: anything here now is new
                    if _exists(here):
                        _remove(here)
                    os.rename(old, here)
                # else: the old item was never moved and is still in place
            except OSError:
                stuck.append(name)
        for d in made:
            try:
                d.rmdir()  # only if still empty
            except OSError:
                pass
        if stuck:  # keep `previous`: it holds the only copy of what could not be restored
            _prune(previous, keep_root=True)  # drop empty folders (report/) left by the rollback
            raise RuntimeError(
                f"the build failed while swapping in the new outputs ({exc!r}) and could not "
                f"restore {', '.join(stuck)}. {previous} keeps your earlier outputs: "
                f"{_held_files(previous)}. {_move_back(previous)} A rebuild will refuse to "
                "start until that folder is gone.") from exc
        _prune(previous)
        raise


def run(brand_dir: Path, config: Path | None = None, layout: str | None = None,
        assessment: assess.Assessment | None = None) -> BuildResult:
    """Build every output and the three documents under `brand_dir` from the brand.toml at
    `config` (default: `config.BRAND`, the one next to the package). Sources resolve against
    `brand_dir`. `layout` (config.LAYOUT_TOOLS or LAYOUT_SKILL; default: from where `config`
    sits, see `config.layout_of`) is recorded on the result for the documents. `assessment`
    (`assess.assess` of the sources) goes into the documents; default: assessed here.

    Raises RuntimeError, before any work, when Chrome or potrace is missing (deps.check_tools)
    or when an interrupted build left a `.build-previous-<pid>` folder (`_check_interrupted`).
    Everything is built into a staging folder inside `brand_dir` and swapped into place (see
    MANAGED) only when the build, the verification and the documents all succeed; on any
    failure the previous outputs are left untouched and the error is raised."""
    missing = [t for t in deps.check_tools() if t in ("chrome", "potrace")]
    if missing:  # before any work
        hints = "; ".join(f"{t}: {deps.INSTALL_HINTS[t]}" for t in missing)
        raise RuntimeError(f"cannot build: missing {', '.join(missing)} ({hints})")
    brand_dir = Path(brand_dir)
    cfg_path = Path(config or config_mod.BRAND)
    brand = config_mod.load_brand(brand_dir, cfg_path)
    data = tomllib.loads(cfg_path.read_text())
    config_mod.check_tables(data)  # before any work
    settings = compose.load_settings(cfg_path)
    layout = layout or config_mod.layout_of(brand_dir, cfg_path)
    _check_interrupted(brand_dir)
    _check_report_folder(brand_dir)
    _remove_stale(brand_dir)
    staging = brand_dir / f"{STAGING}{os.getpid()}"
    previous = brand_dir / f"{PREVIOUS}{os.getpid()}"
    discard = brand_dir / f"{DISCARD}{os.getpid()}"
    staging.mkdir()
    try:
        res = _build(staging, brand, data["elements"], cfg_path, settings, layout)
        if assessment is None:
            assessment = assess.assess([v.source for v in brand.variants.values()])
        # imported here: report imports this module at load time
        from . import report
        # the documents describe brand_dir (paths, rebuild command) but are written to staging
        report.write_all(brand_dir, assessment, res, layout=layout, out=staging)
        _swap(brand_dir, staging, previous, discard)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        # the old outputs after a complete swap; whatever a kill leaves, the next build removes
        shutil.rmtree(discard, ignore_errors=True)
    res.files = [brand_dir / p.relative_to(staging) for p in res.files]
    return res


def _build(out: Path, brand: config_mod.Brand, rules: dict, cfg_path: Path,
           settings: compose.Settings, layout: str) -> BuildResult:
    """Build every output into `out` (an empty folder); raise when a lockup fails verify."""
    svg_dir, png_dir = out / "svg", out / "png"
    pkg = out / "logo-package"
    for d in (svg_dir, png_dir, pkg / "svg", pkg / "pdf", pkg / "png"):
        d.mkdir(parents=True)
    res = BuildResult(brand=brand, config=cfg_path, settings=settings, layout=layout)
    if brand.mark_element is None:
        res.notes.append(NO_MARK_NOTE)

    def add(p: Path) -> Path:
        res.files.append(p)
        return p

    stacked_min = {}
    for v, spec in brand.variants.items():
        source, tile = spec.source, spec.tile
        with Image.open(source) as img:
            rgba = np.asarray(img.convert("RGBA")).copy()
        els = segment.split_elements(rgba, rules)
        res.elements[v] = els
        res.dropped[v] = segment.dropped_components(rgba, rules)
        raw = compose.stacked(v, els, rgba=rgba, settings=settings)
        stk = minify.minify(raw, STACKED_W, 0)
        stacked_min[v] = stk

        # lockup gate: what ships is what is verified
        name = f"logo-stacked-{v}.svg"
        result = verify.compare(stk, source, verify.viewbox_region(raw), cfg_path)
        res.verify[name] = result
        if not result.passed:
            raise RuntimeError(f"{name} failed verification against {source.name}: "
                               f"iou={result.iou:.4f}, color_error={result.color_error:.2f}")
        add(svg_dir / name).write_text(stk)

        # the mark (or, without a mark element, the lockup in its place)
        if brand.mark_element is not None:
            mark_raw = compose.mark(v, els, rgba=rgba, element=brand.mark_element,
                                    settings=settings)
            mark = minify.minify(mark_raw, MARK_W, 0)
            add(svg_dir / f"mark-{spec.mark_name}.svg").write_text(mark)
            el = els[brand.mark_element]
            mark_mask, mark_bbox = el.mask, el.bbox
        else:
            mark_raw = raw
            mark_mask, mark_bbox = _union(els)

        # icons and favicons
        outline = _outline_color(mark_raw)
        if outline is not None:
            res.contrast[f"icon-{v}"] = contrast_ratio(outline, tile)
        rounded = minify.minify(_tile_icon(mark_raw, tile, rounded=True), ICON_S, 0)
        square = minify.minify(_tile_icon(mark_raw, tile, rounded=False), ICON_S, 0)
        maskable = minify.minify(_maskable_icon(mark_raw, mark_mask, mark_bbox, tile), ICON_S, 0)
        add(svg_dir / f"icon-{v}.svg").write_text(rounded)
        for s in (192, 512):
            _write_png(add(png_dir / f"icon-{v}-{s}.png"), render.svg_to_png(rounded, s, s))
        _write_png(add(png_dir / f"icon-{v}-maskable-512.png"),
                   render.svg_to_png(maskable, 512, 512))
        _write_png(add(png_dir / f"apple-touch-icon-{v}-180.png"),
                   render.svg_to_png(square, 180, 180, bg=tile), opaque=True)
        small = rounded
        if brand.mark_element is not None:
            simple = compose.mark(v, els, rgba=rgba, element=brand.mark_element, simplified=True,
                                  settings=settings)
            small = minify.minify(_tile_icon(simple, tile, rounded=True, fit=SMALL_FIT), ICON_S, 0)
        fav = {s: render.svg_to_png(small if s == SMALL_PX else rounded, s, s)
               for s in (16, 32, 48)}
        for s, a in fav.items():
            _write_png(add(png_dir / f"favicon-{v}-{s}.png"), a)
        _ico(add(png_dir / f"favicon-{v}.ico"), fav)

        # PNG lockup (transparent) and email headers (opaque white)
        _, _, vw, vh = _viewbox(stk)
        _write_png(add(png_dir / f"logo-stacked-{v}-1200.png"),
                   render.svg_to_png(stk, 1200, round(1200 * vh / vw)))
        for W in (600, 1200):
            H = round(W * 0.5)
            x, y, w, h = _fit(stk, W, H)
            _write_png(add(png_dir / f"email-header-{v}-{W}.png"),
                       render.svg_to_png(_canvas(W, H, _nest(stk, x, y, w, h)), W, H, bg=WHITE),
                       opaque=True)

    # share card: the share-card variant's lockup on opaque white
    card = stacked_min[brand.share_card_variant]
    x, y, w, h = _fit(card, 1200, 630, box_h=SHARE_H)
    share = _canvas(1200, 630, _nest(card, x, y, w, h))
    _write_png(add(png_dir / "share-card-1200x630.png"),
               render.svg_to_png(share, 1200, 630, bg=WHITE), opaque=True)

    # handoff folder
    for f in sorted(svg_dir.glob("*.svg")):
        if f.name.startswith("icon-"):
            continue
        add(pkg / "svg" / f.name).write_text(f.read_text())
        render.svg_to_pdf(f.read_text(), add(pkg / "pdf" / f"{f.stem}.pdf"))
    for v in brand.variants:
        for n in (f"logo-stacked-{v}-1200", f"email-header-{v}-1200", f"icon-{v}-512",
                  f"icon-{v}-192"):
            shutil.copyfile(png_dir / f"{n}.png", add(pkg / "png" / f"{n}.png"))
    return res
