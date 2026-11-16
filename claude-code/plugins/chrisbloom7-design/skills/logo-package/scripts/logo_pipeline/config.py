"""The logo's structure from brand.toml: its name, its variants and which element is the mark.

  from logo_pipeline import config
  brand = config.load_brand(Path("."))             # tools/brand.toml next to the package
  brand = config.load_brand(brand_dir, Path("x/brand.toml"))

`[brand]` holds `name` (required; for the docs), `mark_element` (optional: the element drawn
alone as the mark and on icons; without it the stacked lockup is used) and `share_card_variant`
(optional: defaults to the first variant). One `[variants.<name>]` table per variant, in
processing order, holds `source` (path relative to the brand folder), `mark_name` (file stem of
the mark: required when `mark_element` is set) and `tile` (#rrggbb icon and favicon tile
color), and optionally `background` (a word such as "light" or "dark": the docs say "use the
<variant> files on <background> backgrounds"). Unknown keys are errors, so a typo cannot
silently fall back to a default. When `[elements.regions]` is present, `mark_element` must
name one of its regions.

The optional `[report]` table holds `notes`: plain sentences about the art that the code cannot
measure (supplied by whoever knows the art). The report lists them under "Known limits of this
conversion" in report/conversion-report.md, and nowhere else.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
# The default config: brand.toml next to the package when there is one, else the commented
# brand.example.toml (whose [verify] and [elements] knobs are the shipped defaults). The build
# and the CLI always pass the brand's own brand.toml explicitly.
EXAMPLE = SCRIPTS / "brand.example.toml"
BRAND = SCRIPTS / "brand.toml" if (SCRIPTS / "brand.toml").is_file() else EXAMPLE

# Where a brand folder keeps its config, which decides what the documents say about it:
# "tools": BRAND_DIR/tools/brand.toml next to a copy of the pipeline (rebuilt with
# tools/build.py); "skill": BRAND_DIR/brand.toml, built by the logo-package skill's cli.py.
LAYOUT_TOOLS, LAYOUT_SKILL = "tools", "skill"


def layout_of(brand_dir: Path, config: Path) -> str:
    """LAYOUT_TOOLS when `config` is `brand_dir`/tools/brand.toml, else LAYOUT_SKILL."""
    tools = Path(brand_dir).resolve() / "tools" / "brand.toml"
    return LAYOUT_TOOLS if Path(config).resolve() == tools else LAYOUT_SKILL


BRAND_KEYS = {"name", "mark_element", "share_card_variant"}
VARIANT_KEYS = {"source", "mark_name", "tile", "background"}
REPORT_KEYS = {"notes"}
TILE = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class Variant:
    source: Path  # absolute: brand_dir / the configured path
    mark_name: str | None
    tile: str  # "#rrggbb" as written in brand.toml
    background: str | None = None  # "light", "dark", ...: what the variant is for


@dataclass(frozen=True)
class Brand:
    name: str
    mark_element: str | None
    share_card_variant: str
    variants: dict[str, Variant] = field(default_factory=dict)
    notes: tuple[str, ...] = ()  # [report] notes, in order


def load_brand(brand_dir: Path, config: Path | None = None) -> Brand:
    """The [brand] and [variants.*] tables of `config` (default: BRAND), validated.

    Sources resolve against `brand_dir` (the folder that holds source/), not the config's own
    folder. Raises ValueError with the offending table and key on any problem.
    """
    brand_dir = Path(brand_dir)
    data = tomllib.loads(Path(config or BRAND).read_text())
    head = dict(data.get("brand", {}))
    unknown = set(head) - BRAND_KEYS
    if unknown:
        raise ValueError(f"brand.toml [brand]: unknown key(s) {sorted(unknown)}")
    if not isinstance(head.get("name"), str) or not head["name"].strip():
        raise ValueError("brand.toml [brand]: missing name (the brand name the docs use)")
    tables = data.get("variants", {})
    if not tables:
        raise ValueError("brand.toml has no [variants.*] table; add one per variant, for example "
                         "[variants.default] with source and tile")
    mark_element = head.get("mark_element")
    regions = data.get("elements", {}).get("regions")
    if mark_element is not None and regions is not None and mark_element not in regions:
        raise ValueError(f"brand.toml [brand] mark_element {mark_element!r} is not one of the "
                         f"[elements.regions] {sorted(regions)}")

    variants, marks = {}, {}
    for name, t in tables.items():
        where = f"brand.toml [variants.{name}]"
        unknown = set(t) - VARIANT_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
        if "source" not in t:
            raise ValueError(f"{where}: missing source (the art file, relative to the brand "
                             "folder)")
        source = brand_dir / t["source"]
        if not source.is_file():
            raise ValueError(f"{where}: source file {source} does not exist")
        tile = t.get("tile")
        if not isinstance(tile, str) or not TILE.fullmatch(tile):
            raise ValueError(f"{where}: tile {tile!r} is not a #rrggbb color")
        mark_name = t.get("mark_name")
        if mark_element is not None and not mark_name:
            raise ValueError(f"{where}: missing mark_name (needed because [brand] mark_element "
                             "is set; it names the mark file, svg/mark-<mark_name>.svg)")
        if mark_name and mark_name in marks:
            raise ValueError(f"{where}: mark_name {mark_name!r} is also used by "
                             f"[variants.{marks[mark_name]}]; mark file names must differ")
        if mark_name:
            marks[mark_name] = name
        background = t.get("background")
        if background is not None and (not isinstance(background, str)
                                       or not background.strip()):
            raise ValueError(f"{where}: background {background!r} is not a word such as "
                             "\"light\" or \"dark\"")
        variants[name] = Variant(source, mark_name, tile, background)

    share = head.get("share_card_variant", next(iter(variants)))
    if share not in variants:
        raise ValueError(f"brand.toml [brand] share_card_variant {share!r} is not a variant "
                         f"(variants: {', '.join(variants)})")
    return Brand(head["name"], mark_element, share, variants, _notes(data))


# The tables and keys a build reads besides [brand] and [variants.*]: (table, key) pairs, where
# a key of None means the table itself.
REQUIRED = (("elements", None), ("elements", "palette"), ("elements", "regions"),
            ("elements", "outline"), ("verify", None), ("verify", "iou_min"),
            ("verify", "color_error_max"))


def check_tables(data: dict) -> None:
    """Raise ValueError naming the first table or key of REQUIRED that `data` (a parsed
    brand.toml) lacks, so a build fails before it does any work."""
    for table, key in REQUIRED:
        t = data.get(table)
        if not isinstance(t, dict):
            raise ValueError(f"brand.toml has no [{table}] table (see brand.example.toml)")
        if key is not None and key not in t:
            where = f"[{table}.{key}] table" if key in ("palette", "regions") else \
                f"key {key} in [{table}]"
            raise ValueError(f"brand.toml is missing the {where} (see brand.example.toml)")


def _notes(data: dict) -> tuple[str, ...]:
    """The validated `[report] notes` (empty when the table or the key is absent)."""
    table = data.get("report", {})
    if not isinstance(table, dict):
        raise ValueError("brand.toml [report] must be a table (with notes = [\"...\"])")
    unknown = set(table) - REPORT_KEYS
    if unknown:
        raise ValueError(f"brand.toml [report]: unknown key(s) {sorted(unknown)}")
    notes = table.get("notes", [])
    if not isinstance(notes, list):
        raise ValueError("brand.toml [report] notes must be a list of sentences, for example "
                         "notes = [\"The fine grain is not reproduced.\"]")
    for n in notes:
        if not isinstance(n, str):
            raise ValueError(f"brand.toml [report] notes: {n!r} is not a string")
        if not n.strip():
            raise ValueError("brand.toml [report] notes: an entry is empty")
    return tuple(notes)
