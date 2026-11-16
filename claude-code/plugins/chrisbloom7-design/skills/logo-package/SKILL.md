---
name: logo-package
description: Convert raster logo art (PNG) into a brand asset package - traced SVG lockups and marks, vector PDFs, PNG exports, favicons and app icons, with a conversion report - using bundled Python scripts. Use ONLY when the user asks to convert or vectorize a raster logo, or to build a logo or brand asset package (SVG, PDF, PNG, favicons, icons) from existing logo art. It does not design, redraw, restyle or clean up logos. Not for resizing images, and not for making a favicon or icon from an existing SVG or other vector file. Requires uv, potrace and Google Chrome.
compatibility: Requires uv, potrace and Google Chrome (or Chromium via LOGO_PIPELINE_CHROME). Tested on macOS; Linux is untested; Windows is unsupported.
---

# Logo package

Turn a designer's raster logo art into a website-ready package: minified SVGs, vector PDFs, PNG
exports, favicons and app icons, plus three documents. The pipeline traces the art and fills it
with colors (and vertical gradients) sampled from the art itself. It never changes the art.

## Scripts

Everything runs through `cli.py` in the `scripts/` folder beside this SKILL.md (this skill's
base directory). Define a shell function with that folder's absolute path (works in zsh and
bash), then call it as `logo <command> ...`; every example below uses it:

```bash
logo() { uv run --project "<scripts dir>" python "<scripts dir>/cli.py" "$@"; }
logo check
```

If `logo` is not found in a later command (each shell call can start fresh), redefine it in the
same command. The first run installs the pinned Python dependencies (Pillow, numpy, scipy) into
`<scripts dir>/.venv`, and may first download CPython 3.13 (`pyproject.toml` requires 3.13 or
newer). Commands: `check`, `assess`, `colors`, `blobs`, `init`, `build`. Each has
`--help`. The config format is documented, key by key, in `<scripts dir>/brand.example.toml`.

## Prerequisites

- `uv` and `potrace`: `brew install uv potrace`. If `command -v uv` prints nothing, nothing
  else runs: install uv first (`brew install uv`).
- Google Chrome (headless, for rendering PNGs and PDFs): install it from google.com, or set
  `LOGO_PIPELINE_CHROME` to a Chrome or Chromium binary.
- macOS is the tested platform. Linux is untested (Chrome or Chromium is found on `PATH` or
  via `LOGO_PIPELINE_CHROME`; install hints are for Homebrew, so use your package manager).
  Windows is unsupported.

Run `logo check` first. If anything is missing, stop and show the user the install commands it
prints. Install nothing yourself.

## Input: tiers are a baseline, not a gate

The preflight (`assess`) grades the input and always proceeds. Tell the user the tier and what
to expect before building:

| Tier | Typical input | What to expect |
|---|---|---|
| Best | Per-element PNG layers at 3000 px or more on one canvas (or real vector art) | Keep and hand on the originals; a vector original needs no tracing. The build still needs one flat export per variant and outputs no per-element files |
| Good | Flat transparent PNGs, 2400 px or more | Full package; the layer split is inferred, so some roughness at halos and overlaps |
| Limited | Under about 2000 px, lossy (JPEG) or no transparency | Web-size SVGs and favicons are fine; print-grade output is not reliable |

For each gap, `assess` names the upgrade to ask for. Pass the designer ask it prints on to the
user verbatim:

> Please send transparent PNGs at 3000 px or more, one per variant, ideally one per element on
> the same canvas, plus any vector or layered originals you have.

Real vector originals (SVG, or a PDF with real paths) are better than any trace: say so, and
suggest using them directly. A PDF that only wraps a bitmap is flagged, not traced.

## Workflow

1. **Check tools:** `logo check`.
2. **Start a brand folder** (outside any public repo; see Rules): `logo init <brand_dir>`. It
   creates `<brand_dir>/source/` and `<brand_dir>/brand.toml` from the example, and never
   overwrites an existing `brand.toml`.
3. **Add the art:** copy the user's PNGs into `<brand_dir>/source/`, unchanged. The build
   traces ONE flat PNG per variant (for example a light and a dark version), ideally all on the
   same canvas size. If the user has per-element layers or vector originals, keep them as the
   masters and hand them on, but give the build a flat export (or flattened composite) per
   variant.
4. **Assess:** `logo assess <brand_dir>/source/*.png` (to grade per-element layer files, run
   it on them with `--layered`; the build does not use them). Report the tier, the findings and
   the designer ask.
5. **Write `brand.toml`** for this logo (read the comments in it):
   - `[brand] name`; one `[variants.<name>]` per PNG with `source` and a `tile` color.
   - `mark_element` (plus a `mark_name` per variant) only if the logo has a symbol that stands
     alone; otherwise leave it out and the icons use the whole lockup.
   - `[elements.palette]`: run `logo colors <png>` and turn the dominant colors into anchors.
     For a gradient, `colors` lists mid-ramp colors: sample the top and bottom of the shape
     and give the entry those two END colors as its ramp anchors.
   - The outline: `[elements] outline = "<palette entry name>"`, a key under `[elements]`
     whose value names a palette entry.
   - `[elements.regions.*]`: run `logo blobs <png>` (it writes a numbered overlay,
     `<stem>-blobs.png`, to the current folder, or to `--out`), look at the overlay, and draw
     `center` boxes (canvas fractions) so every blob's center falls in exactly one box. A
     shape enclosed by another (a star inside a circle) or touching it is ONE blob: model it
     as a palette color of the enclosing element, not as its own region.
   - Keep `[verify]` at `iou_min = 0.98` and `color_error_max = 8.0` unless the user decides
     otherwise.
6. **Build:** `logo build <brand_dir>`. It assesses, builds every output, verifies each lockup
   against its source and writes the documents. It exits nonzero when a lockup misses the bar.
   The build changes no output until all of it has succeeded, so a failed build leaves the
   previous outputs and documents exactly as they were (it only clears its own leftover
   `.build-staging-<pid>/` and `.build-discard-<pid>/` folders): fix the config and rebuild.
   If a build is killed while swapping, or cannot undo a failed swap, it leaves
   `.build-previous-<pid>/` holding the earlier outputs, and every later build refuses to
   start until you move its contents back into the brand folder or delete it.
7. **Review before claiming anything:** read `report/conversion-report.md` (tier, verify
   numbers, dropped pieces, what was traced flat or with gradients). Then open and look at the
   key files next to the sources: `png/logo-stacked-<variant>-1200.png`,
   `png/icon-<variant>-512.png`, the favicons at 16 and 32 px and the share card. Compare
   shapes and colors with the source by eye. Do not call the result faithful until you have
   viewed them.
8. **Iterate:** fix `brand.toml` (regions, palette, tile colors, `[report] notes` for limits
   only a person can see, such as lost texture) and build again. Show the user the outputs and
   the open choices (tile colors, which variant goes on the share card).

## What is delivered

```
<brand_dir>/
├── brand.toml                 # the config (yours to edit)
├── source/                    # the original PNGs, untouched
├── svg/                       # minified lockups, marks, icons
├── png/                       # lockups, email headers, share card, icons, favicons, .ico
├── report/
│   └── conversion-report.md   # tier, findings, verify numbers, what to ask the designer
├── README.md                  # inventory and usage rules, for the brand owner and agents
└── logo-package/              # self-contained handoff folder
    ├── README.txt             # plain-language guide: which file for which job
    └── svg/  pdf/  png/       # the PDFs exist only here, in logo-package/pdf/
```

A successful build replaces `svg/`, `png/`, `logo-package/`, `README.md` and
`report/conversion-report.md`, each as a whole; a failed one leaves them as they were (see step
6). Everything else in the brand folder (`source/`, `brand.toml`, your own files, including any
other file in `report/`) is never touched. The build stages its work in a hidden
`.build-staging-<pid>/` folder inside the brand folder and removes it when done. A managed
folder that is a symlink is replaced by a real folder (the link's target is left alone), and
a managed folder that is a mount point cannot be built into. The generated `README.md` gives
the owner the full rebuild command.

## Rules

- Never alter the art: no color shifts, added outlines, effects or "cleanup". Ask the designer
  for new art instead.
- No one-color (white or black) versions and no CMYK, EPS or AI output. RGB only; for print or
  large-format work, point the user to the designer's originals.
- The user's logo art is private client work. Never commit the source art, the outputs or a
  brand's `brand.toml` to a public repo, and never paste them into public issues or examples.
- Keep every `.md` you write Macdown-safe: no hard-wrapped line may start with `#` (escape
  issue numbers as `\#`). Check with `rg -n '^\s*#\d' <file>`.

## Troubleshooting

- **A lockup fails verification** (IoU below `iou_min` or color error above the cap): look at
  the outputs first. Raise the trace scale (`[compose] LOCKUP_TRACE = { up = ... }`, above the
  default 1200 / longer side) for small or detailed art, or fix the regions and palette so each
  piece gets the right colors. Change the bar only with the user's agreement.
- **Straight edges and sharp corners look slightly soft** (geometric logos): the trace rounds
  them a little. Under `[compose]`, lower `alpha` (potrace's corner threshold, default 1.1)
  and `sigma` (the pre-trace blur, default 1.5 x longer side / 2400) or raise `up`, for example
  `LOCKUP_TRACE = { alpha = 0.8 }`, then rebuild and look again. The verify scores average the
  whole lockup, so a small misshaped or wrongly colored piece barely moves them: always look at
  the outputs.
- **"element ... no component of the art has its bbox center in the region"**: a required
  element is missing. Rerun `logo blobs`, widen or move that region's `center` box, or set
  `optional = true` on it if the variant truly lacks it.
- **"no element rule matches the component"** or **"matches several regions"**: a blob's
  center falls in no box or in two; adjust the boxes so they cover every blob without
  overlapping. A real piece dropped as a speck means `area_floor` is too high.
- **Chrome or potrace missing**: `logo check` prints the install command. For Chromium or a
  nonstandard Chrome path, set `LOGO_PIPELINE_CHROME`.
