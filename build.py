"""
Build script for Little Fish — packages into .exe files using PyInstaller.

Builds:
  - LittleFish.exe       (the desktop companion)
  - LittleFishLauncher.exe (the launcher/tray manager)

Usage:
    pip install pyinstaller
    python build.py           # build both
    python build.py fish      # build only the fish
    python build.py launcher  # build only the launcher
    python build.py release   # build both + create release zip
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent


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
        str(ROOT / "main.py"),
    ]
    print("Building Little Fish...")
    print(" ".join(cmd))
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
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print("\nDone! dist/LittleFishLauncher.exe")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target in ("all", "fish", "release"):
        build_fish()
    if target in ("all", "launcher", "release"):
        build_launcher()
    if target == "release":
        build_release_zip()

    if target == "all":
        print("\nBoth executables are in dist/")
    elif target == "release":
        print("\nRelease zip is in dist/")


def build_release_zip():
    """Create a release zip containing the exe files and supporting assets."""
    ver_file = ROOT / "version.json"
    version = "0.0.0"
    try:
        version = json.loads(ver_file.read_text(encoding="utf-8")).get("version", "0.0.0")
    except (OSError, json.JSONDecodeError):
        pass

    dist = ROOT / "dist"
    zip_name = dist / f"LittleFish-v{version}.zip"

    files_to_include = [
        (dist / "LittleFish.exe", "LittleFish.exe"),
        (dist / "LittleFishLauncher.exe", "LittleFishLauncher.exe"),
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


if __name__ == "__main__":
    main()
