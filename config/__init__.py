"""
Central path resolver for persistent config storage.

When running frozen (PyInstaller --onefile), `__file__` points to a temp
dir that is deleted on exit.  So we store settings.json in %APPDATA% next
to the other persistent data.  On first launch we copy the bundled
defaults there so the user starts with sane values.
"""

import json
import os
import shutil
import sys
from pathlib import Path


def _appdata_dir() -> Path:
    """Persistent per-user storage folder (same as emotion_engine etc.)."""
    appdata = os.environ.get("APPDATA", "")
    base = Path(appdata) / "LittleFish" if appdata else Path.home() / ".littlefish"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _bundled_settings() -> Path:
    """Path to the settings.json that ships inside the bundle / source tree."""
    if getattr(sys, "frozen", False):
        # PyInstaller: extracted to _MEIPASS (onefile) or next to exe (onedir)
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent.parent
    return base / "config" / "settings.json"


def get_config_path() -> Path:
    """
    The ONE canonical place settings.json is read from *and* written to.

    Development mode  → <project>/config/settings.json  (editable in repo)
    Frozen mode       → %APPDATA%/LittleFish/settings.json  (persistent)
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).parent / "settings.json"

    target = _appdata_dir() / "settings.json"
    if not target.exists():
        # First launch after install → copy bundled defaults
        bundled = _bundled_settings()
        if bundled.exists():
            shutil.copy2(bundled, target)
        else:
            # Write minimal defaults
            target.write_text(json.dumps({
                "appearance": {"size": 80, "opacity": 1.0,
                               "position": [100, 100], "always_on_top": True},
            }, indent=2), encoding="utf-8")
    return target


CONFIG_PATH = get_config_path()
