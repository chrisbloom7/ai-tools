"""A build changes the brand folder only when it fully succeeds.

`build.run` builds every output and the three documents into a staging folder inside the brand
folder and swaps them into place at the end. A failed build (a lockup under the verify bar, an
exception mid-build, a failed swap) leaves the previous outputs exactly as they were. These tests
use the synthetic ring-and-bar brand at 600 px, each in its own folder.
"""

import errno
import os
import re
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
# The user's own files inside report/: only report/conversion-report.md is the build's.
USER_REPORT = {"report/my-notes.md": b"# my notes on the report\n",
               "report/old-debug.png": b"debug image bytes"}
OURS = re.compile(r"\.build-(staging|previous|discard)-\d+")


def _snapshot(root):
    """{relative path: bytes, or "dir" for a folder} of everything under `root`."""
    return {p.relative_to(root).as_posix(): "dir" if p.is_dir() else p.read_bytes()
            for p in sorted(root.rglob("*"))}


def _brand(root, old=True, skill_layout=False):
    """The synthetic brand under `root`, with the previous build's files and a user file.
    Return the config path."""
    cfg = make_brand(root, SIDE)
    if skill_layout:  # brand.toml at the top of the folder, as `cli.py init` makes it
        top = root / "brand.toml"
        top.write_text(cfg.read_text())
        shutil.rmtree(root / "tools")
        cfg = top
    for rel, data in ({**OLD, **USER_REPORT} if old else {}).items() | USER_FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return cfg


def _leftovers(root):
    return sorted(p.name for p in root.iterdir() if OURS.fullmatch(p.name))


def _stop(monkeypatch):
    """Make the first build step fail, so a test that never reaches the swap stays fast."""
    def stop(*a, **kw):
        raise RuntimeError("stop here")
    monkeypatch.setattr(segment, "split_elements", stop)


def _flaky_rename(monkeypatch, root, fail_at, after=False):
    """Make the `fail_at`-th rename under `root` (1-based; an int or a set) fail: raise
    OSError before renaming, or with `after`, rename and then raise KeyboardInterrupt (an
    interrupt between a rename and whatever the code does next). Return the list of calls."""
    real, calls = os.rename, []
    at = {fail_at} if isinstance(fail_at, int) else set(fail_at)

    def flaky(src, dst, *a, **kw):
        if str(root) in str(src):  # count only the swap's own renames
            calls.append((src, dst))
            if len(calls) in at:
                if after:
                    real(src, dst, *a, **kw)
                    raise KeyboardInterrupt
                raise OSError(errno.EBUSY, "rename failed")
        return real(src, dst, *a, **kw)
    monkeypatch.setattr(os, "rename", flaky)
    return calls


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
            if rel.split("/")[0] in ("source", "tools", "notes.txt") or rel in USER_REPORT}
    res = build.run(tmp_path, config=cfg)
    after = _snapshot(tmp_path)
    for rel in OLD:  # every old file is gone or rewritten
        assert after.get(rel) != OLD[rel], rel
    assert "svg/logo-stacked-default.svg" in after and "logo-package/README.txt" in after
    assert "report/conversion-report.md" in after and "README.md" in after
    # source/, tools/brand.toml, notes.txt and the user's own files in report/
    assert {rel: after.get(rel) for rel in keep} == keep
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


@pytest.mark.slow
@NEEDS_BUILD
def test_a_failed_first_build_leaves_no_report_folder(tmp_path, monkeypatch):
    cfg = _brand(tmp_path, old=False)
    before = _snapshot(tmp_path)
    _flaky_rename(monkeypatch, tmp_path, 5)  # the last item moved in: the report
    with pytest.raises(OSError, match="rename failed"):
        build.run(tmp_path, config=cfg)
    assert _snapshot(tmp_path) == before  # no report/ (or any output) left behind
    assert _leftovers(tmp_path) == []


def test_stale_staging_and_discard_folders_from_a_crashed_run_are_removed(tmp_path,
                                                                          monkeypatch):
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    cfg = _brand(tmp_path)
    for stale in (".build-staging-123", ".build-discard-456"):
        (tmp_path / stale / "svg").mkdir(parents=True)
        (tmp_path / stale / "svg" / "x.svg").write_text("<svg/>")
    _stop(monkeypatch)  # fail at the first build step, after the stale folders are cleared
    with pytest.raises(RuntimeError, match="stop here"):
        build.run(tmp_path, config=cfg)
    assert _leftovers(tmp_path) == []
    for rel, data in OLD.items():
        assert (tmp_path / rel).read_bytes() == data, rel


def test_a_build_refuses_to_start_while_an_interrupted_swap_holds_the_old_outputs(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    _brand(tmp_path)
    held = tmp_path / ".build-previous-456"
    (held / "svg").mkdir(parents=True)
    (held / "svg" / "only-copy.svg").write_text("<svg>only copy</svg>")
    (tmp_path / ".build-staging-456").mkdir()  # the same crash also left its staging folder
    before = _snapshot(tmp_path)
    _stop(monkeypatch)
    assert cli.main(["build", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "A previous build was interrupted and left" in err and str(held) in err
    assert "Move its contents back into the brand folder, or delete it" in err
    assert "Traceback" not in err and "stop here" not in err
    assert _snapshot(tmp_path) == before  # nothing touched, not even the stale staging folder


def test_names_that_only_look_like_build_folders_are_never_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "check_tools", lambda: [])
    cfg = _brand(tmp_path)
    for name in (".build-previous-123.bak", ".build-staging-old", ".build-discard-1-mine"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "keep.txt").write_text("mine")
    before = _snapshot(tmp_path)
    _stop(monkeypatch)
    with pytest.raises(RuntimeError, match="stop here"):  # not refused
        build.run(tmp_path, config=cfg)
    assert _snapshot(tmp_path) == before


@pytest.mark.slow
@NEEDS_BUILD
# Five managed items exist, so renames 1 to 5 move the previous outputs aside and 6 to 10 move
# the new ones in: fail once in each phase, either before a rename (OSError) or right after one
# (an interrupt the code has not yet seen the result of).
@pytest.mark.parametrize("fail_at, after", [(3, False), (7, False), (2, True), (8, True)],
                         ids=["moving-aside", "moving-in", "interrupt-aside", "interrupt-in"])
def test_a_failed_swap_restores_the_previous_outputs(tmp_path, monkeypatch, fail_at, after):
    cfg = _brand(tmp_path)
    before = _snapshot(tmp_path)
    _flaky_rename(monkeypatch, tmp_path, fail_at, after)
    with pytest.raises(KeyboardInterrupt if after else OSError):
        build.run(tmp_path, config=cfg)
    assert _snapshot(tmp_path) == before
    assert _leftovers(tmp_path) == []


@pytest.mark.slow
@NEEDS_BUILD
def test_a_swap_failure_the_cli_reports_in_one_line(tmp_path, monkeypatch, capsys):
    _brand(tmp_path)
    before = _snapshot(tmp_path)
    _flaky_rename(monkeypatch, tmp_path, 1)
    assert cli.main(["build", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "rename failed" in err and "left untouched" in err and "Traceback" not in err
    assert _snapshot(tmp_path) == before
    assert _leftovers(tmp_path) == []


@pytest.mark.slow
@NEEDS_BUILD
def test_a_failed_rollback_keeps_the_old_outputs_and_the_next_build_refuses(
        tmp_path, monkeypatch, capsys):
    _brand(tmp_path)
    old_outputs = {rel: data for rel, data in _snapshot(tmp_path).items() if rel in OLD}
    # rename 3 (moving aside) fails, and so does rename 4: the first rename of the rollback
    calls = _flaky_rename(monkeypatch, tmp_path, {3, 4})
    assert cli.main(["build", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    held = tmp_path / f".build-previous-{os.getpid()}"
    assert str(held) in err and "keeps your earlier outputs" in err
    assert "refuse to start" in err and "Traceback" not in err
    stuck = calls[3][0]  # what the failed rollback rename tried to put back
    rel = stuck.relative_to(held).as_posix()
    assert (held / rel).exists() and not (tmp_path / rel).exists()
    # between the brand folder and the held folder, every old output still exists
    for name, data in old_outputs.items():
        here = tmp_path / name
        assert (here if here.exists() else held / name).read_bytes() == data, name
    held_before = _snapshot(held)

    monkeypatch.undo()  # renames work again; the next build must still refuse
    with pytest.raises(RuntimeError, match="A previous build was interrupted"):
        build.run(tmp_path, config=tmp_path / "tools" / "brand.toml")
    assert _snapshot(held) == held_before
