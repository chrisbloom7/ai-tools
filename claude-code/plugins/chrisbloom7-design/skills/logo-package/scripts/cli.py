"""The logo-package command line. Run it through uv so the pinned dependencies are used:

  uv run --project <scripts> python <scripts>/cli.py <command> ...

Commands:
  check                    report missing external tools (Chrome, potrace, uv); exit 1 if any
  assess FILE... [--layered]
                           grade the source art (best, good, limited) and say what would help
  colors PNG [--n 12]      dominant opaque colors, for [elements.palette] anchors
  blobs PNG [--out F]      numbered opaque blobs with centers, for [elements.regions] boxes
  init BRAND_DIR           create BRAND_DIR/source/ and BRAND_DIR/brand.toml from the example
  build BRAND_DIR          build every output, verify the lockups and write the documents

`<scripts>` is the folder that holds this file.
"""

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from logo_pipeline import assess, config, deps, report, segment  # noqa: E402
from logo_pipeline import build as pipeline_build  # noqa: E402

EXAMPLE = HERE / "brand.example.toml"
OPAQUE = 128
COLOR_STEP = 16  # colors quantize to a grid of this many levels per channel
COLOR_MERGE = 24.0  # RGB distance under which two grid colors count as one color
COLOR_MIN_SHARE = 0.002  # colors under this share of the opaque pixels are not listed
UNTOUCHED = "The previous outputs were left untouched."  # a failed build changes nothing
RAISE_TRACE = ("Raise the trace scale ([compose] LOCKUP_TRACE up) or fix the [elements] regions "
               "and palette, then build again.")


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


# --- check -----------------------------------------------------------------------------------

def cmd_check(_args) -> int:
    missing = deps.check_tools()
    for name in missing:
        print(f"missing: {name}: install with {deps.INSTALL_HINTS[name]}")
    if missing:
        print("These install hints are for macOS (Homebrew), the tested platform; on Linux "
              "(untested) use your package manager.")
        return 1
    print(f"all tools found (Chrome: {deps.CHROME})")
    return 0


# --- assess ----------------------------------------------------------------------------------

def cmd_assess(args) -> int:
    paths = [Path(p) for p in args.files]
    gone = [str(p) for p in paths if not p.is_file()]
    if gone:
        return _fail(f"no such file: {', '.join(gone)}")
    try:
        a = assess.assess(paths, layered=args.layered)
    except ValueError as e:
        return _fail(str(e))
    except UnidentifiedImageError as e:
        return _fail(f"not a raster image Pillow can read: {e}")
    print(f"tier: {a.tier}")
    print(f"what to expect: {assess.TIER_EXPECT[a.tier]}")
    print("files:")
    for f in a.files:
        print(f"  {f.path.name}: {f.width}x{f.height}, alpha {'yes' if f.has_alpha else 'no'}, "
              f"gradient {'yes' if f.gradient else 'no'}, small opaque blobs "
              f"(<= {assess.SPECK_MAX_AREA} px) {f.specks}"
              f"{', looks lossy' if f.lossy_suspect else ''}")
    if not a.files:
        print("  (no raster files graded)")
    print("findings:")
    for line in a.findings or ["none"]:
        print(f"  - {line}")
    print("upgrades to ask the designer for:")
    for line in a.upgrades or ["none; the input is already Best"]:
        print(f"  - {line}")
    print(f"designer ask: {report.DESIGNER_ASK}")
    return 0


# --- colors ----------------------------------------------------------------------------------

def dominant_colors(rgba: np.ndarray, n: int = 12) -> list[tuple[str, float]]:
    """The `n` most common opaque colors as ("#rrggbb", share of opaque pixels), largest first.

    Opaque pixels (alpha >= OPAQUE) are binned on a COLOR_STEP grid; each bin's color is the
    mean of its pixels; bins whose colors lie within COLOR_MERGE are merged into the larger.
    """
    px = rgba[..., :3][rgba[..., 3] >= OPAQUE].astype(np.int64)
    if not len(px):
        return []
    q = px // COLOR_STEP
    keys = (q[:, 0] << 16) | (q[:, 1] << 8) | q[:, 2]
    uniq, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, inv.ravel(), px)
    means = sums / counts[:, None]
    groups: list[list] = []  # [count, weighted sum]
    for k in np.argsort(-counts, kind="stable"):
        for g in groups:
            if np.linalg.norm(g[1] / g[0] - means[k]) < COLOR_MERGE:
                g[0] += counts[k]
                g[1] = g[1] + sums[k]
                break
        else:
            groups.append([counts[k], sums[k].copy()])
    total = len(px)
    groups.sort(key=lambda g: -g[0])
    out = []
    for count, s in groups[:n]:
        if count / total < COLOR_MIN_SHARE:
            break
        rgb = np.clip(np.round(s / count), 0, 255).astype(int)
        out.append(("#" + "".join(f"{v:02x}" for v in rgb), count / total))
    return out


def _read_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA")).copy()


def cmd_colors(args) -> int:
    path = Path(args.png)
    if not path.is_file():
        return _fail(f"no such file: {path}")
    colors = dominant_colors(_read_rgba(path), args.n)
    if not colors:
        print("no opaque pixels (alpha >= 128)")
        return 0
    print("color     share of opaque pixels")
    for hex_color, share in colors:
        print(f"{hex_color}   {share * 100:5.1f}%")
    return 0


# --- blobs -----------------------------------------------------------------------------------

def _blob_rules(png: Path, cfg: Path | None, min_area: float | None) -> tuple[dict, str]:
    """[elements] rules for `segment.blobs` and where they came from."""
    if cfg is None:
        guess = png.resolve().parent.parent / "brand.toml"  # BRAND_DIR/source/x.png
        cfg = guess if guess.is_file() else None
    rules, origin = {}, "built-in defaults"
    if cfg is not None:
        rules = dict(tomllib.loads(Path(cfg).read_text()).get("elements", {}))
        origin = str(cfg)
    if min_area is not None:
        rules["area_floor"] = min_area
        origin += f", area floor {min_area} of the canvas (--min-area)"
    return rules, origin


def blob_overlay(rgba: np.ndarray, found: list, width: int = 1200) -> Image.Image:
    """The art on gray with each blob boxed and numbered (1-based, as `blobs` prints them)."""
    h, w = rgba.shape[:2]
    base = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    base.alpha_composite(Image.fromarray(rgba))
    scale = width / w
    base = base.resize((width, max(1, round(h * scale))), Image.LANCZOS)
    draw = ImageDraw.Draw(base)
    font = ImageFont.load_default(size=max(14, base.height // 40))
    hues = [(230, 40, 40), (40, 110, 230), (0, 160, 90), (200, 60, 200), (240, 150, 0)]
    for k, b in enumerate(found, start=1):
        color = (*hues[(k - 1) % len(hues)], 255)
        box = [round(v * scale) for v in b.bbox]
        draw.rectangle([box[0], box[1], box[2] - 1, box[3] - 1], outline=color, width=3)
        draw.text((box[0] + 4, box[1] + 2), str(k), font=font, fill=color,
                  stroke_width=2, stroke_fill=(255, 255, 255, 255))
    return base


def cmd_blobs(args) -> int:
    path = Path(args.png)
    if not path.is_file():
        return _fail(f"no such file: {path}")
    rgba = _read_rgba(path)
    try:
        rules, origin = _blob_rules(path, Path(args.config) if args.config else None,
                                    args.min_area)
        found = segment.blobs(rgba, rules)
    except (ValueError, tomllib.TOMLDecodeError) as e:
        return _fail(str(e))
    h, w = rgba.shape[:2]
    print(f"{path.name}: {w}x{h}, {len(found)} blob(s) at or above the area floor ({origin})")
    print("Fractions of the canvas; a region's center box must hold the blob's center.")
    print("  #       area  bbox [x0, y0, x1, y1]         center [x, y]   color")
    for k, b in enumerate(found, start=1):
        x0, y0, x1, y1 = b.bbox
        frac = f"[{x0 / w:.3f}, {y0 / h:.3f}, {x1 / w:.3f}, {y1 / h:.3f}]"
        print(f"{k:3d} {b.area:10d}  {frac:28s} [{b.center[0]:.3f}, {b.center[1]:.3f}]  "
              f"{b.color}")
    out = Path(args.out) if args.out else Path.cwd() / f"{path.stem}-blobs.png"
    blob_overlay(rgba, found).save(out)
    print(f"overlay: {out}")
    return 0


# --- init ------------------------------------------------------------------------------------

def cmd_init(args) -> int:
    brand_dir = Path(args.brand_dir)
    target = brand_dir / "brand.toml"
    if target.exists():
        return _fail(f"{target} already exists; not overwriting it")
    legacy = brand_dir / "tools" / "brand.toml"
    if legacy.exists():
        return _fail(f"{legacy} already exists; a new {target} would shadow it. Build this "
                     "folder as it is, or move that config to the top of the folder yourself")
    (brand_dir / "source").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE, target)
    if (brand_dir / "README.md").exists():
        print(f"warning: {brand_dir / 'README.md'} already exists; `build` will overwrite it")
    print(f"created {brand_dir / 'source'}/ (put the source PNGs here)")
    print(f"wrote {target} (from brand.example.toml; edit it for this logo)")
    return 0


# --- build -----------------------------------------------------------------------------------

def find_config(brand_dir: Path) -> Path | None:
    """BRAND_DIR/brand.toml, else BRAND_DIR/tools/brand.toml (a brand folder that keeps the
    pipeline in tools/), else None."""
    for cfg in (brand_dir / "brand.toml", brand_dir / "tools" / "brand.toml"):
        if cfg.is_file():
            return cfg
    return None


def cmd_build(args) -> int:
    brand_dir = Path(args.brand_dir).resolve()
    cfg = find_config(brand_dir)
    if cfg is None:
        return _fail(f"no brand.toml in {brand_dir} (or in its tools/); run `cli.py init` first")
    missing = deps.check_tools()
    if "chrome" in missing or "potrace" in missing:
        for name in missing:
            print(f"missing: {name}: install with {deps.INSTALL_HINTS[name]}", file=sys.stderr)
        return _fail("the build needs Chrome and potrace")
    try:
        brand = config.load_brand(brand_dir, cfg)
        assessment = assess.assess([v.source for v in brand.variants.values()])
        layout = config.layout_of(brand_dir, cfg)  # what the documents say about it
        # builds the outputs and writes the documents; changes nothing unless all of it succeeds
        result = pipeline_build.run(brand_dir, config=cfg, layout=layout, assessment=assessment)
    except RuntimeError as e:
        if "failed verification" in str(e):
            return _fail(f"{e}. The lockup misses the [verify] bar in {cfg}. The previous "
                         f"outputs were left untouched. {RAISE_TRACE}")
        return _fail(str(e))
    except (ValueError, tomllib.TOMLDecodeError) as e:
        return _fail(f"{e} (config: {cfg})")
    except UnidentifiedImageError as e:
        return _fail(f"a variant's source is not a raster image (use a PNG): {e}. {UNTOUCHED}")
    except OSError as e:  # after UnidentifiedImageError, which is an OSError too
        return _fail(f"the build failed: {e}. {UNTOUCHED}")
    except subprocess.TimeoutExpired as e:
        cmd = e.cmd[0] if isinstance(e.cmd, (list, tuple)) and e.cmd else e.cmd
        return _fail(f"{Path(str(cmd)).name or 'a tool'} timed out after {e.timeout} s; try "
                     f"again, or check that Chrome and potrace run. {UNTOUCHED}")
    except (KeyError, TypeError, AttributeError) as e:  # a table or key of the wrong shape
        return _fail(f"brand.toml has a missing or malformed table or key ({e!r}); compare it "
                     f"with brand.example.toml (config: {cfg})")

    print(f"config {cfg}")
    print(f"input graded {assessment.tier}")
    for name, r in result.verify.items():
        print(f"verify {name}: iou={r.iou:.4f} color_error={r.color_error:.2f} passed={r.passed}")
    for name, ratio in result.contrast.items():
        print(f"contrast {name}: outline on tile {ratio:.2f}:1")
    for note in result.notes:
        print(f"note: {note}")
    print(f"wrote {len(result.files)} files and 3 documents; read "
          f"{brand_dir / 'report' / 'conversion-report.md'}")
    return 0


# --- main ------------------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli.py", description="Convert raster logo art into a "
                                "logo package (SVG, PDF, PNG, favicons, icons).")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="report missing external tools").set_defaults(func=cmd_check)
    a = sub.add_parser("assess", help="grade the source art")
    a.add_argument("files", nargs="+", metavar="FILE")
    a.add_argument("--layered", action="store_true",
                   help="the files are per-element layers on one canvas (graded only: the "
                   "build needs one flat PNG per variant)")
    a.set_defaults(func=cmd_assess)
    c = sub.add_parser("colors", help="dominant opaque colors of a PNG")
    c.add_argument("png", metavar="PNG")
    c.add_argument("--n", type=int, default=12, help="how many colors to list (default 12)")
    c.set_defaults(func=cmd_colors)
    b = sub.add_parser("blobs", help="numbered opaque blobs of a PNG, with an overlay image")
    b.add_argument("png", metavar="PNG")
    b.add_argument("--out", help="overlay PNG path (default: <stem>-blobs.png in the current "
                   "folder)")
    b.add_argument("--config", help="brand.toml whose [elements] knobs to use (default: "
                   "../brand.toml from the PNG's folder, if present)")
    b.add_argument("--min-area", type=float, help="area floor as a fraction of the canvas area "
                   "(overrides the config)")
    b.set_defaults(func=cmd_blobs)
    i = sub.add_parser("init", help="start a brand folder")
    i.add_argument("brand_dir", metavar="BRAND_DIR")
    i.set_defaults(func=cmd_init)
    d = sub.add_parser("build", help="build, verify and document a brand folder")
    d.add_argument("brand_dir", metavar="BRAND_DIR")
    d.set_defaults(func=cmd_build)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
