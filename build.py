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
"""

import subprocess
import sys
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

    if target in ("all", "fish"):
        build_fish()
    if target in ("all", "launcher"):
        build_launcher()

    if target == "all":
        print("\nBoth executables are in dist/")


if __name__ == "__main__":
    main()
