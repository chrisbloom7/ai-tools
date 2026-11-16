"""Write the three documents from the data objects: README.md, logo-package/README.txt and
report/conversion-report.md.

  report.write_all(brand_dir, assessment, results)
  report.write_all(brand_dir, assessment, results, out=staging)  # what build.run does

`results` is the `build.BuildResult`. It carries the brand (`config.load_brand`: name, variants,
mark, tiles, share-card variant, `[report] notes`), the brand.toml path and `[compose]`
settings the build used, the segmented elements and the pieces segmentation dropped. Every name
and number in the documents comes from that data, the built SVGs or brand.toml. Facts about the
art that the code cannot measure come only from `[report] notes`, listed under "Known limits of
this conversion" in the report.
"""

import re
import shlex
import textwrap
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image

from . import assess, build, compose, variants
from . import config as config_mod

WIDTH = 100
SCRIPTS_DIR = Path(__file__).resolve().parent.parent  # the folder that holds cli.py
DESIGNER_ASK = ("Please send transparent PNGs at 3000 px or more, one per variant, ideally one per "
                "element on the same canvas, plus any vector or layered originals you have.")
SHARE_TOL = 0.95  # IoU at or above which a piece counts as the same drawing in both variants
DROPPED_SHOWN = 3  # dropped pieces described per variant (the largest)
SMALL = build.SMALL_PX  # the favicon size drawn from the simplified mark
COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


# --- text helpers ------------------------------------------------------------------------------

def wrap(text: str, indent: str = "", subsequent: str | None = None) -> str:
    """Hard-wrap at WIDTH. A wrapped line never starts with `#`: such a line is joined back."""
    sub = indent if subsequent is None else subsequent
    lines = textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=sub,
                          break_long_words=False, break_on_hyphens=False)
    out: list[str] = []
    for line in lines:
        if out and line.lstrip().startswith("#"):
            out[-1] += " " + line.strip()
        else:
            out.append(line)
    return "\n".join(out)


def _escape_hash(text: str) -> str:
    """Escape `#<digit>` (an issue or PR number) so it renders as text in any markdown editor."""
    parts = text.split("`")
    for i in range(0, len(parts), 2):  # even parts are outside code spans
        parts[i] = re.sub(r"(?<![\w&\\])#(?=\d)", r"\\#", parts[i])
    return "`".join(parts)


def _md_para(text: str) -> str:
    return wrap(_escape_hash(text))


def _bullets(items: list[str]) -> str:
    return "\n".join(wrap(_escape_hash(i), "- ", "  ") for i in items)


def _join(items, last: str = "and") -> str:
    """'a', 'a and b', 'a, b and c' (or with `last` = 'or')."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def _brace(names) -> str:
    """'primary' for one name, '{primary,alt}' for several (shell brace style, for file
    patterns)."""
    names = list(names)
    return names[0] if len(names) == 1 else "{" + ",".join(names) + "}"


def _alts(paths: list[str]) -> str:
    """'svg/a.svg or b.svg': the first path in full, the rest by file name (same folder)."""
    return _join([paths[0]] + [p.rsplit("/", 1)[-1] for p in paths[1:]], "or")


def _count(n: int) -> str:
    return COUNT_WORDS.get(n, str(n))


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _read_rgba(path: Path) -> np.ndarray | None:
    if not Path(path).is_file():
        return None
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA"))


# --- what the documents are about --------------------------------------------------------------

class _Doc:
    """Everything the three documents need, read once from the build result and brand.toml."""

    def __init__(self, brand_dir: Path, assessment, results, layout: str | None = None,
                 out: Path | None = None):
        self.dir = Path(brand_dir)  # the brand folder the documents describe
        self.out = Path(out or brand_dir)  # where the built files are and the documents go
        self.a, self.r = assessment, results
        self.cfg_path = Path(results.config or config_mod.BRAND)
        self.layout = (layout or getattr(results, "layout", None)
                       or config_mod.layout_of(self.dir, self.cfg_path))
        self.tools = self.layout == config_mod.LAYOUT_TOOLS
        # how the documents name the config file (relative to the brand folder)
        self.cfg_name = "tools/brand.toml" if self.tools else "brand.toml"
        self.brand = results.brand or config_mod.load_brand(self.dir, self.cfg_path)
        self.toml = tomllib.loads(self.cfg_path.read_text())
        self.settings = results.settings or compose.load_settings(self.cfg_path)
        self.names = list(self.brand.variants)
        self.mark = self.brand.mark_element
        self.outline = self.toml.get("elements", {}).get("outline", "outline")
        self.matches = variants.match_first(
            {v: results.elements.get(v, {}) for v in self.names}, 0.0)

    def source(self, v: str) -> str:
        """The variant's source path relative to the brand folder (its file name if outside)."""
        src = self.brand.variants[v].source
        try:
            return src.relative_to(self.dir).as_posix()
        except ValueError:
            return src.name

    def shared(self, other: str) -> dict[str, float]:
        """Pieces the first variant and `other` share (IoU at or above SHARE_TOL)."""
        return {k: v for k, v in self.matches[other].shared.items() if v >= SHARE_TOL}

    def gradients(self) -> bool:
        """Whether any element has a gradient layer."""
        return any(e.gradient_layers for els in self.r.elements.values() for e in els.values())

    def drawn(self) -> str:
        """What the icons show: the mark, or the lockup when there is no mark element."""
        return "mark" if self.mark else "lockup"


def _small_note(d: _Doc) -> str:
    """What the 16 px favicon is."""
    if d.mark is None:
        return (f"The {SMALL} px favicon (the .png and the {SMALL} px image inside each .ico) is "
                "the icon scaled down, like the 32 and 48 px ones: there is no mark, so the icon "
                "shows the whole lockup.")
    bodies = []
    for v in d.names:
        el = d.r.elements.get(v, {}).get(d.mark)
        layers = [n for n in el.layers if n not in compose.SIMPLIFIED_DROP] if el else []
        if layers:
            bodies.append(f"{_join(f'`{n}`' for n in layers)} on {v}")
    which = f" ({'; '.join(bodies)})" if bodies else ""
    return (f"The {SMALL} px favicon (the .png and the {SMALL} px image inside each .ico) is a "
            "simplified drawing, not the icon scaled down: only the mark's body "
            f"layer{'s' if len(bodies) != 1 else ''}{which}, with no {d.outline} outline and no "
            "halo, enlarged to fill the tile. The outline would blur into mush at that size.")


def _inventory(d: _Doc) -> list[tuple[list[str], str]]:
    b, n = _brace(d.names), len(d.names)
    s = "s" if n > 1 else ""
    what = d.drawn()
    rows = [([f"`{d.source(v)}`" for v in d.names], "The original art, untouched. Never edit."),
            ([f"`svg/logo-stacked-{b}.svg`"],
             f"Full lockup{s} (minified{', with gradients' if d.gradients() else ''}).")]
    if d.mark:
        marks = [d.brand.variants[v].mark_name for v in d.names]
        rows.append(([f"`svg/mark-{_brace(marks)}.svg`"], f"{d.mark.capitalize()} mark alone."))
    favicons = (f"Favicons. The {SMALL} px one is a simplified drawing (see below)." if d.mark
                else "Favicons: the icon scaled down.")
    rows += [
        ([f"`svg/icon-{b}.svg`"], f"App icon source: {what} on a colored rounded tile."),
        ([f"`png/logo-stacked-{b}-1200.png`"], f"Lockup{s}, transparent, 1200 px wide."),
        ([f"`png/email-header-{b}-{{600,1200}}.png`"],
         "Email headers, opaque white background, 2:1."),
        (["`png/share-card-1200x630.png`"],
         f"Social share card: {d.brand.share_card_variant} lockup on opaque white."),
        ([f"`png/icon-{b}-{{192,512}}.png`"], "Web app icons (rounded tile)."),
        ([f"`png/icon-{b}-maskable-512.png`"],
         f"Maskable icon{s}: full-bleed tile, {what} in the safe area."),
        ([f"`png/apple-touch-icon-{b}-180.png`"], f"Apple touch icon{s} (opaque tile)."),
        ([f"`png/favicon-{b}-{{16,32,48}}.png`", f"`png/favicon-{b}.ico`"], favicons),
        (["`logo-package/`"],
         "Self-contained handoff folder (svg, pdf, png) with its own README.txt."),
        (["`report/conversion-report.md`"],
         "What the input graded, verify numbers, what to ask the designer."),
        (["`tools/`"], "The pipeline (`logo_pipeline`), `build.py` and `brand.toml`.")
        if d.tools else
        (["`brand.toml`"], "The build config: variants, elements, palette, tiles and the verify "
                           "bar. Edit it, then rebuild."),
    ]
    return rows


def _background_rule(d: _Doc) -> list[str]:
    """'Use the primary files on light backgrounds and the alt files on dark backgrounds.'"""
    uses = [f"the {v} files on {d.brand.variants[v].background} backgrounds" for v in d.names
            if d.brand.variants[v].background]
    return [f"Use {_join(uses)}."] if uses else []


def _halo_bands(d: _Doc) -> dict[str, tuple[float, float, str]]:
    """{variant: (width in source px, opacity, color)} of the halo band, from the built lockups."""
    out = {}
    for v in d.names:
        f = d.out / "svg" / f"logo-stacked-{v}.svg"
        m = f.exists() and re.search(r'<g [^>]*class="n-halos"[^>]*>', f.read_text())
        if m:
            px = re.search(r'data-halo-px="([0-9.]+)"', m.group(0))
            op = re.search(r'\sopacity="([0-9.]+)"', m.group(0))
            fill = re.search(r'\sfill="(#[0-9a-fA-F]{3,6})"', m.group(0))
            if px and op:
                out[v] = (float(px.group(1)), float(op.group(1)),
                          fill.group(1) if fill else "")
    return out


def _is_white(color: str) -> bool:
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return len(h) == 6 and all(int(h[i:i + 2], 16) >= 0xf0 for i in (0, 2, 4))


def _speck_fate(d: _Doc, v: str, counted: int) -> str | None:
    """How many of the blobs the preflight counted stay with the art and how many were dropped,
    from the source and the element masks. None when the source cannot be read."""
    els = d.r.elements.get(v)
    rgba = _read_rgba(d.brand.variants[v].source)
    if not counted or rgba is None or not els:
        return None
    kept = np.logical_or.reduce([e.mask for e in els.values()])
    if kept.shape != rgba.shape[:2]:
        return None
    labels, ids = assess.speck_labels(rgba)
    inside = sum(1 for i in ids if kept[labels == i].any())
    out = len(ids) - inside
    return (f"{d.brand.variants[v].source.name}: {inside} of the {len(ids)} counted blobs touch a "
            f"kept piece of the art and stay with it; {out} "
            f"{'is' if out == 1 else 'are'} part of what segmentation dropped (next section).")


def _dropped_line(d: _Doc, v: str) -> str:
    name = d.brand.variants[v].source.name
    drops = d.r.dropped.get(v, [])
    if not drops:
        return f"{name}: nothing dropped."
    solid = d.toml.get("elements", {}).get("alpha_solid", 128)
    specks = sum(1 for p in drops if p.max_alpha >= solid)
    kinds = f"{_plural(specks, 'speck')}, {_plural(len(drops) - specks, 'faint wisp')}"
    shown = []
    for i, p in enumerate(drops[:DROPPED_SHOWN]):
        x, y = p.centroid
        shown.append(f"{'about ' if i == 0 else ''}{p.area} px (max alpha {p.max_alpha}, mean "
                     f"color `{p.color}`, near x={x}, y={y})")
    head = "The largest" if len(drops) > DROPPED_SHOWN else "By size"
    return (f"{name}: {_plural(len(drops), 'detached piece')} dropped ({kinds}). {head}: "
            + "; ".join(shown) + ".")


# --- report/conversion-report.md -------------------------------------------------------------

def _report(d: _Doc) -> str:
    a, r, st = d.a, d.r, d.settings
    bar = d.toml["verify"]
    s: list[str] = ["# Conversion report", ""]
    made = ("`tools/build.py`" if d.tools
            else "`cli.py build` (the `logo-package` skill's `scripts/cli.py`)")
    s += [_md_para(f"Generated by {made} on every build. Do not edit by hand; rebuild "
                   "instead."), ""]

    shortest = min((min(f.width, f.height) for f in a.files), default=None)
    why = []
    if shortest is not None:
        why.append(f"shortest side {shortest} px")
    if a.files:
        why.append("all files have transparency" if all(f.has_alpha for f in a.files)
                   else "some files have no transparency")
    why.append("one canvas size across variants" if a.same_canvas
               else "different canvas sizes across variants")
    why.append("flat (not per-element layers)")
    s += ["## Input grade", ""]
    s += [_md_para(f"The input graded **{a.tier.capitalize()}**: " + ", ".join(why) + ". "
                   + assess.TIER_EXPECT[a.tier])]
    s += ["", f"| File | Size | Alpha | Gradient found | Opaque blobs of "
              f"{assess.SPECK_MAX_AREA} px or less |",
          "|---|---|---|---|---|"]
    for f in a.files:
        s.append(f"| {f.path.name} | {f.width}x{f.height} | {'yes' if f.has_alpha else 'no'} | "
                 f"{'yes' if f.gradient else 'no'} | {f.specks} |")

    s += ["", "## Preflight findings", ""]
    s += [_bullets(a.findings) if a.findings else "- None."]
    counted = {f.path.name: f.specks for f in a.files}
    fates = [x for v in d.names
             if (x := _speck_fate(d, v, counted.get(d.brand.variants[v].source.name, 0)))]
    s += ["", _md_para("The last column above is what the preflight counted, not what was "
                       "dropped: it counts every small opaque blob that touches no other along an "
                       "edge, and segmentation keeps a blob that touches the art at a corner.")]
    if fates:
        s += ["", _bullets(fates)]

    s += ["", "## Segmentation: what was dropped", ""]
    s += [_md_para("Segmentation leaves out detached pieces: opaque specks below the area floor in "
                   f"`{d.cfg_name}` `[elements]` (with their soft fringe) and faint wisps that "
                   "touch no kept piece. Positions are in source pixels.")]
    s += ["", _bullets([_dropped_line(d, v) for v in d.names])]

    s += ["", "## Verify numbers", ""]
    s += [_md_para("Each shipped lockup is rendered in Chrome and compared with its source PNG: "
                   "alpha IoU (overlap of the opaque shapes) and mean color error (per-channel "
                   "difference, 0 to 255, over pixels opaque in both). The build fails if either "
                   f"misses the bar in `{d.cfg_name}` `[verify]`: IoU at least "
                   f"{bar['iou_min']}, color error at most {bar['color_error_max']}.")]
    s += ["", "| File | Alpha IoU | Mean color error | Passed |", "|---|---|---|---|"]
    for name, res in r.verify.items():
        s.append(f"| {name} | {res.iou:.4f} | {res.color_error:.2f} | "
                 f"{'yes' if res.passed else 'NO'} |")
    s += ["", _md_para(f"The color error bar is set in `{d.cfg_name}` `[verify]`; it is a "
                       "regression guard, not a fidelity claim. The stacked lockup is the only "
                       "file compared with the source. The marks, and so the icons and "
                       "favicons, are traced separately and are checked by eye only: look at "
                       "them. The headers and share card are made from the verified lockup "
                       "SVG; the PDFs are the lockup and mark SVGs.")]

    s += ["", "## How each element was traced", ""]
    if r.elements:
        s += ["| Variant | Element | Traced as | Gradient layers |", "|---|---|---|---|"]
        for v, els in r.elements.items():
            for name, e in els.items():
                kind = "flat plus gradient" if e.kind == "gradient" else "flat"
                s.append(f"| {v} | {name} | {kind} | {', '.join(e.gradient_layers) or 'none'} |")
        s += [""]
    if d.gradients():
        s += [_md_para(f"Gradient layers are a vertical linearGradient with {st.stops} stops, "
                       "sampled from the art.")]
    else:
        s += [_md_para("No element has a gradient layer; every layer is one flat color sampled "
                       "from the art.")]
    bands = _halo_bands(d)
    if bands:
        each = "; ".join(f"{v} {w:g} px of source art at opacity {op:.2f}"
                         for v, (w, op, _) in bands.items())
        white = all(_is_white(c) for _, _, c in bands.values())
        halo = (f"The {'white ' if white else ''}halo is a uniform-width translucent band, not a "
                "feathered glow: each element's outline silhouette offset outward by one width, "
                f"drawn behind the bodies at one opacity ({each}). Width is the median distance "
                "from the outline to the outer edge of the art's halo (alpha "
                f"{st.halo_alpha} and up), and opacity the median alpha of those halo pixels, both "
                "pooled over every element of the variant. The band has one width everywhere, so "
                "an uneven rim in the art comes out even.")
    else:
        halo = "The lockups have no halo."
    s += ["", _md_para(halo)]

    s += ["", "## Pieces shared between variants", ""]
    s += _sharing(d)

    s += ["", "## Icons, headers and share card", ""]
    items = [_tiles(d)]
    if r.contrast:
        ratios = [f"{c:.2f}:1 ({k.removeprefix('icon-')})" for k, c in r.contrast.items()]
        values = list(r.contrast.values())
        if all(c >= 3 for c in values):
            target = ", meeting the 3:1 graphics target."
        elif all(2.5 <= c < 3 for c in values):
            target = ", just under the 3:1 graphics target."
        elif all(c < 3 for c in values):
            target = ", under the 3:1 graphics target."
        else:
            target = "; the 3:1 graphics target is met only where the ratio is 3 or more."
        items[-1] += f" The {d.outline} outline's contrast on the tile is {_join(ratios)}{target}"
    items += ["The email headers are the lockup centered on an opaque white background (RGB, no "
              "alpha), so they look the same in light and dark email clients. A transparent "
              "version is not shipped.",
              _small_note(d),
              f"The share card is the {d.brand.share_card_variant} lockup on opaque white."]
    items += list(r.notes)
    s += [_bullets(items)]

    s += ["", "## What to expect", ""]
    s += [_bullets([
        "Shapes and colors match the source within the bar above. The art is traced, so curves "
        "stay smooth at any size, but sharp corners and perfectly straight edges are softened "
        "slightly by the tracing.",
        "Texture and fine grain are not reproduced (see Known limits of this conversion).",
        "RGB only. No CMYK, EPS or AI files. Use the designer's originals for print-critical or "
        "large-format work.",
        "PDFs in `logo-package/pdf/` are vector."])]

    s += ["", "## Known limits of this conversion", ""]
    s += [_bullets(["Texture and fine grain inside fills are not reproduced; each gradient fill "
                    "is a vertical ramp.",
                    "The verification scores are averages over the whole lockup, so a small "
                    "wrongly colored or misshaped region barely moves them; look at the "
                    "outputs.", *d.brand.notes])]

    s += ["", "## Upgrades to ask the designer for", ""]
    s += [_bullets(a.upgrades) if a.upgrades else "- None; the input is already Best."]
    s += ["", _md_para("Suggested message: " + DESIGNER_ASK)]
    return "\n".join(s) + "\n"


def _sharing(d: _Doc) -> list[str]:
    """The "pieces shared between variants" section: the first variant against each other."""
    if not d.matches:
        return [_md_para(f"There is only one variant ({d.names[0]}), so there is nothing to "
                         "compare.")]
    first = d.names[0]
    s: list[str] = []
    if len(d.matches) > 1:
        s += [_md_para(f"With {_count(len(d.names))} variants, the first ({first}) is compared "
                       "with each of the others."), ""]
    paras = []
    for o, m in d.matches.items():
        shared = d.shared(o)
        if shared:
            paras.append(f"Pieces shared between {first} and {o} (IoU at or above {SHARE_TOL}): "
                         + ", ".join(f"{k} ({v:.3f})" for k, v in shared.items()) + ".")
        else:
            paras.append(f"No pieces are shared: no piece reached an IoU of {SHARE_TOL} between "
                         f"{first} and {o}. {first.capitalize()} and {o} are separate drawings, "
                         "so each variant is traced on its own.")
        if m.variant_only:
            paras.append(f"Present in only one of {first} and {o}: "
                         + ", ".join(m.variant_only) + ".")
    s += "\n\n".join(_md_para(p) for p in paras).split("\n")
    pieces = sorted({k for m in d.matches.values() for k in m.shared})
    if pieces:
        cols = list(d.matches)
        s += ["", "| Piece | " + " | ".join(f"{first.capitalize()} vs {o} IoU" for o in cols)
              + " |", "|---|" + "---|" * len(cols)]
        for k in pieces:
            cells = [f"{d.matches[o].shared[k]:.3f}" if k in d.matches[o].shared else "-"
                     for o in cols]
            s.append(f"| {k} | " + " | ".join(cells) + " |")
    return s


def _tiles(d: _Doc) -> str:
    """Tile colors per variant; named after the palette entry they equal, when they do."""
    palette = d.toml.get("elements", {}).get("palette", {})
    anchors = {c.lower(): name for name, ramp in palette.items() for c in ramp}
    tiles = {v: d.brand.variants[v].tile for v in d.names}
    if tiles and all(t.lower() in anchors for t in tiles.values()):
        return ("Icon and favicon tiles take their color from the art's palette in "
                f"`{d.cfg_name}`: "
                + ", ".join(f"{v} `{t}` (`{anchors[t.lower()]}`)" for v, t in tiles.items()) + ".")
    return (f"Icon and favicon tiles use each variant's `tile` color from `{d.cfg_name}`: "
            + ", ".join(f"{v} `{t}`" for v, t in tiles.items()) + ".")


# --- README.md -------------------------------------------------------------------------------

def _readme(d: _Doc) -> str:
    name, n = d.brand.name, len(d.names)
    versions = (f"{_join(d.names)} versions" if n > 1 else f"one version, {d.names[0]}")
    s = [f"# {name} brand assets", "",
         _md_para(f"Logo files for {name}, converted from the designer's flat PNGs ({versions}) "
                  "into SVG, PNG, PDF and icon files by "
                  + ("the pipeline in `tools/`" if d.tools
                     else "the `logo-package` skill's pipeline")
                  + ". For the person who owns the brand and for future agents."),
         "", "## What is here", "", "| Path | What it is |", "|---|---|"]
    s += [f"| {', '.join(paths)} | {what} |" for paths, what in _inventory(d)]
    out_dirs = [f"`{o}/`" for o in build.OUT_DIRS]
    s += ["", "## Usage rules", ""]
    s += [_bullets(_background_rule(d) + [
        "The email headers are always on an opaque white background, whichever variant they "
        "show.",
        f"Never edit `{d.source(d.names[0]).split('/')[0]}/`; it is the input. Never hand-edit "
        f"{', '.join(out_dirs)} or `report/`: a rebuild deletes and regenerates "
        f"{_join(out_dirs)}, and overwrites `report/conversion-report.md`.",
        "Do not recolor, restyle or redraw the art; ask the designer for new artwork instead.",
        "RGB only. There is no CMYK, EPS or AI output, and no one-color version. For "
        "print-critical or large-format work, use the designer's original files.",
        "Scale the logo in proportion; do not stretch it.",
        _small_note(d)])]
    s += ["", "## Rebuild", ""] + (_rebuild_tools() if d.tools else _rebuild_skill(d.dir))
    s += ["", "## Status", ""]
    s += [_md_para(f"The input graded **{d.a.tier.capitalize()}**. See "
                   "[report/conversion-report.md](report/conversion-report.md) for the verify "
                   "numbers, what to expect and what to ask the designer for.")]
    if d.r.notes:
        s += ["", _md_para("Notes from the build:"), "", _bullets(list(d.r.notes))]
    return "\n".join(s) + "\n"


def _rebuild_tools() -> list[str]:
    """The Rebuild section for a brand folder that keeps the pipeline in tools/."""
    return [_md_para("From the brand folder, or from `tools/`. Both run the same build: assess "
                     "the sources, build every file, verify, and rewrite this README, the "
                     "package README and the report."), "",
            "    uv run --project tools python tools/build.py", "",
            "    cd tools && uv run python build.py", "",
            _md_para("Needs `uv`, Chrome and `potrace` (the build checks and says what is "
                     "missing). Tests, from `tools/` (the tests marked slow do real builds):"),
            "", "    uv run pytest"]


def _rebuild_skill(brand_dir: Path) -> list[str]:
    """The Rebuild section for a brand folder built by the logo-package skill: a complete
    command with the scripts folder this build ran from and this brand folder."""
    q = shlex.quote
    scripts = SCRIPTS_DIR.as_posix()
    cmd = (f"uv run --project {q(scripts)} python {q(scripts + '/cli.py')} build "
           f"{q(Path(brand_dir).resolve().as_posix())}")
    return [_md_para("Edit `brand.toml`, then run the build on this folder. It assesses the "
                     "sources, builds every file, verifies, and rewrites this README, the "
                     "package README and the report."), "",
            f"    {cmd}", "",
            _md_para("`cli.py` is `scripts/cli.py` of the `logo-package` skill (Claude Code plugin "
                     "`chrisbloom7-design`); the path above is where this build ran from. If the "
                     "plugin has moved since, the skill's SKILL.md gives the command. Needs `uv`, "
                     "Chrome and `potrace` (`cli.py check` says what is missing).")]


# --- logo-package/README.txt -----------------------------------------------------------------

def _package_txt(d: _Doc) -> str:
    p: list[str] = []
    names, n = d.names, len(d.names)

    def para(t: str, ind: str = "", sub: str | None = None) -> None:
        p.append(wrap(t, ind, sub))

    def files(pattern: str) -> str:
        return _alts([pattern.format(v=v) for v in names])

    title = f"{d.brand.name.upper()} LOGO PACKAGE"
    p += [title, "=" * len(title), ""]
    upper = [v.upper() for v in names]
    uses = [f"{v.upper()} is for {d.brand.variants[v].background} backgrounds." for v in names
            if d.brand.variants[v].background]
    if n > 1 and len(uses) == n:
        intro = f"in {_count(n)} versions. " + " ".join(uses)
    else:
        intro = (f"in {_count(n)} version{'s' if n > 1 else ''}: {_join(upper)}."
                 + (" " + " ".join(uses) if uses else ""))
    para(f"This folder has the {d.brand.name} logo {intro} Everything here is ready to use on "
         "screen (websites, email, social media and shop listings). Before you print anything, "
         "read WHAT IS NOT INCLUDED below.")
    p += ["", "WHICH FILE FOR WHICH JOB", "-" * 24]
    lockups = files("svg/logo-stacked-{v}.svg")
    if d.mark:
        marks = [f"svg/mark-{d.brand.variants[v].mark_name}.svg" for v in names]
        cut = f"{_join(marks, 'or')}, or the SVG lockups."
    else:
        cut = f"the SVG lockups ({lockups})."
    each = "It has" if n == 1 else ("Both have" if n == 2 else "All have")
    rows = [
        ("Website", f"{lockups}. Sharp at any size and small to download."),
        ("Print shop (stickers, shirts, flyers)",
         f"{files('pdf/logo-stacked-{v}.pdf')}. These are vector files: they stay sharp at any "
         "size. See WHAT IS NOT INCLUDED below before you send them to print."),
        ("Signs, banners and other large-format print",
         "use the designer's original art, not these files (see WHAT IS NOT INCLUDED below)."),
        ("Etsy and other shop listings",
         f"{files('png/logo-stacked-{v}-1200.png')} (transparent background)."),
        ("Cutting machine (Cricut, Silhouette)",
         f"{cut} The art is full color with many overlapping pieces, so it suits print-then-cut; "
         "for vinyl, ask the designer for separate one-color shapes."),
        ("Email", f"{files('png/email-header-{v}-1200.png')}. {each} a white background, so "
                  f"{'it looks' if n == 1 else 'they look'} the same in light and dark email "
                  "clients."),
        ("Social media and profile pictures",
         f"{files('png/icon-{v}-512.png')} for a profile picture (192 is for small avatars). For "
         "a post or link image, use the lockup PNG on a plain background."),
    ]
    if d.mark:
        mark_names = [d.brand.variants[v].mark_name for v in names]
        rows.append((f"The mark alone ({_join(mark_names, 'or')})",
                     f"{', '.join(marks)} and the matching PDFs in pdf/."))
    for tool, what in rows:
        para(f"{tool}: {what}", "* ", "  ")
    p += ["", "WHAT IS NOT INCLUDED", "-" * 20]
    for t in ["RGB only (screen colors). There are no CMYK files (CMYK is the four-ink color mode "
              "print shops use), and no EPS or AI files (print-industry file formats).",
              "There are no print-ready masters. For print-critical or large-format work (large "
              "banners, signs, exact color matching), use the designer's original art.",
              "The PDFs are vector, but they carry screen (RGB) color, not press color.",
              "The PDFs and PNGs are untagged sRGB: when sending them to a print shop, ask them "
              "to treat the color as sRGB and to check a proof.",
              "No one-color versions."]:
        para(t, "* ", "  ")
    p += ["", "GOOD TO KNOW", "-" * 12]
    good = ["The art was converted from flat PNG files, so texture and fine grain in the "
            "original are not reproduced. Shapes and colors were checked against the original "
            "within a set tolerance; sharp corners and perfectly straight edges are softened "
            "slightly by the tracing."]
    if n > 1:
        if not any(d.shared(o) for o in d.matches):
            good.append(f"Files marked {_join(names)} are different drawings; do not swap parts "
                        "between them.")
        else:
            good.append("Some pieces match between versions (see report/conversion-report.md); "
                        "the rest are different drawings, so do not swap parts between them.")
    for t in good:
        para(t, "* ", "  ")
    return "\n".join(p) + "\n"


def write_all(brand_dir: Path, assessment, results, layout: str | None = None,
              out: Path | None = None) -> None:
    """Write README.md, logo-package/README.txt and report/conversion-report.md under `out`
    (default: `brand_dir`; overwriting them) from the assessment and the `build.BuildResult`.

    The documents describe `brand_dir` (source paths, the rebuild command) and read the built
    SVGs from `out`: `build.run` passes its staging folder as `out`, so they name the final
    brand folder, never the staging one. `layout` (config.LAYOUT_TOOLS or LAYOUT_SKILL) decides
    how the documents name the config and the rebuild command; default: the result's `layout`,
    else from where its config sits."""
    d = _Doc(brand_dir, assessment, results, layout, out)
    (d.out / "report").mkdir(exist_ok=True)
    (d.out / "logo-package").mkdir(exist_ok=True)
    (d.out / "README.md").write_text(_readme(d))
    (d.out / "logo-package" / "README.txt").write_text(_package_txt(d))
    (d.out / "report" / "conversion-report.md").write_text(_report(d))
