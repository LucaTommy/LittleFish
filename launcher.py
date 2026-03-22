"""
Little Fish Launcher — a separate companion app that manages,
monitors, and updates Little Fish.

Features:
- Dynamic tray icon reflecting current mood (updates every 5s)
- Full dashboard window with mood, uptime, stats, mood history, about
- Launch / stop Fish from tray or dashboard
- Auto-launch Fish on launcher start (toggleable)
- Launcher auto-starts on Windows boot (registry entry)
- GitHub Releases auto-update checker with download + progress bar
- version.json tracking
- Settings passthrough — launches Fish's settings dialog
- Export/import settings
- Mood summary text

Usage:
    python launcher.py
"""

import json
import sys
import os
import signal
import subprocess
import time
import datetime
import tempfile
import zipfile
import shutil
import threading
import winreg
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

import psutil

from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, pyqtSignal, QObject
from PyQt6.QtGui import (
    QPainter, QIcon, QPixmap, QColor, QFont,
    QPen, QBrush,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMenu, QSystemTrayIcon,
    QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QPushButton,
    QGridLayout, QFrame, QScrollArea, QProgressBar,
    QStackedWidget, QCheckBox, QFileDialog, QMessageBox,
    QDialog, QComboBox, QTextEdit, QLineEdit, QTabWidget,
)

# Add project root to path so we can import shared_state
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).parent
else:
    PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.shared_state import SharedState, STATE_PATH, LOG_PATH
from config import CONFIG_PATH as _SETTINGS_PATH
from config import get_github_token


# ---------------------------------------------------------------------------
# PID liveness helper
# ---------------------------------------------------------------------------

def _is_fish_pid_alive(pid: int) -> bool:
    """Check if a given PID is still a running LittleFish process."""
    if not pid:
        return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            return False
        name = proc.name().lower()
        return "littlefish" in name or "python" in name
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _clean_stale_state():
    """Mark state.json as dead if the PID is no longer running."""
    state = SharedState.read()
    if state.get("alive") and not _is_fish_pid_alive(state.get("pid", 0)):
        try:
            state["alive"] = False
            import datetime as _dt
            state["updated_at"] = _dt.datetime.now().isoformat()
            STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

GITHUB_REPO = "LucaTommy/LittleFish"

# Read version from the install directory (writable, updatable), NOT from
# _MEIPASS which is a temp copy baked into the exe at build-time.
VERSION_PATH = PROJECT_ROOT / "version.json"

# Fallback: if version.json doesn't exist on disk yet (first run after
# install, or running from source), seed it from the bundled copy.
_BUNDLED_VERSION = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "version.json"
if not VERSION_PATH.exists() and _BUNDLED_VERSION.exists() and _BUNDLED_VERSION != VERSION_PATH:
    try:
        shutil.copy2(str(_BUNDLED_VERSION), str(VERSION_PATH))
    except OSError:
        pass


def _read_version() -> dict:
    try:
        if VERSION_PATH.exists():
            return json.loads(VERSION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": "0.0.0", "channel": "stable"}


# ---------------------------------------------------------------------------
# Autostart registry
# ---------------------------------------------------------------------------

STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "LittleFishLauncher"


def _get_autostart() -> bool:
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0,
                            winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def _set_autostart(enabled: bool):
    if sys.platform != "win32":
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                exe = sys.executable
                script = str(PROJECT_ROOT / "launcher.py")
                if getattr(sys, "frozen", False):
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
                else:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                                      f'"{exe}" "{script}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

MOOD_COLORS = {
    "happy": "#4ADE80",
    "excited": "#FACC15",
    "curious": "#60A5FA",
    "focused": "#A78BFA",
    "bored": "#94A3B8",
    "sleepy": "#818CF8",
    "worried": "#FB923C",
    "frustrated": "#EF4444",
    "content": "#34D399",
}

MOOD_EMOJI = {
    "happy": "happy",
    "excited": "excited",
    "curious": "curious",
    "focused": "focused",
    "bored": "bored",
    "sleepy": "sleepy",
    "worried": "worried",
    "frustrated": "frustrated",
    "content": "content",
}

DARK_STYLE = """
    QWidget {
        background-color: #0F172A;
        color: #E2E8F0;
    }
    QLabel {
        color: #E2E8F0;
        font-size: 12px;
        background: transparent;
    }
    QLabel#title {
        color: #7EC8E3;
        font-size: 18px;
        font-weight: bold;
    }
    QLabel#subtitle {
        color: #94A3B8;
        font-size: 10px;
    }
    QLabel#mood-big {
        font-size: 28px;
    }
    QLabel#stat-value {
        color: #7EC8E3;
        font-size: 16px;
        font-weight: bold;
    }
    QLabel#stat-label {
        color: #94A3B8;
        font-size: 10px;
    }
    QLabel#version-label {
        color: #64748B;
        font-size: 10px;
    }
    QLabel#update-label {
        color: #FACC15;
        font-size: 11px;
    }
    QLabel#section-title {
        color: #7EC8E3;
        font-size: 13px;
        font-weight: bold;
    }
    QGroupBox {
        color: #7EC8E3;
        border: 1px solid #1E3A5F;
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 16px;
        font-weight: bold;
        font-size: 12px;
        background: transparent;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
    }
    QPushButton {
        background-color: #1E293B;
        color: #E2E8F0;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #334155;
        border-color: #5BA8C8;
    }
    QPushButton#primary {
        background-color: #1E3A5F;
        border-color: #5BA8C8;
        color: #7EC8E3;
    }
    QPushButton#primary:hover {
        background-color: #5BA8C8;
        color: #0F172A;
    }
    QPushButton#danger {
        border-color: #EF4444;
        color: #FCA5A5;
    }
    QPushButton#danger:hover {
        background-color: #7F1D1D;
        border-color: #EF4444;
    }
    QFrame#separator {
        background-color: #1E3A5F;
        max-height: 1px;
    }
    QProgressBar {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 4px;
        text-align: center;
        color: #E2E8F0;
        font-size: 10px;
    }
    QProgressBar::chunk {
        background-color: #5BA8C8;
        border-radius: 3px;
    }
    QCheckBox {
        color: #E2E8F0;
        font-size: 12px;
    }
    QScrollArea {
        border: none;
        background: transparent;
    }
"""


# ---------------------------------------------------------------------------
# Mood-based tray icon generator
# ---------------------------------------------------------------------------

def _make_mood_icon(mood: str, alive: bool) -> QIcon:
    """Generate a 32x32 pixel-art tray icon that reflects mood."""
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    if not alive:
        body_color = QColor("#64748B")
        body_light = QColor("#94A3B8")
        eye_color = QColor("#334155")
    else:
        body_color = QColor("#5BA8C8")
        body_light = QColor("#7EC8E3")
        eye_color = QColor("#1A1A2E")

    # Body
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(body_color))
    p.drawRoundedRect(2, 2, 28, 28, 3, 3)
    p.setBrush(QBrush(body_light))
    p.drawRoundedRect(3, 3, 26, 26, 2, 2)

    # Mood indicator dot
    if alive and mood in MOOD_COLORS:
        p.setBrush(QBrush(QColor(MOOD_COLORS[mood])))
        p.drawEllipse(24, 2, 7, 7)

    # Eyes
    if not alive or mood == "sleepy":
        p.fillRect(9, 13, 5, 1, eye_color)
        p.fillRect(18, 13, 5, 1, eye_color)
    elif mood == "excited":
        for cx in [11, 20]:
            p.fillRect(cx - 1, 12, 3, 1, QColor("#FFD700"))
            p.fillRect(cx, 11, 1, 3, QColor("#FFD700"))
    elif mood == "worried":
        p.fillRect(10, 11, 3, 4, eye_color)
        p.fillRect(19, 11, 3, 4, eye_color)
        p.fillRect(9, 9, 3, 1, eye_color)
        p.fillRect(20, 9, 3, 1, eye_color)
    elif mood == "focused":
        p.fillRect(10, 12, 3, 2, eye_color)
        p.fillRect(19, 12, 3, 2, eye_color)
    elif mood == "bored":
        p.fillRect(10, 12, 3, 3, eye_color)
        p.fillRect(19, 12, 3, 3, eye_color)
    else:
        p.fillRect(10, 11, 3, 4, eye_color)
        p.fillRect(19, 11, 3, 4, eye_color)

    # Mouth
    mouth_color = eye_color
    if not alive:
        p.fillRect(12, 20, 5, 1, mouth_color)
    elif mood in ("happy", "excited"):
        p.fillRect(12, 20, 1, 1, mouth_color)
        p.fillRect(13, 21, 4, 1, mouth_color)
        p.fillRect(17, 20, 1, 1, mouth_color)
    elif mood == "worried":
        p.fillRect(12, 21, 1, 1, mouth_color)
        p.fillRect(13, 20, 4, 1, mouth_color)
        p.fillRect(17, 21, 1, 1, mouth_color)
    elif mood == "curious":
        p.fillRect(14, 20, 3, 1, mouth_color)
        p.fillRect(14, 22, 3, 1, mouth_color)
        p.fillRect(14, 21, 1, 1, mouth_color)
        p.fillRect(16, 21, 1, 1, mouth_color)
    else:
        p.fillRect(12, 20, 5, 1, mouth_color)

    p.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Update checker (runs in background thread)
# ---------------------------------------------------------------------------

class UpdateSignals(QObject):
    update_available = pyqtSignal(str, str, str)  # version, changelog, download_url
    download_progress = pyqtSignal(int)  # percent 0-100
    download_finished = pyqtSignal(str)  # path to downloaded file
    download_error = pyqtSignal(str)
    no_update = pyqtSignal()


class UpdateChecker:
    """Checks GitHub Releases API for updates."""

    def __init__(self):
        self.signals = UpdateSignals()
        self._latest_download_url: str = ""
        self._latest_version: str = ""

    @staticmethod
    def _gh_headers() -> dict:
        """Build headers for GitHub API, including auth token if available."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "LittleFishLauncher",
        }
        token = get_github_token()
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    def check(self):
        """Check for updates in a background thread."""
        thread = threading.Thread(target=self._check_thread, daemon=True)
        thread.start()

    def download(self, url: str):
        """Download an update in a background thread."""
        thread = threading.Thread(target=self._download_thread, args=(url,), daemon=True)
        thread.start()

    def _check_thread(self):
        current = _read_version().get("version", "0.0.0")
        try:
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            headers = self._gh_headers()
            req = Request(api_url, headers=headers)
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            tag = data.get("tag_name", "").lstrip("v")
            if not tag:
                self.signals.no_update.emit()
                return

            if self._version_newer(tag, current):
                changelog = data.get("body", "No changelog provided.")
                # Find a .zip asset
                download_url = ""
                for asset in data.get("assets", []):
                    if asset["name"].endswith(".zip"):
                        download_url = asset["browser_download_url"]
                        break
                if not download_url:
                    # Fallback to zipball
                    download_url = data.get("zipball_url", "")

                self._latest_download_url = download_url
                self._latest_version = tag
                self.signals.update_available.emit(tag, changelog, download_url)
            else:
                self.signals.no_update.emit()
        except (URLError, OSError, json.JSONDecodeError, KeyError) as e:
            # Emit error message so user can see why check failed
            err_str = str(e)
            if "404" in err_str:
                self.signals.download_error.emit(
                    "Repo not accessible — make it public or add github_token to settings"
                )
            else:
                self.signals.download_error.emit(f"Update check failed: {err_str[:80]}")

    def _download_thread(self, url: str):
        try:
            headers = self._gh_headers()
            headers["Accept"] = "application/octet-stream"
            req = Request(url, headers=headers)
            with urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
                downloaded = 0
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        self.signals.download_progress.emit(int(downloaded * 100 / total))
                tmp.close()
            self.signals.download_finished.emit(tmp.name)
        except (URLError, OSError) as e:
            self.signals.download_error.emit(str(e))

    @staticmethod
    def _version_newer(remote: str, local: str) -> bool:
        """Compare semver strings."""
        try:
            r = tuple(int(x) for x in remote.split(".")[:3])
            l_ = tuple(int(x) for x in local.split(".")[:3])
            return r > l_
        except (ValueError, IndexError):
            return False


# ---------------------------------------------------------------------------
# Mood History Bar
# ---------------------------------------------------------------------------

class MoodHistoryBar(QWidget):
    """Horizontal bar showing mood colors over time."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(24)
        self._data: list[dict] = []

    def set_data(self, data: list[dict]):
        self._data = data
        self.update()

    def paintEvent(self, event):
        if not self._data:
            p = QPainter(self)
            p.fillRect(0, 0, self.width(), self.height(), QColor("#1E293B"))
            p.setPen(QColor("#475569"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No mood data yet")
            p.end()
            return
        p = QPainter(self)
        w = self.width()
        h = self.height()
        n = len(self._data)
        bar_w = max(1, w / n)
        for i, entry in enumerate(self._data):
            mood = entry.get("mood", "happy")
            color = QColor(MOOD_COLORS.get(mood, "#5BA8C8"))
            x = int(i * bar_w)
            bw = max(1, int(bar_w))
            p.fillRect(x, 0, bw, h, color)
        p.end()


# ---------------------------------------------------------------------------
# Main Dashboard Window (proper window, not popup)
# ---------------------------------------------------------------------------

class DashboardWindow(QWidget):
    """Main launcher window — dark theme, pixel aesthetic, ~400x540."""

    launch_fish_requested = pyqtSignal()
    stop_fish_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Little Fish Launcher")
        ico = PROJECT_ROOT / "littlefish.ico"
        if ico.exists():
            self.setWindowIcon(QIcon(str(ico)))
        else:
            self.setWindowIcon(_make_mood_icon("happy", True))
        self.setFixedSize(520, 780)
        self.setStyleSheet(DARK_STYLE)

        self._updater = UpdateChecker()
        self._updater.signals.update_available.connect(self._on_update_available)
        self._updater.signals.no_update.connect(self._on_no_update)
        self._updater.signals.download_progress.connect(self._on_download_progress)
        self._updater.signals.download_finished.connect(self._on_download_finished)
        self._updater.signals.download_error.connect(self._on_download_error)

        self._pending_download_url = ""

        self._build_ui()

        # Auto-refresh
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(3000)
        self._refresh_timer.timeout.connect(self.refresh)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        # ── Header (always visible) ──
        header = QHBoxLayout()
        title = QLabel("Little Fish")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        ver = _read_version()
        self._version_label = QLabel(f"v{ver.get('version', '?')}")
        self._version_label.setObjectName("version-label")
        header.addWidget(self._version_label)
        outer.addLayout(header)

        # ── Status bar (always visible) ──
        status_frame = QFrame()
        status_frame.setStyleSheet(
            "QFrame { background-color: #16213E; border-radius: 8px; padding: 6px; }")
        status_row = QHBoxLayout(status_frame)
        status_row.setContentsMargins(10, 6, 10, 6)
        self._mood_icon_label = QLabel()
        self._mood_icon_label.setFixedSize(36, 36)
        status_row.addWidget(self._mood_icon_label)

        mood_info = QVBoxLayout()
        mood_info.setSpacing(1)
        self._mood_name = QLabel("Offline")
        self._mood_name.setObjectName("stat-value")
        mood_info.addWidget(self._mood_name)
        self._status_label = QLabel("● Fish is not running")
        self._status_label.setObjectName("subtitle")
        mood_info.addWidget(self._status_label)
        self._mood_summary = QLabel("")
        self._mood_summary.setObjectName("subtitle")
        self._mood_summary.setWordWrap(True)
        mood_info.addWidget(self._mood_summary)
        status_row.addLayout(mood_info)
        status_row.addStretch()

        self._launch_btn = QPushButton("Launch Fish")
        self._launch_btn.setObjectName("primary")
        self._launch_btn.setFixedWidth(120)
        self._launch_btn.clicked.connect(self._on_launch_click)
        status_row.addWidget(self._launch_btn)
        outer.addWidget(status_frame)

        # ── Tabs ──
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #1E3A5F;
                border-radius: 6px;
                background: transparent;
            }
            QTabBar::tab {
                background: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 6px 16px;
                margin-right: 2px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: #0F172A;
                color: #7EC8E3;
                border-color: #1E3A5F;
            }
            QTabBar::tab:hover:!selected {
                background: #334155;
                color: #E2E8F0;
            }
        """)

        # ── Tab 1: Overview ──
        overview_tab = self._build_overview_tab()
        self._tabs.addTab(overview_tab, "Overview")

        # ── Tab 2: Personality ──
        personality_tab = self._build_personality_tab()
        self._tabs.addTab(personality_tab, "Personality")

        # ── Tab 3: Settings ──
        settings_tab = self._build_settings_tab()
        self._tabs.addTab(settings_tab, "Settings")

        # ── Tab 4: Updates ──
        updates_tab = self._build_updates_tab()
        self._tabs.addTab(updates_tab, "Updates")

        outer.addWidget(self._tabs, 1)

    def _build_overview_tab(self) -> QWidget:
        """Tab 1: Emotions, Energy, Relationship, Session stats, Mood History."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # Emotion bars
        emo_group = QGroupBox("Emotions")
        emo_layout = QVBoxLayout()
        emo_layout.setSpacing(3)
        self._emo_bars: dict[str, tuple[QLabel, QWidget, QWidget]] = {}
        for emo in ["happy", "curious", "excited", "content", "focused",
                     "bored", "sleepy", "worried", "frustrated"]:
            row = QHBoxLayout()
            name_lbl = QLabel(emo.capitalize())
            name_lbl.setFixedWidth(65)
            name_lbl.setObjectName("stat-label")
            row.addWidget(name_lbl)
            bar_bg = QWidget()
            bar_bg.setFixedHeight(8)
            bar_bg.setStyleSheet("background-color: #1E293B; border-radius: 4px;")
            bar_inner = QWidget(bar_bg)
            bar_inner.setFixedHeight(8)
            bar_inner.setStyleSheet(
                f"background-color: {MOOD_COLORS.get(emo, '#5BA8C8')}; border-radius: 4px;"
            )
            bar_inner.setFixedWidth(0)
            row.addWidget(bar_bg)
            val_lbl = QLabel("0.0")
            val_lbl.setFixedWidth(30)
            val_lbl.setObjectName("subtitle")
            row.addWidget(val_lbl)
            emo_layout.addLayout(row)
            self._emo_bars[emo] = (val_lbl, bar_inner, bar_bg)
        emo_group.setLayout(emo_layout)
        layout.addWidget(emo_group)

        # Energy & Relationship
        er_group = QGroupBox("Status")
        er_layout = QVBoxLayout()
        er_layout.setSpacing(6)

        energy_row = QHBoxLayout()
        energy_lbl = QLabel("Energy")
        energy_lbl.setFixedWidth(80)
        energy_lbl.setObjectName("stat-label")
        energy_row.addWidget(energy_lbl)
        self._energy_bar_bg = QWidget()
        self._energy_bar_bg.setFixedHeight(10)
        self._energy_bar_bg.setStyleSheet("background-color: #1E293B; border-radius: 5px;")
        self._energy_bar_inner = QWidget(self._energy_bar_bg)
        self._energy_bar_inner.setFixedHeight(10)
        self._energy_bar_inner.setStyleSheet("background-color: #FBBF24; border-radius: 5px;")
        self._energy_bar_inner.setFixedWidth(0)
        energy_row.addWidget(self._energy_bar_bg)
        self._energy_val = QLabel("--")
        self._energy_val.setFixedWidth(36)
        self._energy_val.setObjectName("subtitle")
        energy_row.addWidget(self._energy_val)
        er_layout.addLayout(energy_row)

        rel_row = QHBoxLayout()
        rel_lbl = QLabel("Relationship")
        rel_lbl.setFixedWidth(80)
        rel_lbl.setObjectName("stat-label")
        rel_row.addWidget(rel_lbl)
        self._rel_bar_bg = QWidget()
        self._rel_bar_bg.setFixedHeight(10)
        self._rel_bar_bg.setStyleSheet("background-color: #1E293B; border-radius: 5px;")
        self._rel_bar_inner = QWidget(self._rel_bar_bg)
        self._rel_bar_inner.setFixedHeight(10)
        self._rel_bar_inner.setStyleSheet("background-color: #F472B6; border-radius: 5px;")
        self._rel_bar_inner.setFixedWidth(0)
        rel_row.addWidget(self._rel_bar_bg)
        self._rel_val = QLabel("--")
        self._rel_val.setFixedWidth(80)
        self._rel_val.setObjectName("subtitle")
        rel_row.addWidget(self._rel_val)
        er_layout.addLayout(rel_row)

        er_group.setLayout(er_layout)
        layout.addWidget(er_group)

        # Session stats
        stats_group = QGroupBox("Session")
        stats_grid = QGridLayout()
        stats_grid.setSpacing(6)
        self._uptime_val = QLabel("--")
        self._uptime_val.setObjectName("stat-value")
        self._interact_val = QLabel("0")
        self._interact_val.setObjectName("stat-value")
        self._games_val = QLabel("0")
        self._games_val.setObjectName("stat-value")
        self._phrases_val = QLabel("0")
        self._phrases_val.setObjectName("stat-value")
        for i, (val, lbl) in enumerate([
            (self._uptime_val, "Uptime"),
            (self._interact_val, "Interactions"),
            (self._games_val, "Games"),
            (self._phrases_val, "Phrases"),
        ]):
            stats_grid.addWidget(val, 0, i, Qt.AlignmentFlag.AlignCenter)
            l = QLabel(lbl)
            l.setObjectName("stat-label")
            stats_grid.addWidget(l, 1, i, Qt.AlignmentFlag.AlignCenter)
        stats_group.setLayout(stats_grid)
        layout.addWidget(stats_group)

        # Mood History
        history_group = QGroupBox("Mood History (24h)")
        history_layout = QVBoxLayout()
        self._history_bar = MoodHistoryBar()
        history_layout.addWidget(self._history_bar)
        history_group.setLayout(history_layout)
        layout.addWidget(history_group)

        layout.addStretch()
        scroll.setWidget(container)
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        return tab

    def _build_personality_tab(self) -> QWidget:
        """Tab 2: Fish Memories + Emotion Tuning."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        self._build_memory_panel(layout)
        self._build_emotion_config_panel(layout)

        layout.addStretch()
        scroll.setWidget(container)
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        return tab

    def _build_settings_tab(self) -> QWidget:
        """Tab 3: Settings, Profile, Auto-launch, Import/Export."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Quick actions
        actions_group = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)

        row1 = QHBoxLayout()
        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setObjectName("primary")
        settings_btn.clicked.connect(self._open_settings)
        row1.addWidget(settings_btn)
        profile_btn = QPushButton("👤  Profile")
        profile_btn.setToolTip("View / edit your profile")
        profile_btn.clicked.connect(self._open_profile)
        row1.addWidget(profile_btn)
        mood_log_btn = QPushButton("📊  Mood Log")
        mood_log_btn.clicked.connect(self._show_mood_log)
        row1.addWidget(mood_log_btn)
        actions_layout.addLayout(row1)

        row2 = QHBoxLayout()
        export_btn = QPushButton("Export")
        export_btn.setToolTip("Export settings to file")
        export_btn.clicked.connect(self._export_settings)
        row2.addWidget(export_btn)
        import_btn = QPushButton("Import")
        import_btn.setToolTip("Import settings from file")
        import_btn.clicked.connect(self._import_settings)
        row2.addWidget(import_btn)
        about_btn = QPushButton("About")
        about_btn.clicked.connect(self._show_about)
        row2.addWidget(about_btn)
        actions_layout.addLayout(row2)

        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        # Startup options
        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout()
        startup_layout.setSpacing(6)

        self._auto_launch_cb = QCheckBox("Auto-launch Fish when launcher starts")
        self._auto_launch_cb.setChecked(self._load_launcher_prefs().get("auto_launch", True))
        self._auto_launch_cb.toggled.connect(self._on_auto_launch_toggle)
        startup_layout.addWidget(self._auto_launch_cb)

        self._autostart_cb = QCheckBox("Start launcher on Windows boot")
        self._autostart_cb.setChecked(_get_autostart())
        self._autostart_cb.toggled.connect(lambda c: _set_autostart(c))
        startup_layout.addWidget(self._autostart_cb)

        startup_group.setLayout(startup_layout)
        layout.addWidget(startup_group)

        # Danger zone
        danger_group = QGroupBox("Danger Zone")
        danger_layout = QVBoxLayout()
        reset_btn = QPushButton("Reset Little Fish")
        reset_btn.setObjectName("danger")
        reset_btn.setToolTip("Reset all Little Fish settings to defaults")
        reset_btn.clicked.connect(self._reset_fish)
        danger_layout.addWidget(reset_btn)
        danger_group.setLayout(danger_layout)
        layout.addWidget(danger_group)

        layout.addStretch()
        return tab

    def _build_updates_tab(self) -> QWidget:
        """Tab 4: Update checking + download."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._update_group = QGroupBox("Updates")
        update_layout = QVBoxLayout()
        update_layout.setSpacing(4)
        self._update_status = QLabel("Checking for updates...")
        self._update_status.setObjectName("subtitle")
        update_layout.addWidget(self._update_status)
        self._update_changelog = QLabel("")
        self._update_changelog.setObjectName("subtitle")
        self._update_changelog.setWordWrap(True)
        self._update_changelog.setMaximumHeight(80)
        self._update_changelog.hide()
        update_layout.addWidget(self._update_changelog)
        self._update_progress = QProgressBar()
        self._update_progress.setFixedHeight(16)
        self._update_progress.hide()
        update_layout.addWidget(self._update_progress)
        update_btn_row = QHBoxLayout()
        self._update_btn = QPushButton("Update Now")
        self._update_btn.setObjectName("primary")
        self._update_btn.hide()
        self._update_btn.clicked.connect(self._on_update_click)
        update_btn_row.addWidget(self._update_btn)
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.hide()
        self._skip_btn.clicked.connect(self._on_skip_update)
        update_btn_row.addWidget(self._skip_btn)
        self._rollback_btn = QPushButton("Rollback")
        self._rollback_btn.setToolTip("Restore previous version from backup")
        # Show rollback only when a backup exists
        self._rollback_btn.setVisible((PROJECT_ROOT / "_backup").exists())
        self._rollback_btn.clicked.connect(self._on_rollback)
        update_btn_row.addWidget(self._rollback_btn)
        self._check_update_btn = QPushButton("Check Now")
        self._check_update_btn.clicked.connect(self.check_for_updates)
        update_btn_row.addWidget(self._check_update_btn)
        update_btn_row.addStretch()
        update_layout.addLayout(update_btn_row)
        self._update_group.setLayout(update_layout)
        layout.addWidget(self._update_group)

        layout.addStretch()
        return tab

    def _add_separator(self, layout):
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

    # ------------------------------------------------------------------
    # Memory panel
    # ------------------------------------------------------------------

    def _build_memory_panel(self, parent_layout):
        """Build the fish memory panel — view, add, edit, remove memories."""
        from core.fish_memory import FishMemory

        group = QGroupBox("Fish Memories")
        layout = QVBoxLayout()
        layout.setSpacing(4)

        info = QLabel("Things the fish remembers. You can add or edit them.")
        info.setObjectName("subtitle")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Memory list
        self._memory_list = QTextEdit()
        self._memory_list.setReadOnly(True)
        self._memory_list.setMaximumHeight(120)
        self._memory_list.setStyleSheet(
            "QTextEdit { background: #1E293B; color: #CBD5E1; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px; font-size: 11px; }"
        )
        layout.addWidget(self._memory_list)

        # Add row
        add_row = QHBoxLayout()
        self._memory_input = QLineEdit()
        self._memory_input.setPlaceholderText("Add a memory (e.g. 'User's name is Alex')...")
        self._memory_input.setStyleSheet(
            "QLineEdit { background: #1E293B; color: #CBD5E1; border: 1px solid #334155; "
            "border-radius: 4px; padding: 4px 8px; }"
        )
        add_row.addWidget(self._memory_input, 1)

        add_btn = QPushButton("Add")
        add_btn.setObjectName("primary")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_memory)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        # Edit/Delete row
        edit_row = QHBoxLayout()
        self._memory_index_input = QLineEdit()
        self._memory_index_input.setPlaceholderText("#")
        self._memory_index_input.setFixedWidth(36)
        self._memory_index_input.setStyleSheet(
            "QLineEdit { background: #1E293B; color: #CBD5E1; border: 1px solid #334155; "
            "border-radius: 4px; padding: 4px; text-align: center; }"
        )
        edit_row.addWidget(self._memory_index_input)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(50)
        edit_btn.clicked.connect(self._edit_memory)
        edit_row.addWidget(edit_btn)

        del_btn = QPushButton("Delete")
        del_btn.setObjectName("danger")
        del_btn.setFixedWidth(60)
        del_btn.clicked.connect(self._delete_memory)
        edit_row.addWidget(del_btn)

        edit_row.addStretch()
        layout.addLayout(edit_row)

        group.setLayout(layout)
        parent_layout.addWidget(group)
        self._refresh_memory_list()

    def _refresh_memory_list(self):
        from core.fish_memory import FishMemory
        fm = FishMemory.load()
        if not fm.memories:
            self._memory_list.setPlainText("No memories yet.")
            return
        lines = []
        for i, m in enumerate(fm.memories):
            pin = "📌 " if m.get("pinned") else ""
            lines.append(f"{i+1}. {pin}{m['text']}")
        self._memory_list.setPlainText("\n".join(lines))

    def _add_memory(self):
        from core.fish_memory import FishMemory
        text = self._memory_input.text().strip()
        if not text:
            return
        fm = FishMemory.load()
        fm.add(text)
        self._memory_input.clear()
        self._refresh_memory_list()

    def _edit_memory(self):
        from core.fish_memory import FishMemory
        idx_text = self._memory_index_input.text().strip()
        try:
            idx = int(idx_text) - 1
        except ValueError:
            return
        new_text = self._memory_input.text().strip()
        if not new_text:
            return
        fm = FishMemory.load()
        fm.edit(idx, new_text)
        self._memory_input.clear()
        self._memory_index_input.clear()
        self._refresh_memory_list()

    def _delete_memory(self):
        from core.fish_memory import FishMemory
        idx_text = self._memory_index_input.text().strip()
        try:
            idx = int(idx_text) - 1
        except ValueError:
            return
        fm = FishMemory.load()
        fm.remove(idx)
        self._memory_index_input.clear()
        self._refresh_memory_list()

    # ------------------------------------------------------------------
    # Emotion config panel
    # ------------------------------------------------------------------

    def _build_emotion_config_panel(self, parent_layout):
        """Build emotion baseline configuration — lets the user tune the fish's vibe."""
        group = QGroupBox("Emotion Tuning")
        layout = QVBoxLayout()
        layout.setSpacing(4)

        info = QLabel("Adjust baseline mood. Higher = fish tends more toward that emotion.")
        info.setObjectName("subtitle")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._emo_sliders: dict[str, QProgressBar] = {}
        self._emo_config_values: dict[str, float] = {}

        # Load current config
        config = self._load_emotion_config()

        DEFAULTS = {
            "happy": 0.35, "bored": 0.1, "curious": 0.25, "sleepy": 0.0,
            "excited": 0.05, "worried": 0.0, "focused": 0.15,
            "frustrated": 0.0, "content": 0.2,
        }

        for emo in ["happy", "curious", "excited", "content", "focused",
                     "bored", "sleepy", "worried", "frustrated"]:
            row = QHBoxLayout()
            lbl = QLabel(emo.capitalize())
            lbl.setFixedWidth(70)
            lbl.setObjectName("stat-label")
            row.addWidget(lbl)

            val = config.get(emo, DEFAULTS.get(emo, 0.0))
            self._emo_config_values[emo] = val

            # Use buttons to adjust since QSlider styling is complex
            minus_btn = QPushButton("−")
            minus_btn.setFixedSize(24, 24)
            minus_btn.clicked.connect(lambda checked, e=emo: self._adjust_emo_config(e, -0.05))
            row.addWidget(minus_btn)

            bar = QProgressBar()
            bar.setRange(0, 60)
            bar.setValue(int(val * 100))
            bar.setFixedHeight(14)
            bar.setFormat(f"{val:.2f}")
            bar.setStyleSheet(
                f"QProgressBar {{ background: #1E293B; border-radius: 7px; border: 1px solid #334155; "
                f"text-align: center; color: #CBD5E1; font-size: 10px; }}"
                f"QProgressBar::chunk {{ background: {MOOD_COLORS.get(emo, '#5BA8C8')}; border-radius: 6px; }}"
            )
            row.addWidget(bar, 1)
            self._emo_sliders[emo] = bar

            plus_btn = QPushButton("+")
            plus_btn.setFixedSize(24, 24)
            plus_btn.clicked.connect(lambda checked, e=emo: self._adjust_emo_config(e, 0.05))
            row.addWidget(plus_btn)

            layout.addLayout(row)

        # Save / Reset buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.setFixedWidth(80)
        save_btn.clicked.connect(self._save_emotion_config)
        btn_row.addWidget(save_btn)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setFixedWidth(120)
        reset_btn.clicked.connect(self._reset_emotion_config)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Night Owl toggle
        self._night_owl_cb = QCheckBox("Night Owl Mode (stay active at night)")
        self._night_owl_cb.setChecked(config.get("night_owl", False))
        layout.addWidget(self._night_owl_cb)

        group.setLayout(layout)
        parent_layout.addWidget(group)

    def _adjust_emo_config(self, emo: str, delta: float):
        val = self._emo_config_values.get(emo, 0.0) + delta
        val = max(0.0, min(0.6, round(val, 2)))
        self._emo_config_values[emo] = val
        bar = self._emo_sliders[emo]
        bar.setValue(int(val * 100))
        bar.setFormat(f"{val:.2f}")

    def _load_emotion_config(self) -> dict:
        import os
        appdata = os.environ.get("APPDATA", "")
        p = Path(appdata) / "LittleFish" / "emotion_config.json" if appdata else Path.home() / ".littlefish" / "emotion_config.json"
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _save_emotion_config(self):
        import os
        appdata = os.environ.get("APPDATA", "")
        d = Path(appdata) / "LittleFish" if appdata else Path.home() / ".littlefish"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "emotion_config.json"
        try:
            data = dict(self._emo_config_values)
            data["night_owl"] = self._night_owl_cb.isChecked()
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Saved", "Emotion tuning saved! Restart Fish for changes to take effect.")
        except OSError as e:
            QMessageBox.warning(self, "Error", f"Could not save: {e}")

    def _reset_emotion_config(self):
        DEFAULTS = {
            "happy": 0.35, "bored": 0.1, "curious": 0.25, "sleepy": 0.0,
            "excited": 0.05, "worried": 0.0, "focused": 0.15,
            "frustrated": 0.0, "content": 0.2,
        }
        self._emo_config_values = dict(DEFAULTS)
        for emo, bar in self._emo_sliders.items():
            val = DEFAULTS.get(emo, 0.0)
            bar.setValue(int(val * 100))
            bar.setFormat(f"{val:.2f}")
        self._night_owl_cb.setChecked(False)

    def refresh(self):
        # Validate PID is actually alive before trusting state
        _clean_stale_state()

        state = SharedState.read()
        alive = state.get("alive", False)
        dominant = state.get("dominant_emotion", "happy")

        self._mood_icon_label.setPixmap(
            _make_mood_icon(dominant if alive else "happy", alive).pixmap(36, 36))

        # Show fish name + compound emotion if available
        fish_name = state.get("fish_name", "Little Fish")
        compound = state.get("compound_emotion", [])
        rel_stage = state.get("relationship_stage", "")
        energy = state.get("energy", 1.0)

        if alive and isinstance(compound, list) and len(compound) >= 2 and compound[0] != compound[1]:
            self._mood_name.setText(f"{compound[0].capitalize()} + {compound[1].capitalize()}")
        else:
            self._mood_name.setText(dominant.capitalize() if alive else "Offline")

        if alive:
            self._status_label.setText(f"● Running — {state.get('uptime_human', '')}")
            self._status_label.setStyleSheet("color: #4ADE80; font-size: 10px;")
            self._launch_btn.setText("Restart Fish")
            self._launch_btn.setObjectName("primary")
        else:
            self._status_label.setText("● Fish is not running")
            self._status_label.setStyleSheet("color: #EF4444; font-size: 10px;")
            self._launch_btn.setText("Launch Fish")
            self._launch_btn.setObjectName("primary")
        # Force style refresh on button
        self._launch_btn.setStyleSheet(self._launch_btn.styleSheet())
        self._launch_btn.style().unpolish(self._launch_btn)
        self._launch_btn.style().polish(self._launch_btn)

        if state.get("quiet_mode") and alive:
            self._mood_summary.setText("In quiet/focus mode")
        elif alive:
            summary = self._generate_mood_summary(state)
            if rel_stage:
                stage_display = rel_stage.replace("_", " ").title()
                summary += f" | {stage_display}"
            if energy < 0.3:
                summary += " | Low energy"
            self._mood_summary.setText(summary)
        else:
            self._mood_summary.setText("")

        # Emotion bars
        emotions = state.get("emotions", {})
        for emo, (val_lbl, bar_inner, bar_bg) in self._emo_bars.items():
            val = emotions.get(emo, 0.0)
            val_lbl.setText(f"{val:.2f}")
            bg_width = bar_bg.width()
            bar_inner.setFixedWidth(max(0, int(val * bg_width)))

        # Energy bar
        energy_bg_w = self._energy_bar_bg.width()
        self._energy_bar_inner.setFixedWidth(max(0, int(energy * energy_bg_w)))
        if alive:
            pct = int(energy * 100)
            self._energy_val.setText(f"{pct}%")
            if energy < 0.3:
                self._energy_bar_inner.setStyleSheet("background-color: #EF4444; border-radius: 5px;")
            elif energy < 0.6:
                self._energy_bar_inner.setStyleSheet("background-color: #FBBF24; border-radius: 5px;")
            else:
                self._energy_bar_inner.setStyleSheet("background-color: #4ADE80; border-radius: 5px;")
        else:
            self._energy_val.setText("--")
            self._energy_bar_inner.setFixedWidth(0)

        # Relationship bar
        rel_points = state.get("relationship_points", 0)
        STAGE_THRESHOLDS = {"stranger": 0, "acquaintance": 50, "friend": 150, "close_friend": 350, "best_friend": 600}
        STAGE_ORDER = ["stranger", "acquaintance", "friend", "close_friend", "best_friend"]
        if alive and rel_stage:
            idx = STAGE_ORDER.index(rel_stage) if rel_stage in STAGE_ORDER else 0
            if idx < len(STAGE_ORDER) - 1:
                current_th = STAGE_THRESHOLDS[STAGE_ORDER[idx]]
                next_th = STAGE_THRESHOLDS[STAGE_ORDER[idx + 1]]
                progress = (rel_points - current_th) / max(1, next_th - current_th)
                progress = max(0.0, min(1.0, progress))
            else:
                progress = 1.0
            rel_bg_w = self._rel_bar_bg.width()
            self._rel_bar_inner.setFixedWidth(max(0, int(progress * rel_bg_w)))
            stage_display = rel_stage.replace("_", " ").title()
            self._rel_val.setText(f"{stage_display}")
        else:
            self._rel_bar_inner.setFixedWidth(0)
            self._rel_val.setText("--")

        # Stats
        stats = state.get("stats", {})
        self._uptime_val.setText(state.get("uptime_human", "--"))
        self._interact_val.setText(str(stats.get("interactions", 0)))
        self._games_val.setText(str(stats.get("games_played", 0)))
        self._phrases_val.setText(str(stats.get("phrases_said", 0)))

        # History
        log = SharedState.read_mood_log()
        self._history_bar.set_data(log[-24:])

    def _generate_mood_summary(self, state: dict) -> str:
        """Generate a short text summary of today's mood from the log."""
        log = SharedState.read_mood_log()
        if not log:
            return ""
        today = datetime.date.today().isoformat()
        today_entries = [e for e in log if e.get("time", "").startswith(today)]
        if not today_entries:
            return ""
        # Count mood occurrences
        counts: dict[str, int] = {}
        for e in today_entries:
            m = e.get("mood", "happy")
            counts[m] = counts.get(m, 0) + 1
        dominant = max(counts, key=counts.get)
        return f"Today: mostly {dominant} ({counts[dominant]}h logged)"

    # ------------------------------------------------------------------
    # Launch / Stop
    # ------------------------------------------------------------------

    def _on_launch_click(self):
        state = SharedState.read()
        if state.get("alive"):
            # Restart: stop then relaunch
            self.stop_fish_requested.emit()
            QTimer.singleShot(1500, lambda: self.launch_fish_requested.emit())
        else:
            self.launch_fish_requested.emit()

    # ------------------------------------------------------------------
    # Update handlers
    # ------------------------------------------------------------------

    def check_for_updates(self):
        self._update_status.setText("Checking for updates...")
        self._updater.check()

    def _on_update_available(self, version: str, changelog: str, url: str):
        self._pending_download_url = url
        self._update_status.setText(f"Update available: v{version}")
        self._update_status.setObjectName("update-label")
        self._update_status.setStyleSheet("color: #FACC15; font-size: 11px;")
        # Truncate changelog
        short = changelog[:120] + ("..." if len(changelog) > 120 else "")
        self._update_changelog.setText(short)
        self._update_changelog.show()
        self._update_btn.show()
        self._skip_btn.show()

    def _on_no_update(self):
        ver = _read_version().get("version", "?")
        self._update_status.setText(f"Up to date (v{ver})")
        self._update_status.setStyleSheet("color: #4ADE80; font-size: 10px;")

    def _on_update_click(self):
        if not self._pending_download_url:
            return
        self._update_btn.setEnabled(False)
        self._update_progress.setValue(0)
        self._update_progress.show()
        self._update_status.setText("Downloading...")
        self._updater.download(self._pending_download_url)

    def _on_skip_update(self):
        self._update_changelog.hide()
        self._update_btn.hide()
        self._skip_btn.hide()
        self._update_status.setText("Update skipped")
        self._update_status.setStyleSheet("color: #94A3B8; font-size: 10px;")

    def _on_download_progress(self, pct: int):
        self._update_progress.setValue(pct)

    def _on_download_finished(self, zip_path: str):
        self._update_progress.setValue(100)
        self._update_status.setText("Download complete! Extracting...")
        try:
            self._apply_update(zip_path)
            new_ver = self._updater._latest_version
            self._update_status.setText(
                f"v{new_ver} ready! Click 'Apply & Restart' to install."
            )
            self._update_status.setStyleSheet("color: #FACC15; font-size: 11px;")
            self._update_changelog.hide()
            self._update_progress.hide()
            # Swap buttons: hide Update/Skip, show Apply & Restart
            self._update_btn.hide()
            self._skip_btn.hide()
            if not hasattr(self, "_apply_btn"):
                self._apply_btn = QPushButton("Apply && Restart")
                self._apply_btn.setObjectName("primary")
                self._apply_btn.clicked.connect(self._on_apply_restart)
                # Insert into the button row
                self._update_btn.parent().layout().insertWidget(0, self._apply_btn)
            self._apply_btn.show()
        except Exception as e:
            self._update_status.setText(f"Update failed: {str(e)[:60]}")
            self._update_status.setStyleSheet("color: #EF4444; font-size: 10px;")
        finally:
            try:
                os.unlink(zip_path)
            except OSError:
                pass
            self._update_btn.setEnabled(True)

    def _on_apply_restart(self):
        """Launch the batch updater script, then quit so it can replace files."""
        script = PROJECT_ROOT / "_apply_update.cmd"
        if not script.exists():
            self._update_status.setText("Update staging missing. Re-download needed.")
            self._update_status.setStyleSheet("color: #EF4444; font-size: 10px;")
            return
        # Stop the fish first
        app = QApplication.instance()
        launcher = None
        for w in app.topLevelWidgets():
            if hasattr(w, "_stop_fish"):
                launcher = w
                break
        if launcher:
            launcher._stop_fish()
        # Launch the batch script (hidden window)
        subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            cwd=str(PROJECT_ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # Quit the launcher so the script can replace it
        QApplication.quit()

    def _on_download_error(self, err: str):
        self._update_status.setText(f"Download failed: {err[:60]}")
        self._update_status.setStyleSheet("color: #EF4444; font-size: 10px;")
        self._update_progress.hide()
        self._update_btn.setEnabled(True)

    def _apply_update(self, zip_path: str):
        """Extract update zip to staging and prepare batch updater script."""
        staging = PROJECT_ROOT / "_update_staging"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(exist_ok=True)

        # Extract zip to staging
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            prefix = ""
            if names and "/" in names[0]:
                prefix = names[0].split("/")[0] + "/"

            for member in zf.infolist():
                if member.is_dir():
                    continue
                rel = member.filename
                if prefix and rel.startswith(prefix):
                    rel = rel[len(prefix):]
                if not rel:
                    continue
                # Never overwrite user settings
                if rel == "config/settings.json":
                    continue
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        # Backup current key files
        backup = PROJECT_ROOT / "_backup"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        backup.mkdir(exist_ok=True)
        for name in ["LittleFish.exe", "LittleFishLauncher.exe", "version.json",
                      "littlefish.ico"]:
            src = PROJECT_ROOT / name
            if src.exists():
                shutil.copy2(src, backup / name)

        # Write batch script that waits for processes to exit, then copies files
        launcher_exe = PROJECT_ROOT / "LittleFishLauncher.exe"
        script_lines = [
            "@echo off",
            "echo Updating Little Fish, please wait...",
            "",
            "REM Wait for launcher to exit",
            ":wait_launcher",
            "timeout /t 1 /nobreak >nul",
            'tasklist /FI "IMAGENAME eq LittleFishLauncher.exe" 2>nul '
            "| findstr /I /C:\"LittleFishLauncher\" >nul",
            "if %ERRORLEVEL%==0 goto wait_launcher",
            "",
            "REM Kill fish if still running",
            'tasklist /FI "IMAGENAME eq LittleFish.exe" 2>nul '
            "| findstr /I /C:\"LittleFish.exe\" >nul",
            "if %ERRORLEVEL%==0 (",
            "    taskkill /F /IM LittleFish.exe >nul 2>&1",
            "    timeout /t 2 /nobreak >nul",
            ")",
            "",
            "REM Copy staged files over the installation",
            f'xcopy /E /Y /Q "{staging}\\" "{PROJECT_ROOT}\\"',
            "",
            "REM Clean up staging",
            f'rmdir /S /Q "{staging}"',
            "",
            "REM Restart the launcher",
            f'start "" "{launcher_exe}"',
            "",
            "REM Delete this script",
            'del "%~f0"',
        ]
        script = PROJECT_ROOT / "_apply_update.cmd"
        script.write_text("\r\n".join(script_lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self):
        """Open the fish settings dialog directly, or signal the running fish."""
        settings_path = _SETTINGS_PATH
        state = SharedState.read()
        if state.get("alive"):
            # Signal running fish to open its own settings dialog
            flag = STATE_PATH.parent / "open_settings_flag"
            try:
                flag.write_text("1", encoding="utf-8")
            except OSError:
                pass
            return
        # Fish not running — open standalone settings dialog
        try:
            config = {}
            if settings_path.exists():
                config = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = {}
        from config.config_ui import StandaloneSettingsDialog
        dlg = StandaloneSettingsDialog(config, parent=self)
        dlg.exec()

    def _open_profile(self):
        """Show a profile viewer/editor dialog."""
        from core.user_profile import UserProfile
        from core.relationship import Relationship
        profile = UserProfile()
        relationship = Relationship()

        dlg = QDialog(self)
        dlg.setWindowTitle("Fish Profile")
        dlg.setFixedWidth(380)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel(f"🐟 {profile.fish_name}")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(title)

        info_lines = [
            f"Age: {profile.age} ({profile.age_group.replace('_', ' ')})" if profile.age else "Age: Not set",
            f"Usage: {profile.usage.replace('_', ' ').title()}",
            f"Chronotype: {profile.chronotype.replace('_', ' ').title()}",
            f"Talkativeness: {profile.talkativeness.title()}",
            f"",
            f"Relationship: {relationship.stage.replace('_', ' ').title()}",
            f"Points: {relationship.points}",
            f"Day streak: {relationship.consecutive_days}",
        ]
        for line in info_lines:
            lbl = QLabel(line)
            lbl.setStyleSheet("font-size: 12px; color: #D1D5DB;")
            layout.addWidget(lbl)

        # Re-onboard button
        reonboard_btn = QPushButton("Re-run Onboarding")
        reonboard_btn.setToolTip("Re-do the onboarding wizard (resets your profile)")
        def _reonboard():
            from core.onboarding import run_onboarding
            result = run_onboarding(parent=dlg)
            if result:
                profile.complete_onboarding(
                    age=result.get("age", 20),
                    usage=result.get("usage", "general"),
                    chronotype=result.get("chronotype", "normal"),
                    talkativeness=result.get("talkativeness", "moderate"),
                    fish_name=result.get("fish_name", "Little Fish"),
                )
                dlg.accept()
        reonboard_btn.clicked.connect(_reonboard)
        layout.addWidget(reonboard_btn)

        dlg.exec()

    def _export_settings(self):
        """Export settings.json to a user-chosen location."""
        src = _SETTINGS_PATH
        if not src.exists():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Little Fish Settings", "LittleFish_settings.json",
            "JSON Files (*.json)")
        if path:
            shutil.copy2(str(src), path)

    def _import_settings(self):
        """Import a settings.json from file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Little Fish Settings", "",
            "JSON Files (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            # Validate it's a dict with expected keys
            if not isinstance(data, dict):
                raise ValueError("Invalid settings format")
            dst = _SETTINGS_PATH
            dst.write_text(json.dumps(data, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Settings Imported",
                                    "Settings imported! Restart Fish to apply.")
        except (json.JSONDecodeError, ValueError, OSError) as e:
            QMessageBox.warning(self, "Import Failed", f"Could not import: {e}")

    # ------------------------------------------------------------------
    # Reset Fish
    # ------------------------------------------------------------------

    def _reset_fish(self):
        """Reset Little Fish settings to defaults."""
        reply = QMessageBox.question(
            self, "Reset Little Fish",
            "This will reset all settings to defaults and clear chat history.\n"
            "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Stop fish first if running
        self.stop_fish_requested.emit()

        # Reset settings.json
        default_settings = {
            "appearance": {
                "size": 80, "opacity": 1.0, "position": [100, 100],
                "always_on_top": True, "body_color": "#7EC8E3", "eye_style": "default",
                "mouth_style": "default", "dark_border": False, "glow_enabled": False,
                "sparkle_eyes": False, "shadow": False, "hat": "", "tail_style": "",
                "skin_preset": "", "custom_name": "",
            },
            "voice": {"push_to_talk_key": "ctrl_right", "always_listening": False,
                      "tts_enabled": True, "tts_voice": "default", "whisper_mode": "groq"},
            "permissions": {"microphone": True, "browser_control": True,
                            "system_monitor": True, "tts": True, "minigames": True},
            "personality": {
                "curiosity_baseline": 0.6, "boredom_threshold": 0.7,
                "attention_seeking": 0.5, "reaction_intensity": 0.8,
                "sleep_resistance": 0.3, "chattiness": 0.4,
            },
            "intelligence": {
                "companion_mode": False, "clipboard_reactions": False,
                "app_awareness": False, "todo_list": False,
                "morning_briefing": False, "jokes": False,
                "autonomous_behavior": True,
            },
        }
        settings_path = _SETTINGS_PATH
        try:
            settings_path.write_text(json.dumps(default_settings, indent=2), encoding="utf-8")
        except OSError:
            pass

        # Clear chat history
        chat_path = Path.home() / "AppData" / "Roaming" / "LittleFish" / "chat_history.json"
        try:
            if chat_path.exists():
                chat_path.write_text("[]", encoding="utf-8")
        except OSError:
            pass

        QMessageBox.information(self, "Reset Complete",
                                "Settings reset to defaults.\nRelaunch Fish to apply.")
        # Also reset user profile so onboarding triggers on next launch
        profile_path = Path.home() / "AppData" / "Roaming" / "LittleFish" / "user_profile.json"
        try:
            if profile_path.exists():
                profile_path.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # About
    # ------------------------------------------------------------------

    def _show_about(self):
        ver = _read_version()
        QMessageBox.about(
            self, "About Little Fish",
            f"<h3>Little Fish</h3>"
            f"<p>Version {ver.get('version', '?')} ({ver.get('channel', 'stable')})</p>"
            f"<p>A living desktop companion.</p>"
            f"<p>Built with PyQt6 + Groq AI</p>"
            f"<hr>"
            f"<p>by Luca & Leonardo</p>"
        )

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def _on_rollback(self):
        backup_dir = PROJECT_ROOT / "_backup"
        if not backup_dir.exists():
            QMessageBox.information(self, "Rollback", "No backup found.")
            return
        reply = QMessageBox.question(
            self, "Rollback",
            "Restore from the last backup?\n"
            "The launcher will quit and restart with the previous version.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Write a rollback batch script (same approach as update)
        launcher_exe = PROJECT_ROOT / "LittleFishLauncher.exe"
        script_lines = [
            "@echo off",
            "echo Rolling back Little Fish...",
            "",
            ":wait_launcher",
            "timeout /t 1 /nobreak >nul",
            'tasklist /FI "IMAGENAME eq LittleFishLauncher.exe" 2>nul '
            "| findstr /I /C:\"LittleFishLauncher\" >nul",
            "if %ERRORLEVEL%==0 goto wait_launcher",
            "",
            'tasklist /FI "IMAGENAME eq LittleFish.exe" 2>nul '
            "| findstr /I /C:\"LittleFish.exe\" >nul",
            "if %ERRORLEVEL%==0 (",
            "    taskkill /F /IM LittleFish.exe >nul 2>&1",
            "    timeout /t 2 /nobreak >nul",
            ")",
            "",
            f'xcopy /E /Y /Q "{backup_dir}\\" "{PROJECT_ROOT}\\"',
            f'start "" "{launcher_exe}"',
            'del "%~f0"',
        ]
        script = PROJECT_ROOT / "_rollback.cmd"
        script.write_text("\r\n".join(script_lines), encoding="utf-8")

        # Stop fish, launch script, quit
        app = QApplication.instance()
        for w in app.topLevelWidgets():
            if hasattr(w, "_stop_fish"):
                w._stop_fish()
                break
        subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            cwd=str(PROJECT_ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        QApplication.quit()

    # ------------------------------------------------------------------
    # Mood Log Viewer
    # ------------------------------------------------------------------

    def _show_mood_log(self):
        """Show a filterable mood log viewer dialog."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Mood Log")
        dlg.setFixedSize(420, 460)
        dlg.setStyleSheet(DARK_STYLE)

        layout = QVBoxLayout(dlg)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        filter_combo = QComboBox()
        filter_combo.addItems(["All", "happy", "curious", "excited", "focused",
                                "bored", "sleepy", "worried"])
        filter_combo.setFixedWidth(100)
        filter_row.addWidget(filter_combo)
        filter_row.addWidget(QLabel("Range:"))
        range_combo = QComboBox()
        range_combo.addItems(["Today", "Last 24h", "Last 7 days", "All"])
        range_combo.setFixedWidth(100)
        filter_row.addWidget(range_combo)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Timeline list
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet(
            "background-color: #1E293B; color: #E2E8F0; border: 1px solid #334155; "
            "border-radius: 4px; font-family: Consolas, monospace; font-size: 11px;")
        layout.addWidget(log_text)

        # Stats summary
        stats_label = QLabel("")
        stats_label.setObjectName("subtitle")
        stats_label.setWordWrap(True)
        layout.addWidget(stats_label)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.close)
        layout.addWidget(close_btn)

        def _refresh_log():
            log = SharedState.read_mood_log()
            mood_filter = filter_combo.currentText()
            range_filter = range_combo.currentText()

            now = datetime.datetime.now()
            filtered = []
            for entry in log:
                t_str = entry.get("time", "")
                mood = entry.get("mood", "")
                if mood_filter != "All" and mood != mood_filter:
                    continue
                try:
                    t = datetime.datetime.fromisoformat(t_str)
                except (ValueError, TypeError):
                    continue
                if range_filter == "Today" and t.date() != now.date():
                    continue
                elif range_filter == "Last 24h" and (now - t).total_seconds() > 86400:
                    continue
                elif range_filter == "Last 7 days" and (now - t).total_seconds() > 604800:
                    continue
                filtered.append(entry)

            # Build text
            lines = []
            for entry in reversed(filtered):
                t_str = entry.get("time", "?")
                mood = entry.get("mood", "?")
                color = MOOD_COLORS.get(mood, "#94A3B8")
                try:
                    t = datetime.datetime.fromisoformat(t_str)
                    time_fmt = t.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    time_fmt = t_str
                lines.append(
                    f'<span style="color:{color}">&#9679;</span> '
                    f'<span style="color:#94A3B8">{time_fmt}</span> '
                    f'&mdash; <b>{mood}</b>')
            log_text.setHtml("<br>".join(lines) if lines else
                             '<span style="color:#64748B">No entries found</span>')

            # Stats
            if filtered:
                counts: dict[str, int] = {}
                for e in filtered:
                    m = e.get("mood", "happy")
                    counts[m] = counts.get(m, 0) + 1
                total = sum(counts.values())
                parts = [f"{m}: {c} ({c*100//total}%)" for m, c in
                         sorted(counts.items(), key=lambda x: -x[1])]
                stats_label.setText(f"{total} entries | " + ", ".join(parts))
            else:
                stats_label.setText("No entries")

        filter_combo.currentTextChanged.connect(lambda _: _refresh_log())
        range_combo.currentTextChanged.connect(lambda _: _refresh_log())
        _refresh_log()

        dlg.exec()

    # ------------------------------------------------------------------
    # Launcher preferences (auto-launch, etc.)
    # ------------------------------------------------------------------

    def _load_launcher_prefs(self) -> dict:
        pref_path = STATE_PATH.parent / "launcher_prefs.json"
        try:
            if pref_path.exists():
                return json.loads(pref_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return {"auto_launch": True}

    def _save_launcher_prefs(self, prefs: dict):
        pref_path = STATE_PATH.parent / "launcher_prefs.json"
        try:
            pref_path.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _on_auto_launch_toggle(self, checked: bool):
        prefs = self._load_launcher_prefs()
        prefs["auto_launch"] = checked
        self._save_launcher_prefs(prefs)

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self._refresh_timer.start()
        # Show rollback if backup exists
        backup_dir = PROJECT_ROOT / "_backup"
        self._rollback_btn.setVisible(backup_dir.exists())

    def hideEvent(self, event):
        super().hideEvent(event)
        self._refresh_timer.stop()

    def closeEvent(self, event):
        """Minimize to tray instead of quitting."""
        event.ignore()
        self.hide()


# ---------------------------------------------------------------------------
# Launcher Tray App
# ---------------------------------------------------------------------------

class LauncherApp:
    """System tray launcher for Little Fish."""

    def __init__(self, app: QApplication):
        self._app = app
        self._fish_process: subprocess.Popen | None = None
        self._dashboard: DashboardWindow | None = None

        # Clean up stale update staging/scripts from a previous update
        for stale in ("_update_staging", "_apply_update.cmd", "_rollback.cmd"):
            p = PROJECT_ROOT / stale
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass

        # Tray icon
        self._tray = QSystemTrayIcon(_make_mood_icon("happy", False), app)
        self._tray.setToolTip("Little Fish Launcher")
        self._build_menu()
        self._tray.activated.connect(self._on_tray_click)
        self._tray.show()

        # Poll state every 5s
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._poll_state)
        self._poll_timer.start()

        # Daily update check
        self._update_check_timer = QTimer()
        self._update_check_timer.setInterval(86400000)  # 24h
        self._update_check_timer.timeout.connect(self._check_updates)

        # Auto-launch fish on start
        prefs = self._load_launcher_prefs()
        if prefs.get("auto_launch", True):
            # Small delay so the tray icon appears first
            QTimer.singleShot(1500, self._launch_fish)

        # Initial poll
        self._poll_state()

        # Show dashboard window immediately on launch
        QTimer.singleShot(200, self._show_dashboard)

    def _build_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #5BA8C8;
                color: #0F172A;
            }
        """)

        dashboard_action = menu.addAction("Dashboard")
        dashboard_action.triggered.connect(self._show_dashboard)
        menu.addSeparator()

        self._launch_action = menu.addAction("Launch Fish")
        self._launch_action.triggered.connect(self._launch_fish)
        self._stop_action = menu.addAction("Stop Fish")
        self._stop_action.triggered.connect(self._stop_fish)
        menu.addSeparator()

        settings_action = menu.addAction("Open Settings")
        settings_action.triggered.connect(self._open_settings_tray)
        menu.addSeparator()

        quit_action = menu.addAction("Quit Launcher")
        quit_action.triggered.connect(self._quit)

        self._tray.setContextMenu(menu)

    def _poll_state(self):
        # Validate PID is actually alive
        _clean_stale_state()

        state = SharedState.read()
        alive = state.get("alive", False)
        mood = state.get("dominant_emotion", "happy")

        self._tray.setIcon(_make_mood_icon(mood, alive))

        if alive:
            self._tray.setToolTip(
                f"Little Fish — {mood} | {state.get('uptime_human', '')}"
            )
            self._launch_action.setEnabled(False)
            self._stop_action.setEnabled(True)
        else:
            self._tray.setToolTip("Little Fish — Offline")
            self._launch_action.setEnabled(True)
            self._stop_action.setEnabled(False)

        if self._fish_process and self._fish_process.poll() is not None:
            self._fish_process = None

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_dashboard()

    def _show_dashboard(self):
        if self._dashboard is None:
            self._dashboard = DashboardWindow()
            self._dashboard.launch_fish_requested.connect(self._launch_fish)
            self._dashboard.stop_fish_requested.connect(self._stop_fish)
            self._dashboard.check_for_updates()
            self._update_check_timer.start()

        if self._dashboard.isVisible():
            self._dashboard.raise_()
            self._dashboard.activateWindow()
        else:
            self._dashboard.show()
            self._dashboard.raise_()

    def _launch_fish(self):
        # Clean stale state first — if PID is dead, mark alive=False
        _clean_stale_state()
        state = SharedState.read()
        if state.get("alive"):
            return

        # When frozen (PyInstaller), look for LittleFish.exe next to launcher
        if getattr(sys, "frozen", False):
            fish_exe = Path(sys.executable).parent / "LittleFish.exe"
            if fish_exe.exists():
                try:
                    self._fish_process = subprocess.Popen(
                        [str(fish_exe)],
                        cwd=str(fish_exe.parent),
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except OSError:
                    pass
                return

        # Development mode — run main.py
        main_py = PROJECT_ROOT / "main.py"
        if not main_py.exists():
            return
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        python = str(venv_python) if venv_python.exists() else sys.executable
        try:
            self._fish_process = subprocess.Popen(
                [python, str(main_py)],
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except OSError:
            pass

    def _stop_fish(self):
        state = SharedState.read()
        pid = state.get("pid")
        killed = False
        if pid and _is_fish_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                killed = True
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if self._fish_process:
            try:
                self._fish_process.terminate()
                killed = True
            except OSError:
                pass
            self._fish_process = None
        # Always clean up stale state
        _clean_stale_state()
        if not killed:
            # Force mark as dead if nothing was actually killed
            try:
                s = SharedState.read()
                s["alive"] = False
                s["updated_at"] = datetime.datetime.now().isoformat()
                STATE_PATH.write_text(json.dumps(s, indent=2), encoding="utf-8")
            except OSError:
                pass

    def _check_updates(self):
        if self._dashboard:
            self._dashboard.check_for_updates()

    def _open_settings_tray(self):
        """Signal the running fish to open its settings dialog, or open standalone."""
        state = SharedState.read()
        if state.get("alive"):
            flag = STATE_PATH.parent / "open_settings_flag"
            try:
                flag.write_text("1", encoding="utf-8")
            except OSError:
                pass
        else:
            # Open standalone settings dialog
            settings_path = _SETTINGS_PATH
            try:
                config = {}
                if settings_path.exists():
                    config = json.loads(settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                config = {}
            from config.config_ui import StandaloneSettingsDialog
            dlg = StandaloneSettingsDialog(config)
            dlg.exec()

    def _load_launcher_prefs(self) -> dict:
        pref_path = STATE_PATH.parent / "launcher_prefs.json"
        try:
            if pref_path.exists():
                return json.loads(pref_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return {"auto_launch": True}

    def _quit(self):
        self._tray.hide()
        if self._dashboard:
            self._dashboard.close()
        self._app.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Single-instance guard — prevent duplicate launcher processes
    import ctypes
    _kernel32 = ctypes.windll.kernel32
    _mutex = _kernel32.CreateMutexW(None, True, "LittleFishLauncher_SingleInstance")
    if _kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        _kernel32.CloseHandle(_mutex)
        sys.exit(0)
    # _mutex intentionally leaked — must stay alive for process lifetime

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    launcher = LauncherApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
