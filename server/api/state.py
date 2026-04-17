"""Shared API state and filesystem paths."""

from pathlib import Path

_FEEDBACK_DB_PATH = None

UI_DIR = Path("ui")
UI_DIST_DIR = UI_DIR / "dist"
UI_DIST_INDEX = UI_DIST_DIR / "index.html"
UI_DIST_ASSETS = UI_DIST_DIR / "assets"
