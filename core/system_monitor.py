"""
System monitor for Little Fish.
Runs on a QThread, emits signals that feed the emotion engine.
Tracks: CPU, RAM, battery, idle time, active window, time of day,
day of week, network, USB devices, screen lock, fullscreen, clipboard.
"""

import time
import datetime
import platform

import psutil
from PyQt6.QtCore import QThread, pyqtSignal


# How often each check runs (seconds)
POLL_FAST = 2.0        # CPU, active window
POLL_MEDIUM = 10.0     # battery, time-of-day, RAM, network
POLL_SLOW = 60.0       # day-of-week, USB


def _get_active_window_title() -> str:
    """Best-effort active window title. Returns '' on failure."""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                return buf.value
        elif system == "Linux":
            import subprocess
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2,
            )
            return result.stdout.strip()
        elif system == "Darwin":
            import subprocess
            script = (
                'tell application "System Events" to get name of '
                'first application process whose frontmost is true'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=2,
            )
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _get_active_process_name() -> str:
    """Best-effort active window process name."""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = psutil.Process(pid.value)
            return proc.name().lower()
    except Exception:
        pass
    return ""


def _is_screen_locked() -> bool:
    """Check if the Windows session is locked."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # If the foreground window is the lock screen, it's locked
        hwnd = user32.GetForegroundWindow()
        if hwnd == 0:
            return True
        # Alternative: check if "LockApp" process exists
        for proc in psutil.process_iter(["name"]):
            if proc.info["name"] and "lockapp" in proc.info["name"].lower():
                return True
    except Exception:
        pass
    return False


def _is_fullscreen() -> bool:
    """Check if the foreground window is fullscreen."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd == 0:
            return False
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        # Compare to the monitor that contains this window
        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        mi = wintypes.RECT()

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint),
                        ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT),
                        ("dwFlags", ctypes.c_uint)]
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(monitor, ctypes.byref(info))
        mr = info.rcMonitor
        return (rect.left <= mr.left and rect.top <= mr.top
                and rect.right >= mr.right and rect.bottom >= mr.bottom)
    except Exception:
        return False


def _get_usb_device_count() -> int:
    """Count connected USB disk devices."""
    try:
        count = 0
        for part in psutil.disk_partitions(all=False):
            if "removable" in part.opts.lower() or part.fstype in ("", "FAT32", "exFAT"):
                count += 1
        return count
    except Exception:
        return 0


def _get_clipboard_hash() -> int:
    """Return a hash of current clipboard text. 0 if empty/error."""
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
        user32.OpenClipboard.restype = ctypes.wintypes.BOOL
        if not user32.OpenClipboard(None):
            return 0
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return 0
            kernel32.GlobalLock.restype = ctypes.c_wchar_p
            text = kernel32.GlobalLock(handle)
            h = hash(text) if text else 0
            kernel32.GlobalUnlock(handle)
            return h
        finally:
            user32.CloseClipboard()
    except Exception:
        return 0


def _get_clipboard_text() -> str:
    """Return current clipboard text. '' if empty/error."""
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
        user32.OpenClipboard.restype = ctypes.wintypes.BOOL
        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            kernel32.GlobalLock.restype = ctypes.c_wchar_p
            text = kernel32.GlobalLock(handle)
            result = str(text)[:500] if text else ""
            kernel32.GlobalUnlock(handle)
            return result
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


# Music / game process detection sets
MUSIC_PROCS = frozenset({
    "spotify.exe", "spotify", "musicbee.exe", "foobar2000.exe",
    "itunes.exe", "aimp.exe", "winamp.exe", "vlc.exe",
    "groove music", "media player",
})
GAME_PROCS = frozenset({
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
    "gog galaxy.exe", "origin.exe", "eadesktop.exe",
    "battle.net.exe", "riotclientservices.exe",
})
GAME_TITLE_HINTS = ("unity", "unreal", "directx", "vulkan", "opengl",
                     "steam", "playing", "game")


class SystemMonitor(QThread):
    """
    Background thread that periodically checks system state
    and emits signals for the emotion engine.
    """

    # --- Original signals ---
    late_night = pyqtSignal()
    idle_15min = pyqtSignal()
    idle_45min = pyqtSignal()
    user_returned = pyqtSignal()
    code_editor_active = pyqtSignal()
    youtube_watching = pyqtSignal()
    cpu_high = pyqtSignal()
    cpu_spike = pyqtSignal()
    battery_low = pyqtSignal()
    battery_plugged = pyqtSignal()
    morning_boost = pyqtSignal()
    monday_detected = pyqtSignal()

    # --- New signals ---
    music_detected = pyqtSignal()          # Spotify / music player active
    game_detected = pyqtSignal()           # Steam / game launcher active
    cpu_normal = pyqtSignal()              # CPU returned to normal from high
    battery_full = pyqtSignal()            # Battery reached 100%
    ram_high = pyqtSignal()                # RAM > 90%
    usb_connected = pyqtSignal()           # New USB device appeared
    screen_locked = pyqtSignal()           # Session locked
    screen_unlocked = pyqtSignal()         # Session unlocked
    midnight_event = pyqtSignal()          # Exactly midnight hour
    new_hour = pyqtSignal()                # A new hour started
    clipboard_changed = pyqtSignal()       # Clipboard content changed
    clipboard_content = pyqtSignal(str)    # Clipboard text for analysis
    network_lost = pyqtSignal()            # Network went down
    network_restored = pyqtSignal()        # Network came back
    fullscreen_entered = pyqtSignal()      # Foreground app went fullscreen
    fullscreen_exited = pyqtSignal()       # Fullscreen ended
    active_app_changed = pyqtSignal(str)   # Active window title changed

    def __init__(self):
        super().__init__()
        self._running = True

        # Idle tracking
        self._last_input_time = time.monotonic()
        self._idle_15_fired = False
        self._idle_45_fired = False

        # Battery tracking
        self._was_plugged = None
        self._battery_low_fired = False
        self._battery_full_fired = False

        # CPU tracking
        self._cpu_was_high = False

        # Time tracking
        self._last_morning_check = 0.0
        self._monday_fired_today = False
        self._last_day = -1
        self._last_hour = -1
        self._midnight_fired_today = False

        # RAM tracking
        self._ram_high_fired = False

        # USB tracking
        self._usb_count = _get_usb_device_count()

        # Screen lock
        self._was_locked = False

        # Late night guard
        self._late_night_fired = False

        # Network
        self._was_connected: bool | None = None

        # Clipboard
        self._last_clip_hash = 0

        # Fullscreen
        self._was_fullscreen = False

        # Music / game
        self._music_detected_until = 0.0
        self._game_detected_until = 0.0

    def stop(self):
        self._running = False

    def notify_input(self):
        """Called from main thread when mouse/keyboard activity detected."""
        was_idle = time.monotonic() - self._last_input_time
        self._last_input_time = time.monotonic()

        if was_idle > 1800:  # > 30 min
            self.user_returned.emit()

        self._idle_15_fired = False
        self._idle_45_fired = False

    def run(self):
        # COM init required for clipboard access from background thread
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(0, 0)  # COINIT_MULTITHREADED
        except Exception:
            pass

        last_fast = 0.0
        last_medium = 0.0
        last_slow = 0.0

        while self._running:
            now = time.monotonic()

            if now - last_fast >= POLL_FAST:
                last_fast = now
                self._check_cpu()
                self._check_active_window()
                self._check_idle()
                self._check_fullscreen()

            if now - last_medium >= POLL_MEDIUM:
                last_medium = now
                self._check_battery()
                self._check_time_of_day()
                self._check_ram()
                self._check_network()
                self._check_clipboard()
                self._check_screen_lock()

            if now - last_slow >= POLL_SLOW:
                last_slow = now
                self._check_day_of_week()
                self._check_usb()

            self.msleep(500)

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _check_cpu(self):
        try:
            cpu = psutil.cpu_percent(interval=0)
            if cpu > 90:
                self.cpu_spike.emit()
                self._cpu_was_high = True
            elif cpu > 75:
                self.cpu_high.emit()
                self._cpu_was_high = True
            elif self._cpu_was_high and cpu < 50:
                self._cpu_was_high = False
                self.cpu_normal.emit()
        except Exception:
            pass

    def _check_active_window(self):
        try:
            title = _get_active_window_title().lower()
            proc = _get_active_process_name()
            now = time.monotonic()

            # Emit active app info for behavior engine
            self.active_app_changed.emit(title)

            # Code editor
            if proc in ("code.exe", "code", "code-insiders.exe",
                         "pycharm64.exe", "idea64.exe", "devenv.exe"):
                self.code_editor_active.emit()

            # YouTube
            if "youtube" in title and proc in (
                "chrome.exe", "firefox.exe", "brave.exe", "msedge.exe",
                "chrome", "firefox", "brave", "msedge",
            ):
                self.youtube_watching.emit()

            # Music detection
            if proc in MUSIC_PROCS or "spotify" in title or "music" in title:
                if now > self._music_detected_until:
                    self.music_detected.emit()
                self._music_detected_until = now + 30  # don't spam, re-check in 30s

            # Game detection
            is_game = proc in GAME_PROCS
            if not is_game:
                for hint in GAME_TITLE_HINTS:
                    if hint in title:
                        is_game = True
                        break
            if is_game and now > self._game_detected_until:
                self.game_detected.emit()
                self._game_detected_until = now + 60
        except Exception:
            pass

    def _check_idle(self):
        idle_secs = time.monotonic() - self._last_input_time
        if idle_secs > 2700 and not self._idle_45_fired:  # 45 min
            self._idle_45_fired = True
            self.idle_45min.emit()
        elif idle_secs > 900 and not self._idle_15_fired:  # 15 min
            self._idle_15_fired = True
            self.idle_15min.emit()

    def _check_battery(self):
        try:
            bat = psutil.sensors_battery()
            if bat is None:
                return

            plugged = bat.power_plugged

            # Plugged-in event
            if self._was_plugged is not None and plugged and not self._was_plugged:
                self.battery_plugged.emit()
            self._was_plugged = plugged

            # Low battery
            if bat.percent < 15 and not plugged:
                if not self._battery_low_fired:
                    self._battery_low_fired = True
                    self.battery_low.emit()
            else:
                self._battery_low_fired = False

            # Battery full
            if bat.percent >= 100 and plugged:
                if not self._battery_full_fired:
                    self._battery_full_fired = True
                    self.battery_full.emit()
            else:
                self._battery_full_fired = False
        except Exception:
            pass

    def _check_ram(self):
        try:
            mem = psutil.virtual_memory()
            if mem.percent > 90:
                if not self._ram_high_fired:
                    self._ram_high_fired = True
                    self.ram_high.emit()
            else:
                self._ram_high_fired = False
        except Exception:
            pass

    def _check_network(self):
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            connected = False
            for iface, st in stats.items():
                if st.isup and iface not in ("lo", "Loopback Pseudo-Interface 1"):
                    if iface in addrs:
                        for a in addrs[iface]:
                            if a.family.name in ("AF_INET", "AF_INET6") and not a.address.startswith("127."):
                                connected = True
                                break
                if connected:
                    break

            if self._was_connected is not None:
                if not connected and self._was_connected:
                    self.network_lost.emit()
                elif connected and not self._was_connected:
                    self.network_restored.emit()
            self._was_connected = connected
        except Exception:
            pass

    def _check_usb(self):
        try:
            count = _get_usb_device_count()
            if count > self._usb_count:
                self.usb_connected.emit()
            self._usb_count = count
        except Exception:
            pass

    def _check_screen_lock(self):
        locked = _is_screen_locked()
        if locked and not self._was_locked:
            self.screen_locked.emit()
        elif not locked and self._was_locked:
            self.screen_unlocked.emit()
        self._was_locked = locked

    def _check_clipboard(self):
        # Clipboard access from a background thread causes access violations
        # on Windows. Clipboard monitoring is done from the main thread via
        # QApplication.clipboard() instead.  This stub is kept so callers
        # don't break.
        pass

    def _check_fullscreen(self):
        fs = _is_fullscreen()
        if fs and not self._was_fullscreen:
            self.fullscreen_entered.emit()
        elif not fs and self._was_fullscreen:
            self.fullscreen_exited.emit()
        self._was_fullscreen = fs

    def _check_time_of_day(self):
        now = datetime.datetime.now()
        hour = now.hour

        # Late night
        if hour >= 23 or hour <= 5:
            if not self._late_night_fired:
                self._late_night_fired = True
                self.late_night.emit()
        else:
            self._late_night_fired = False

        # Morning boost (every 10 minutes)
        if 9 <= hour < 12:
            mono = time.monotonic()
            if mono - self._last_morning_check > 600:
                self._last_morning_check = mono
                self.morning_boost.emit()

        # New hour detection
        if hour != self._last_hour:
            if self._last_hour >= 0:
                self.new_hour.emit()
            self._last_hour = hour

            # Midnight event
            today = now.date().isoformat()
            if hour == 0 and not self._midnight_fired_today:
                self._midnight_fired_today = True
                self.midnight_event.emit()

        # Reset midnight flag for the next day
        if hour == 1:
            self._midnight_fired_today = False

    def _check_day_of_week(self):
        now = datetime.datetime.now()
        today = now.weekday()  # 0 = Monday

        if today != self._last_day:
            self._last_day = today
            self._monday_fired_today = False

        if today == 0 and not self._monday_fired_today:
            self._monday_fired_today = True
            self.monday_detected.emit()
