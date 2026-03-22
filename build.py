"""
Build script for Little Fish — packages into .exe files using PyInstaller.

Builds:
  - LittleFish.exe       (the desktop companion)
  - LittleFishLauncher.exe (the launcher/tray manager)

Usage:
    python build.py              # build both exes
    python build.py fish         # build only the fish
    python build.py launcher     # build only the launcher
    python build.py release      # build both + create release zip
    python build.py publish      # release + create GitHub Release + upload zip
"""

import json
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
GITHUB_REPO = "LucaTommy/LittleFish"


def _get_version() -> str:
    try:
        return json.loads((ROOT / "version.json").read_text(encoding="utf-8")).get("version", "0.0.0")
    except (OSError, json.JSONDecodeError):
        return "0.0.0"


def clean_dist():
    """Remove old build artifacts from dist/, keeping only what we're about to produce."""
    if DIST.exists():
        for item in DIST.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except PermissionError:
                print(f"  Skipped locked file: {item.name}")
        print("Cleaned dist/")
    DIST.mkdir(exist_ok=True)


def build_fish():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "LittleFish",
        "--icon", str(ROOT / "littlefish.ico"),
        "--add-data", f"{ROOT / 'config' / 'settings.json'};config",
        "--add-data", f"{ROOT / 'config' / 'app_reactions.json'};config",
        "--add-data", f"{ROOT / 'version.json'};.",
        "--add-data", f"{ROOT / 'littlefish.ico'};.",
        "--hidden-import", "pyttsx3.drivers",
        "--hidden-import", "pyttsx3.drivers.sapi5",
        "--hidden-import", "pycaw",
        "--hidden-import", "pycaw.pycaw",
        "--hidden-import", "comtypes",
        "--hidden-import", "screen_brightness_control",
        "--hidden-import", "dateutil",
        "--hidden-import", "dateutil.parser",
        "--collect-all", "mss",
        "--hidden-import", "mss",
        "--hidden-import", "mss.base",
        "--hidden-import", "mss.factory",
        "--hidden-import", "mss.windows",
        "--hidden-import", "mss.models",
        "--hidden-import", "mss.screenshot",
        "--hidden-import", "mss.tools",
        "--hidden-import", "mss.exception",
        "--hidden-import", "vosk",
        "--hidden-import", "edge_tts",
        "--collect-all", "edge_tts",
        "--hidden-import", "aiohttp",
        "--hidden-import", "certifi",
        str(ROOT / "main.py"),
    ]
    print("Building Little Fish...")
    subprocess.run(cmd, check=True)
    print("\nDone! dist/LittleFish.exe")


def build_launcher():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "LittleFishLauncher",
        "--icon", str(ROOT / "littlefish.ico"),
        "--add-data", f"{ROOT / 'version.json'};.",
        "--add-data", f"{ROOT / 'config' / 'settings.json'};config",
        "--add-data", f"{ROOT / 'config' / 'app_reactions.json'};config",
        "--add-data", f"{ROOT / 'littlefish.ico'};.",
        str(ROOT / "launcher.py"),
    ]
    print("Building Little Fish Launcher...")
    subprocess.run(cmd, check=True)
    print("\nDone! dist/LittleFishLauncher.exe")


def build_release_zip() -> Path:
    """Create a release zip containing the exe files and supporting assets."""
    version = _get_version()
    zip_name = DIST / f"LittleFish-v{version}.zip"

    files_to_include = [
        (DIST / "LittleFish.exe", "LittleFish.exe"),
        (DIST / "LittleFishLauncher.exe", "LittleFishLauncher.exe"),
        (ROOT / "version.json", "version.json"),
        (ROOT / "littlefish.ico", "littlefish.ico"),
        (ROOT / "config" / "app_reactions.json", "config/app_reactions.json"),
        (ROOT / "config" / "settings.json", "config/settings.json"),
    ]

    print(f"Creating release zip: {zip_name.name}")
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc_name in files_to_include:
            if src.exists():
                zf.write(src, arc_name)
                print(f"  + {arc_name}")
            else:
                print(f"  ! MISSING: {src}")

    size_mb = zip_name.stat().st_size / (1024 * 1024)
    print(f"Done! {zip_name.name} ({size_mb:.1f} MB)")
    return zip_name


def publish():
    """Create a GitHub Release and upload the zip. Requires github_token in secrets."""
    # Read token from local secrets
    secrets_path = Path(__file__).parent / "config"
    # Use the same secrets infrastructure as the app
    sys.path.insert(0, str(ROOT))
    from config import get_github_token
    token = get_github_token()
    if not token:
        print("ERROR: No github_token found in secrets.json.")
        print("Add it via Settings > API Keys tab, or manually edit")
        print("  %APPDATA%/LittleFish/secrets.json")
        print('  {"github_token": "ghp_..."}')
        sys.exit(1)

    version = _get_version()
    tag = f"v{version}"
    zip_path = DIST / f"LittleFish-v{version}.zip"
    if not zip_path.exists():
        print(f"ERROR: {zip_path.name} not found. Run 'python build.py release' first.")
        sys.exit(1)

    print(f"\nPublishing {tag} to GitHub...")

    # 1. Create the release
    release_data = json.dumps({
        "tag_name": tag,
        "name": f"Little Fish {tag}",
        "body": f"Little Fish {tag}\n\nBuilt locally.",
        "draft": False,
        "prerelease": False,
    }).encode()

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    req = urllib.request.Request(url, data=release_data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            release = json.loads(resp.read())
        print(f"  Created release: {release['html_url']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "already_exists" in body:
            # Release exists — find it and use its upload URL
            print(f"  Release {tag} already exists, uploading asset to it...")
            get_req = urllib.request.Request(
                f"{url}/tags/{tag}",
                headers=headers,
            )
            with urllib.request.urlopen(get_req) as resp:
                release = json.loads(resp.read())
        else:
            print(f"  ERROR creating release: {e.code} {body[:200]}")
            sys.exit(1)

    # 2. Upload the zip asset
    upload_url = release["upload_url"].replace("{?name,label}", "")
    asset_name = zip_path.name
    upload_url += f"?name={asset_name}"

    zip_data = zip_path.read_bytes()
    upload_headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/zip",
        "Content-Length": str(len(zip_data)),
    }
    upload_req = urllib.request.Request(upload_url, data=zip_data, headers=upload_headers, method="POST")
    try:
        with urllib.request.urlopen(upload_req) as resp:
            asset = json.loads(resp.read())
        size_mb = asset["size"] / (1024 * 1024)
        print(f"  Uploaded {asset['name']} ({size_mb:.1f} MB)")
        print(f"\nPublished! {release['html_url']}")
    except urllib.error.HTTPError as e:
        print(f"  ERROR uploading asset: {e.code} {e.read().decode()[:200]}")
        sys.exit(1)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target in ("all", "fish", "release", "publish"):
        clean_dist()
        build_fish()
    if target in ("all", "launcher", "release", "publish"):
        build_launcher()
    if target in ("release", "publish"):
        build_release_zip()
    if target == "publish":
        publish()

    if target == "all":
        print("\nBoth executables are in dist/")
    elif target == "release":
        print("\nRelease zip is in dist/")

    # Final summary: show what's in dist
    print("\ndist/ contents:")
    for f in sorted(DIST.iterdir()):
        if f.is_file():
            mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.name:30s} {mb:6.1f} MB")


if __name__ == "__main__":
    main()
