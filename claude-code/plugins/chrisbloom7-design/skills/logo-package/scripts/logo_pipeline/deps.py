"""Check that the external tools the pipeline shells out to are installed."""

import os
import shutil

ENV_CHROME = "LOGO_PIPELINE_CHROME"
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_chrome() -> str | None:
    """Path of the Chrome/Chromium to drive, or None when there is none.

    Order: $LOGO_PIPELINE_CHROME (when set it must exist: a bad path is not silently replaced),
    the macOS app, then the first of CHROME_NAMES on PATH.
    """
    env = os.environ.get(ENV_CHROME)
    if env:
        return env if _executable(env) else None
    if _executable(MAC_CHROME):
        return MAC_CHROME
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


CHROME = find_chrome()

INSTALL_HINTS: dict[str, str] = {
    "chrome": ("brew install --cask google-chrome "
               f"(or set {ENV_CHROME} to a Chrome or Chromium binary)"),
    "potrace": "brew install potrace",
    "uv": "brew install uv",
}


def check_tools() -> list[str]:
    """Return names of missing required tools, in order: chrome, potrace, uv."""
    missing = []
    if CHROME is None or not _executable(CHROME):
        missing.append("chrome")
    for name in ("potrace", "uv"):
        if shutil.which(name) is None:
            missing.append(name)
    return missing
