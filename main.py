import sys
import os
from pathlib import Path

# Always log to file for debugging (especially important for .exe where console is hidden)
_log_dir = Path(os.environ.get('APPDATA', str(Path.home()))) / 'LittleFish'
_log_dir.mkdir(parents=True, exist_ok=True)

class _TeeWriter:
    """Write to both the original stream and a log file."""
    def __init__(self, original, log_path):
        self._original = original
        self._log = open(log_path, 'w', encoding='utf-8', errors='replace', buffering=1)
    def write(self, s):
        if self._original is not None:
            try:
                self._original.write(s)
            except Exception:
                pass
        try:
            self._log.write(s)
        except Exception:
            pass
    def flush(self):
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass
        try:
            self._log.flush()
        except Exception:
            pass

sys.stdout = _TeeWriter(sys.stdout, _log_dir / 'debug.log')
sys.stderr = _TeeWriter(sys.stderr, _log_dir / 'debug_err.log')

"""
Little Fish — a living desktop companion.
Entry point: creates the application, loads config, shows the Fish.
"""

import ctypes
import traceback
import threading
import faulthandler

faulthandler.enable()  # Prints traceback on segfault/abort

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from widget.fish_widget import FishWidget

ICO_PATH = Path(__file__).parent / "littlefish.ico"


# Global exception handlers — prevent silent crashes
def _global_except_hook(exc_type, exc_value, exc_tb):
    try:
        print(f"[UNHANDLED] {exc_type.__name__}: {exc_value}")
        traceback.print_exception(exc_type, exc_value, exc_tb)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

def _thread_except_hook(args):
    try:
        print(f"[THREAD CRASH] {args.exc_type.__name__}: {args.exc_value} in {args.thread}")
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    except Exception:
        pass

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
        try:
            print("Little Fish is already running!")
        except Exception:
            pass
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
