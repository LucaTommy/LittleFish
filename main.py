"""
Little Fish — a living desktop companion.
Entry point: creates the application, loads config, shows the Fish.
"""

import sys
import ctypes
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

from widget.fish_widget import FishWidget

ICO_PATH = Path(__file__).parent / "littlefish.ico"


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
