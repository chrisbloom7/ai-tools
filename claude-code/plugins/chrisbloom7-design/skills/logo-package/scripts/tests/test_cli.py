"""The command line (cli.py) on synthetic art. Only the build tests need Chrome and potrace."""

import numpy as np
import pytest
from PIL import Image

import cli
from generic_brand import _art
from logo_pipeline import assess, deps, report

NEEDS_BUILD = pytest.mark.skipif(
    "chrome" in deps.check_tools() or "potrace" in deps.check_tools(),
    reason="Chrome and potrace are needed to build")
TEAL, ORANGE = (31, 138, 158), (240, 120, 30)


def _two_colors(path, side=200):
    """Left 3/4 teal, right 1/4 orange, with a little noise; a transparent strip at the top."""
    rng = np.random.default_rng(0)
    a = np.zeros((side, side, 4), np.uint8)
    a[20:, : side * 3 // 4] = (*TEAL, 255)
    a[20:, side * 3 // 4:] = (*ORANGE, 255)
    a[20:, :, :3] = np.clip(a[20:, :, :3].astype(int) + rng.integers(-3, 4, (side - 20, side, 3)),
                            0, 255)
    Image.fromarray(a).save(path)
    return path


# --- check -----------------------------------------------------------------------------------

def test_check_lists_each_missing_tool_with_its_install_hint(monkeypatch, capsys):
    monkeypatch.setattr(deps, "check_tools", lambda: ["chrome", "potrace"])
    assert cli.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "missing: chrome" in out and deps.ENV_CHROME in out
    assert "missing: potrace: install with brew install potrace" in out


def test_check_passes_when_nothing_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    assert cli.main(["check"]) == 0
    assert "all tools found" in capsys.readouterr().out


# --- assess ----------------------------------------------------------------------------------

def test_assess_prints_tier_facts_findings_upgrades_and_the_designer_ask(tmp_path, capsys):
    png = tmp_path / "logo.png"
    _art(600).save(png)
    assert cli.main(["assess", str(png)]) == 0
    out = capsys.readouterr().out
    assert "tier: limited" in out  # 600 px is under the Limited line
    assert "what to expect: Limited means web-size SVGs" in out
    assert "logo.png: 600x600, alpha yes" in out
    assert "Shortest side is 600 px" in out
    assert assess.LAYERS_UPGRADE in out
    assert f"designer ask: {report.DESIGNER_ASK}" in out


def test_assess_layered_flag_reaches_the_grader(tmp_path, capsys):
    png = tmp_path / "logo.png"
    _art(600).save(png)
    cli.main(["assess", "--layered", str(png)])
    assert "send per-element layers" not in capsys.readouterr().out


def test_assess_missing_file_fails(tmp_path, capsys):
    assert cli.main(["assess", str(tmp_path / "gone.png")]) == 1
    assert "no such file" in capsys.readouterr().err


# --- colors ----------------------------------------------------------------------------------

def test_dominant_colors_merge_noise_and_rank_by_share(tmp_path):
    rgba = np.asarray(Image.open(_two_colors(tmp_path / "x.png")).convert("RGBA"))
    colors = cli.dominant_colors(rgba)
    assert len(colors) == 2  # the noise does not split a color in two
    (c1, s1), (c2, s2) = colors
    assert s1 == pytest.approx(0.75, abs=0.01) and s2 == pytest.approx(0.25, abs=0.01)
    rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (c1, c2)]
    assert np.abs(np.subtract(rgb[0], TEAL)).max() <= 2
    assert np.abs(np.subtract(rgb[1], ORANGE)).max() <= 2


def test_colors_command_prints_hex_and_share(tmp_path, capsys):
    assert cli.main(["colors", str(_two_colors(tmp_path / "x.png")), "--n", "1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2 and lines[1].startswith("#") and "75.0%" in lines[1]


def test_colors_on_fully_transparent_art(tmp_path, capsys):
    Image.new("RGBA", (20, 20)).save(tmp_path / "empty.png")
    assert cli.main(["colors", str(tmp_path / "empty.png")]) == 0
    assert "no opaque pixels" in capsys.readouterr().out


# --- blobs -----------------------------------------------------------------------------------

def test_blobs_lists_centers_as_fractions_and_writes_a_numbered_overlay(tmp_path, capsys,
                                                                       monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "source").mkdir()
    png = tmp_path / "source" / "logo.png"
    _art(600).save(png)
    assert cli.main(["blobs", str(png)]) == 0
    out = capsys.readouterr().out
    assert "2 blob(s)" in out and "built-in defaults" in out
    rows = [line.split() for line in out.splitlines() if line.strip()[:1].isdigit()]
    assert [r[0] for r in rows] == ["1", "2"]
    # ring then bar; each center sits in the brand.example.toml region boxes (y < 0.6, y >= 0.6)
    centers = [float(r[-2].rstrip("]")) for r in rows]
    assert centers[0] < 0.6 <= centers[1]
    # the default overlay goes to the current folder, never into source/
    overlay = tmp_path / "logo-blobs.png"
    assert overlay.is_file() and Image.open(overlay).size == (1200, 1200)
    assert not (tmp_path / "source" / "logo-blobs.png").exists()


def test_blobs_matches_the_segmentation_and_honors_out_and_min_area(tmp_path, capsys):
    png = tmp_path / "logo.png"
    _art(600).save(png)
    found = cli.segment.blobs(np.asarray(Image.open(png).convert("RGBA")))
    assert len(found) == 2
    ring, bar = found
    assert ring.bbox[1] < bar.bbox[1]
    assert ring.center == pytest.approx(((ring.bbox[0] + ring.bbox[2]) / 1200,
                                         (ring.bbox[1] + ring.bbox[3]) / 1200))
    assert bar.color == "#f0781e"
    out = tmp_path / "elsewhere.png"
    assert cli.main(["blobs", str(png), "--out", str(out), "--min-area", "0.2"]) == 0
    text = capsys.readouterr().out
    assert "0 blob(s)" in text and "--min-area" in text  # both pieces are under 20% of the canvas
    assert out.is_file() and not (tmp_path / "logo-blobs.png").exists()


def test_blobs_reads_the_area_floor_from_the_brand_toml(tmp_path, capsys):
    (tmp_path / "source").mkdir()
    png = tmp_path / "source" / "logo.png"
    _art(600).save(png)
    (tmp_path / "brand.toml").write_text("[elements]\narea_floor = 0.2\n")
    cli.main(["blobs", str(png), "--out", str(tmp_path / "o.png")])
    out = capsys.readouterr().out
    assert "0 blob(s)" in out and str(tmp_path / "brand.toml") in out


# --- init ------------------------------------------------------------------------------------

def test_init_creates_source_and_the_example_config_and_never_overwrites(tmp_path, capsys):
    brand = tmp_path / "brand"
    assert cli.main(["init", str(brand)]) == 0
    assert (brand / "source").is_dir()
    assert (brand / "brand.toml").read_text() == cli.EXAMPLE.read_text()
    (brand / "brand.toml").write_text("mine")
    assert cli.main(["init", str(brand)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert (brand / "brand.toml").read_text() == "mine"


def test_init_refuses_a_folder_with_a_tools_brand_toml(tmp_path, capsys):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "brand.toml").write_text("mine")
    assert cli.main(["init", str(tmp_path)]) == 1
    assert "would shadow it" in capsys.readouterr().err
    assert not (tmp_path / "brand.toml").exists()


# --- build -----------------------------------------------------------------------------------

def test_build_config_lookup_prefers_the_brand_folder_then_tools(tmp_path):
    assert cli.find_config(tmp_path) is None
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "brand.toml").write_text("")
    assert cli.find_config(tmp_path) == tmp_path / "tools" / "brand.toml"
    (tmp_path / "brand.toml").write_text("")
    assert cli.find_config(tmp_path) == tmp_path / "brand.toml"


def test_build_without_a_config_fails_clearly(tmp_path, capsys):
    assert cli.main(["build", str(tmp_path)]) == 1
    assert "no brand.toml" in capsys.readouterr().err


def _example_brand(root):
    """`init`, then the synthetic ring-and-bar art at the example's source path."""
    assert cli.main(["init", str(root)]) == 0
    _art(600).save(root / "source" / "logo.png")
    return root


@pytest.mark.slow
@NEEDS_BUILD
def test_build_turns_the_example_config_into_a_verified_package(tmp_path, capsys):
    brand = _example_brand(tmp_path / "brand")
    assert cli.main(["build", str(brand)]) == 0
    out = capsys.readouterr().out
    assert "verify logo-stacked-default.svg" in out and "passed=True" in out
    for f in ("svg/logo-stacked-default.svg", "svg/icon-default.svg",
              "png/favicon-default.ico", "png/share-card-1200x630.png",
              "logo-package/pdf/logo-stacked-default.pdf", "logo-package/README.txt",
              "report/conversion-report.md", "README.md"):
        assert (brand / f).is_file(), f
    readme = (brand / "README.md").read_text()
    assert "# Example Logo brand assets" in readme
    # brand.toml sits at the top of the folder: the docs say cli.py build, never tools/
    docs = readme + (brand / "report/conversion-report.md").read_text()
    assert f"/cli.py build {brand.resolve()}" in readme and "`brand.toml`" in docs
    assert "tools/build.py" not in docs and "tools/brand.toml" not in docs


@pytest.mark.slow
@NEEDS_BUILD
def test_build_below_the_verify_bar_exits_nonzero_with_a_hint(tmp_path, capsys):
    brand = _example_brand(tmp_path / "brand")
    cfg = brand / "brand.toml"
    cfg.write_text(cfg.read_text().replace("iou_min = 0.98", "iou_min = 0.99999"))
    assert cli.main(["build", str(brand)]) == 1
    err = capsys.readouterr().err
    assert "failed verification" in err and "LOCKUP_TRACE" in err


MINIMAL = """
[brand]
name = "Shape Test"

[variants.default]
source = "source/logo.png"
tile = "#ffffff"
"""
FULL_TAIL = """
[elements]
outline = "teal"

[elements.palette]
teal = ["#1f8a9e"]

[elements.regions.all]
center = [0.0, 0.0, 1.0, 1.0]

[verify]
iou_min = 0.98
color_error_max = 8.0
"""


@pytest.mark.parametrize("text, missing", [
    (MINIMAL, "[elements] table"),
    (MINIMAL + FULL_TAIL.split("[verify]")[0], "[verify] table"),
    (MINIMAL + FULL_TAIL.replace('outline = "teal"', ""), "key outline in [elements]"),
    (MINIMAL + FULL_TAIL.replace("iou_min = 0.98", ""), "key iou_min in [verify]"),
    (MINIMAL + FULL_TAIL.replace("[elements.regions.all]", "[x]"), "[elements.regions] table"),
])
def test_build_with_a_missing_table_exits_1_with_its_name_and_keeps_outputs(
        tmp_path, capsys, monkeypatch, text, missing):
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    (tmp_path / "source").mkdir()
    Image.new("RGBA", (10, 10)).save(tmp_path / "source" / "logo.png")
    (tmp_path / "svg").mkdir()
    (tmp_path / "svg" / "old.svg").write_text("<svg/>")
    (tmp_path / "brand.toml").write_text(text)
    assert cli.main(["build", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert missing in err and "Traceback" not in err
    assert (tmp_path / "svg" / "old.svg").exists()  # failed before any work


def _brand_with_source(root, source_name="logo.png"):
    """A complete one-variant brand.toml whose source is `source/<source_name>`."""
    (root / "source").mkdir(exist_ok=True)
    text = (MINIMAL + FULL_TAIL).replace("source/logo.png", f"source/{source_name}")
    (root / "brand.toml").write_text(text)
    return root / "brand.toml"


def test_build_run_checks_tools_before_any_work(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "check_tools", lambda: ["potrace"])
    cfg = _brand_with_source(tmp_path)
    Image.new("RGBA", (10, 10)).save(tmp_path / "source" / "logo.png")
    for d in ("svg", "png", "logo-package"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "old.txt").write_text("keep")
    with pytest.raises(RuntimeError, match="missing potrace.*brew install potrace"):
        cli.pipeline_build.run(tmp_path, config=cfg)
    for d in ("svg", "png", "logo-package"):
        assert (tmp_path / d / "old.txt").read_text() == "keep"


def test_build_with_an_svg_source_fails_in_one_line(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    _brand_with_source(tmp_path, "logo.svg")
    (tmp_path / "source" / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
    assert cli.main(["build", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "not a raster image" in err and "Traceback" not in err


def test_build_tool_timeout_fails_in_one_line(tmp_path, capsys, monkeypatch):
    import subprocess
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    _brand_with_source(tmp_path)
    Image.new("RGBA", (10, 10)).save(tmp_path / "source" / "logo.png")

    def slow(*a, **kw):
        raise subprocess.TimeoutExpired(["/path/to/chrome", "--headless"], 60)
    monkeypatch.setattr(cli.pipeline_build, "run", slow)
    assert cli.main(["build", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "chrome timed out after 60 s" in err and "Traceback" not in err


def test_assess_a_file_that_is_not_an_image_fails_in_one_line(tmp_path, capsys):
    bad = tmp_path / "logo.png"
    bad.write_text("not a png")
    assert cli.main(["assess", str(bad)]) == 1
    assert "not a raster image" in capsys.readouterr().err


def test_init_warns_when_a_readme_exists(tmp_path, capsys):
    (tmp_path / "README.md").write_text("mine")
    assert cli.main(["init", str(tmp_path)]) == 0
    assert "build` will overwrite it" in capsys.readouterr().out
    assert (tmp_path / "README.md").read_text() == "mine"
