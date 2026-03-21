"""
Central path resolver for persistent config storage.

When running frozen (PyInstaller --onefile), `__file__` points to a temp
dir that is deleted on exit.  So we store settings.json in %APPDATA% next
to the other persistent data.  On first launch we copy the bundled
defaults there so the user starts with sane values.

Secrets (API keys, tokens) are stored in a SEPARATE file that is never
committed to the repo:  %APPDATA%/LittleFish/secrets.json
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


# ── Secrets (API keys / tokens — local only, never in repo) ───────────

def get_secrets_path() -> Path:
    """Path to the local-only secrets file (always in %APPDATA%, never in repo)."""
    return _appdata_dir() / "secrets.json"


def load_secrets() -> dict:
    """Load secrets from the local secrets file."""
    sp = get_secrets_path()
    if sp.exists():
        try:
            return json.loads(sp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_secrets(data: dict) -> None:
    """Write secrets to the local secrets file."""
    sp = get_secrets_path()
    sp.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_groq_keys() -> list[str]:
    """Return Groq API keys from local secrets."""
    return load_secrets().get("groq_keys", [])


def get_github_token() -> str:
    """Return GitHub personal access token from local secrets."""
    return load_secrets().get("github_token", "")


def migrate_secrets_from_settings() -> None:
    """One-time migration: move groq_keys/github_token from settings.json to secrets.json."""
    config_path = get_config_path()
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    secrets = load_secrets()
    changed = False

    # Migrate groq_keys
    keys = cfg.get("groq_keys", [])
    if keys and not secrets.get("groq_keys"):
        secrets["groq_keys"] = keys
        changed = True

    # Migrate github_token
    token = cfg.get("github_token", "")
    if token and not secrets.get("github_token"):
        secrets["github_token"] = token
        changed = True

    if changed:
        save_secrets(secrets)
        # Remove from settings.json so they're no longer in the repo-tracked file
        cfg.pop("groq_keys", None)
        cfg.pop("github_token", None)
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


CONFIG_PATH = get_config_path()

# Auto-migrate secrets on import
migrate_secrets_from_settings()
