from logo_pipeline import deps


def test_check_tools_reports_missing(monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(deps, "CHROME", "/nonexistent/chrome")
    assert deps.check_tools() == ["chrome", "potrace", "uv"]


def test_check_tools_all_present():
    assert deps.check_tools() == []


def test_install_hints_cover_all_tools():
    assert set(deps.INSTALL_HINTS) == {"chrome", "potrace", "uv"}
    assert deps.INSTALL_HINTS["uv"] == "brew install uv"


def _fake_exe(tmp_path, name="chrome-bin"):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return str(p)


def test_env_var_wins_over_everything(tmp_path, monkeypatch):
    exe = _fake_exe(tmp_path)
    monkeypatch.setenv("LOGO_PIPELINE_CHROME", exe)
    monkeypatch.setattr(deps, "MAC_CHROME", _fake_exe(tmp_path, "mac"))
    monkeypatch.setattr(deps.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert deps.find_chrome() == exe


def test_nonexistent_env_path_is_reported_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGO_PIPELINE_CHROME", str(tmp_path / "nope"))
    monkeypatch.setattr(deps, "MAC_CHROME", _fake_exe(tmp_path, "mac"))  # not a fallback here
    monkeypatch.setattr(deps.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert deps.find_chrome() is None
    monkeypatch.setattr(deps, "CHROME", deps.find_chrome())
    assert "chrome" in deps.check_tools()


def test_macos_app_comes_before_path_lookup(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGO_PIPELINE_CHROME", raising=False)
    mac = _fake_exe(tmp_path, "mac")
    monkeypatch.setattr(deps, "MAC_CHROME", mac)
    monkeypatch.setattr(deps.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert deps.find_chrome() == mac


def test_path_lookup_order_when_there_is_no_macos_app(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGO_PIPELINE_CHROME", raising=False)
    monkeypatch.setattr(deps, "MAC_CHROME", str(tmp_path / "none"))
    asked = []

    def which(name):
        asked.append(name)
        return "/usr/bin/chromium" if name == "chromium" else None

    monkeypatch.setattr(deps.shutil, "which", which)
    assert deps.find_chrome() == "/usr/bin/chromium"
    assert asked == ["google-chrome", "google-chrome-stable", "chromium"]


def test_none_found_means_chrome_is_none_and_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGO_PIPELINE_CHROME", raising=False)
    monkeypatch.setattr(deps, "MAC_CHROME", str(tmp_path / "none"))
    monkeypatch.setattr(deps.shutil, "which", lambda n: None)
    assert deps.find_chrome() is None
    monkeypatch.setattr(deps, "CHROME", None)
    assert deps.check_tools()[0] == "chrome"


def test_chrome_hint_mentions_the_env_var():
    assert "LOGO_PIPELINE_CHROME" in deps.INSTALL_HINTS["chrome"]
    assert "brew install --cask google-chrome" in deps.INSTALL_HINTS["chrome"]
