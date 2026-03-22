"""
Little Fish — a living desktop companion.
Entry point: creates the application, loads config, shows the Fish.
"""

import os
import sys
import ctypes
import traceback
import threading
import faulthandler
from pathlib import Path

# ------------------------------------------------------------------
# When packaged with PyInstaller --windowed, sys.stdout/stderr are
# None (no console).  Redirect them to a log file so print(),
# faulthandler, and exception hooks don't crash.
# ------------------------------------------------------------------
if sys.stdout is None or sys.stderr is None:
    _log_dir = Path(os.environ.get("APPDATA", ".")) / "LittleFish"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = open(_log_dir / "littlefish.log", "a", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _log_file
    if sys.stderr is None:
        sys.stderr = _log_file

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

faulthandler.enable()  # Prints traceback on segfault/abort

from widget.fish_widget import FishWidget

ICO_PATH = Path(__file__).parent / "littlefish.ico"


# Global exception handlers — prevent silent crashes
def _global_except_hook(exc_type, exc_value, exc_tb):
    print(f"[UNHANDLED] {exc_type.__name__}: {exc_value}")
    traceback.print_exception(exc_type, exc_value, exc_tb)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

def _thread_except_hook(args):
    print(f"[THREAD CRASH] {args.exc_type.__name__}: {args.exc_value} in {args.thread}")
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

sys.excepthook = _global_except_hook
threading.excepthook = _thread_except_hook


def _already_running() -> bool:
    """Use a Windows named mutex to prevent duplicate instances."""
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.windll.kernel32
    mutex_name = "LittleFish_SingleInstance_Mutex"
    # CreateMutexW returns handle; GetLastError()==183 means already exists
    handle = kernel32.CreateMutexW(None, True, mutex_name)
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return True
    # Keep handle alive for process lifetime (leaked intentionally)
    return False


def main():
    if _already_running():
        print("Little Fish is already running!")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # keep running via tray

    if ICO_PATH.exists():
        app.setWindowIcon(QIcon(str(ICO_PATH)))

    # --- Onboarding (first launch) ---
    from core.user_profile import UserProfile
    profile = UserProfile()
    if not profile.is_onboarded:
        from core.onboarding import run_onboarding
        result = run_onboarding()
        if result:
            profile.complete_onboarding(
                age=result.get("age", 20),
                usage=result.get("usage", "general"),
                chronotype=result.get("chronotype", "normal"),
                talkativeness=result.get("talkativeness", "moderate"),
                fish_name=result.get("fish_name", "Little Fish"),
            )
        # If they skip/close, we proceed with defaults

    fish = FishWidget()
    fish.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
