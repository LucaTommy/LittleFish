"""
Lightweight game manager for cursor-based desktop games.
Games run as transparent overlay windows on the desktop.
The fish widget physically moves during gameplay.
"""

import json
from pathlib import Path
from enum import Enum
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QApplication

# ── High-score persistence ─────────────────────────────────────────────
_APPDATA = Path.home() / "AppData" / "Roaming" / "LittleFish"
_SCORES_FILE = _APPDATA / "high_scores.json"


def _load_scores() -> dict:
    try:
        return json.loads(_SCORES_FILE.read_text())
    except Exception:
        return {}


def _save_scores(scores: dict):
    try:
        _APPDATA.mkdir(parents=True, exist_ok=True)
        _SCORES_FILE.write_text(json.dumps(scores, indent=2))
    except Exception:
        pass


# ── Game states ────────────────────────────────────────────────────────

class GameState(Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    GAME_OVER = "game_over"


# ── Base class for overlay games ───────────────────────────────────────

class DesktopGame(QWidget):
    """
    Transparent full-screen overlay that hosts a cursor-based game.
    Fish widget is passed in so the game can physically move the fish.
    """

    name: str = "Untitled"
    description: str = ""

    def __init__(self, fish_widget):
        super().__init__(None)
        self.fish = fish_widget
        self.state = GameState.WAITING
        self.score: int = 0
        self.high_score: int = _load_scores().get(self.name, 0)
        self._new_high_score = False

        # Full-screen transparent overlay
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Cover the primary screen
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # Game tick timer
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(16)  # ~60fps
        self._tick_timer.timeout.connect(self._on_tick)

        # Countdown
        self._countdown = 3
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_countdown)

        # Game duration tracking
        self._game_time: float = 0.0

        # Store original fish position for restoration
        self._original_fish_pos: Optional[QPoint] = None

        # Callback set by fish_widget
        self.on_game_event = None  # callable(str)

    def start_game(self):
        """Show overlay, start countdown, then play."""
        self._original_fish_pos = QPoint(self.fish.pos())
        self.score = 0
        self._game_time = 0.0
        self._new_high_score = False
        self.state = GameState.WAITING
        self._countdown = 3
        self.show()
        self.raise_()
        self._countdown_timer.start()
        self._emit("start")
        self.update()

    def end_game(self):
        """End the game, save score, emit result."""
        self.state = GameState.GAME_OVER
        self._tick_timer.stop()
        self._save_score()
        self.update()
        # Auto-close after 2.5s
        QTimer.singleShot(2500, self._cleanup)

    def _cleanup(self):
        self._tick_timer.stop()
        self._countdown_timer.stop()
        if self._original_fish_pos:
            self.fish.move(self._original_fish_pos)
        self.close()
        self.deleteLater()

    def _on_countdown(self):
        self._countdown -= 1
        self.update()
        if self._countdown <= 0:
            self._countdown_timer.stop()
            self.state = GameState.PLAYING
            self._tick_timer.start()
            self._on_game_start()

    def _on_game_start(self):
        """Override: called when countdown hits 0 and game begins."""
        pass

    def _on_tick(self):
        """Override: called every frame during PLAYING."""
        self._game_time += 0.016
        self.update()

    def _save_score(self):
        scores = _load_scores()
        old = scores.get(self.name, 0)
        if self.score > old:
            self.high_score = self.score
            self._new_high_score = True
            scores[self.name] = self.score
            _save_scores(scores)
        else:
            self._new_high_score = False

    def _emit(self, event: str):
        if self.on_game_event:
            self.on_game_event(event)

    def _move_fish_to(self, x: int, y: int, speed: float = 800.0):
        """Smoothly move the fish to a position."""
        self.fish._walk_to(x, y, speed=speed)

    def _teleport_fish(self, x: int, y: int):
        """Instantly move the fish."""
        self.fish.move(x, y)

    def _fish_center(self) -> QPoint:
        pos = self.fish.pos()
        return QPoint(pos.x() + self.fish.width() // 2,
                      pos.y() + self.fish.height() // 2)

    def _fish_rect(self) -> QRect:
        return self.fish.geometry()

    # ── Common drawing helpers ─────────────────────────────────────────

    def _draw_countdown(self, p: QPainter):
        if self.state != GameState.WAITING or self._countdown <= 0:
            return
        p.setFont(QFont("Segoe UI", 72, QFont.Weight.Bold))
        p.setPen(QPen(QColor(255, 255, 255, 220)))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                   str(self._countdown))

    def _draw_score_hud(self, p: QPainter):
        p.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        p.setPen(QPen(QColor(255, 255, 255, 200)))
        p.drawText(20, 35,
                   f"{self.name}   Score: {self.score}   Best: {self.high_score}")

    def _draw_game_over(self, p: QPainter):
        if self.state != GameState.GAME_OVER:
            return
        p.fillRect(self.rect(), QColor(0, 0, 0, 100))
        p.setFont(QFont("Segoe UI", 48, QFont.Weight.Bold))
        p.setPen(QPen(QColor(255, 255, 255, 230)))
        msg = f"Score: {self.score}"
        if self._new_high_score:
            msg = f"New Best! {self.score}"
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, msg)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._tick_timer.stop()
            self._countdown_timer.stop()
            self.state = GameState.GAME_OVER
            self._emit("quit")
            self._cleanup()
