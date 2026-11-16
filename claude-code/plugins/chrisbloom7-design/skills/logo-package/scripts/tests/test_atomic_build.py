"""A build changes the brand folder only when it fully succeeds.

`build.run` builds every output and the three documents into a staging folder inside the brand
folder and swaps them into place at the end. A failed build (a lockup under the verify bar, an
exception mid-build, a failed swap) leaves the previous outputs exactly as they were. These tests
use the synthetic ring-and-bar brand at 600 px, each in its own folder.
"""

import os
import shutil

import pytest

import cli
from generic_brand import make_brand
from logo_pipeline import build, deps, render, segment

NEEDS_BUILD = pytest.mark.skipif(
    "chrome" in deps.check_tools() or "potrace" in deps.check_tools(),
    reason="Chrome and potrace are needed to build")
SIDE = 600

# What a previous build left: one file in every managed folder and the top-level README.md.
OLD = {"svg/old.svg": b"<svg>old</svg>",
       "png/old.png": b"old png bytes",
       "logo-package/old.txt": b"old package",
       "report/conversion-report.md": b"# old report\n",
       "README.md": b"# old readme\n"}
# What the user keeps in the brand folder besides the config and the sources.
USER_FILES = {"notes.txt": b"my notes\n"}


def _snapshot(root):
    """{relative path: bytes} of every file under `root`."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _brand(root, old=True, skill_layout=False):
    """The synthetic brand under `root`, with the previous build's files and a user file.
    Return the config path."""
    cfg = make_brand(root, SIDE)
    if skill_layout:  # brand.toml at the top of the folder, as `cli.py init` makes it
        top = root / "brand.toml"
        top.write_text(cfg.read_text())
        shutil.rmtree(root / "tools")
        cfg = top
    for rel, data in (OLD if old else {}).items() | USER_FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return cfg


def _leftovers(root):
    return sorted(p.name for p in root.iterdir() if p.name.startswith(".build-"))


@pytest.mark.slow
@NEEDS_BUILD
def test_a_lockup_that_fails_verification_leaves_the_previous_outputs(tmp_path, capsys):
    cfg = _brand(tmp_path)
    cfg.write_text(cfg.read_text().replace("iou_min = 0.98", "iou_min = 1.5"))  # impossible
    before = _snapshot(tmp_path)
    assert cli.main(["build", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "failed verification" in err and "left untouched" in err
    assert "deleted" not in err
    assert _snapshot(tmp_path) == before
    assert _leftovers(tmp_path) == []


@pytest.mark.slow
@NEEDS_BUILD
def test_an_exception_mid_build_leaves_the_previous_outputs(tmp_path, monkeypatch):
    cfg = _brand(tmp_path)
    before = _snapshot(tmp_path)

    def broken(*a, **kw):  # the PDFs are written late, for the handoff folder
        raise RuntimeError("pdf step broke")
    monkeypatch.setattr(render, "svg_to_pdf", broken)
    with pytest.raises(RuntimeError, match="pdf step broke"):
        build.run(tmp_path, config=cfg)
    assert _snapshot(tmp_path) == before
    assert _leftovers(tmp_path) == []


@pytest.mark.slow
@NEEDS_BUILD
def test_a_successful_build_replaces_the_outputs_and_keeps_the_user_files(tmp_path):
    cfg = _brand(tmp_path)
    keep = {rel: data for rel, data in _snapshot(tmp_path).items()
            if rel.split("/")[0] in ("source", "tools", "notes.txt")}
    res = build.run(tmp_path, config=cfg)
    after = _snapshot(tmp_path)
    for rel in OLD:  # every old file is gone or rewritten
        assert after.get(rel) != OLD[rel], rel
    assert "svg/logo-stacked-default.svg" in after and "logo-package/README.txt" in after
    assert "report/conversion-report.md" in after and "README.md" in after
    assert {rel: after[rel] for rel in keep} == keep  # source/, tools/brand.toml, notes.txt
    assert _leftovers(tmp_path) == []
    # the result names the files where they ended up, not in the staging folder
    homes = (tmp_path, tmp_path / "logo-package")
    assert res.files and all(p.is_file() and p.parent.parent in homes for p in res.files)


@pytest.mark.slow
@NEEDS_BUILD
def test_a_first_build_with_no_previous_outputs_works(tmp_path):
    cfg = _brand(tmp_path, old=False, skill_layout=True)
    build.run(tmp_path, config=cfg)
    assert (tmp_path / "svg/logo-stacked-default.svg").is_file()
    assert (tmp_path / "png/share-card-1200x630.png").is_file()
    assert (tmp_path / "logo-package/pdf/logo-stacked-default.pdf").is_file()
    assert (tmp_path / "notes.txt").read_bytes() == USER_FILES["notes.txt"]
    assert _leftovers(tmp_path) == []
    # the documents describe the brand folder, never the staging folder
    readme = (tmp_path / "README.md").read_text()
    assert ".build-" not in readme
    assert str(tmp_path.resolve()) in " ".join(readme.split())  # the rebuild command
    report = (tmp_path / "report/conversion-report.md").read_text()
    assert ".build-" not in report and "`source/ring-bar.png`" in readme


def test_stale_build_folders_from_a_crashed_run_are_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    cfg = _brand(tmp_path)
    for stale in (".build-staging-123", ".build-previous-456"):
        (tmp_path / stale / "svg").mkdir(parents=True)
        (tmp_path / stale / "svg" / "x.svg").write_text("<svg/>")

    def stop(*a, **kw):  # fail at the first build step, after the stale folders are cleared
        raise RuntimeError("stop here")
    monkeypatch.setattr(segment, "split_elements", stop)
    with pytest.raises(RuntimeError, match="stop here"):
        build.run(tmp_path, config=cfg)
    assert _leftovers(tmp_path) == []
    for rel, data in OLD.items():
        assert (tmp_path / rel).read_bytes() == data, rel


@pytest.mark.slow
@NEEDS_BUILD
# Five managed items exist, so renames 1 to 5 move the previous outputs aside and 6 to 10 move
# the new ones in: fail once in each phase.
@pytest.mark.parametrize("fail_at", [3, 7], ids=["moving-aside", "moving-in"])
def test_a_failed_swap_restores_the_previous_outputs(tmp_path, monkeypatch, fail_at):
    cfg = _brand(tmp_path)
    before = _snapshot(tmp_path)
    real = os.rename
    calls = []

    def flaky(src, dst, *a, **kw):
        if str(tmp_path) in str(src):  # count only the swap's own renames
            calls.append((src, dst))
            if len(calls) == fail_at:
                raise OSError("rename failed")
        return real(src, dst, *a, **kw)
    monkeypatch.setattr(os, "rename", flaky)
    with pytest.raises(OSError, match="rename failed"):
        build.run(tmp_path, config=cfg)
    assert _snapshot(tmp_path) == before
    assert _leftovers(tmp_path) == []
