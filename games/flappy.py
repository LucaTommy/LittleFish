"""
Flappy Swim — side-scrolling obstacle course on the desktop.
Click or press space to flap. Fish physically moves on screen.

Personality hooks:
  - Dies immediately → "I meant to do that."
  - Dies after a long run → genuine gutted reaction
  - Passes 10 pipes → proud celebration
  - New high score → ecstatic
"""

import random
import math
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PyQt6.QtWidgets import QApplication

from games.game_manager import DesktopGame, GameState


@dataclass
class Pipe:
    x: float                   # Left edge x
    gap_y: float               # Center of the gap
    gap_size: float = 180.0    # Vertical gap size in pixels
    width: float = 60.0
    passed: bool = False
    color: QColor = None

    def __post_init__(self):
        if self.color is None:
            g = random.randint(100, 180)
            self.color = QColor(50, g, 80, 200)


class FlappyGame(DesktopGame):

    name = "Flappy Swim"
    description = "Flap through the pipes!"

    def __init__(self, fish_widget):
        super().__init__(fish_widget)
        self._pipes: list[Pipe] = []

        # Physics
        self._fish_y: float = 0.0
        self._fish_vy: float = 0.0
        self._gravity: float = 900.0       # px/s²
        self._flap_strength: float = -320.0  # px/s upward
        self._scroll_speed: float = 200.0   # px/s horizontal

        # Fish is locked to a fixed X position on screen
        self._fish_screen_x: float = 0.0

        # Pipe spawning
        self._pipe_timer: float = 0.0
        self._pipe_interval: float = 2.2     # seconds

        # Stats
        self._pipes_passed: int = 0
        self._died_early: bool = False

        self._screen_w = 0
        self._screen_h = 0

        # Ground/ceiling
        self._ground_y: float = 0.0
        self._ceiling_y: float = 0.0

    def _on_game_start(self):
        screen = QApplication.primaryScreen().geometry()
        self._screen_w = screen.width()
        self._screen_h = screen.height()
        self._ground_y = self._screen_h - 60
        self._ceiling_y = 40

        self._pipes.clear()
        self._fish_y = self._screen_h * 0.45
        self._fish_vy = 0.0
        self._pipes_passed = 0
        self._died_early = False
        self._pipe_timer = 0.0

        # Fish stays at 25% from left
        self._fish_screen_x = self._screen_w * 0.25

        # Position fish at starting spot
        self._teleport_fish(
            int(self._fish_screen_x) - self.fish.width() // 2,
            int(self._fish_y) - self.fish.height() // 2,
        )

    def _on_tick(self):
        if self.state != GameState.PLAYING:
            self.update()
            return

        dt = 0.016
        self._game_time += dt

        # ── Fish physics ────────────────────────────────────────────
        self._fish_vy += self._gravity * dt
        self._fish_y += self._fish_vy * dt

        # Move the actual fish widget
        self._teleport_fish(
            int(self._fish_screen_x) - self.fish.width() // 2,
            int(self._fish_y) - self.fish.height() // 2,
        )

        # Ceiling/ground collision
        if self._fish_y <= self._ceiling_y + self.fish.height() // 2:
            self._fish_y = self._ceiling_y + self.fish.height() // 2
            self._fish_vy = 0
        if self._fish_y >= self._ground_y - self.fish.height() // 2:
            self._on_death()
            return

        # ── Scroll pipes ────────────────────────────────────────────
        speed = self._scroll_speed + self._pipes_passed * 3  # Slight speedup
        for pipe in self._pipes:
            pipe.x -= speed * dt

        # ── Spawn pipes ─────────────────────────────────────────────
        self._pipe_timer += dt
        interval = max(1.2, self._pipe_interval - self._pipes_passed * 0.03)
        if self._pipe_timer >= interval:
            self._pipe_timer = 0.0
            self._spawn_pipe()

        # ── Collision detection ─────────────────────────────────────
        fish_cx = self._fish_screen_x
        fish_cy = self._fish_y
        fish_r = self.fish.width() * 0.35  # Collision radius (forgiving)

        for pipe in self._pipes:
            # Check if fish is horizontally in the pipe zone
            if pipe.x < fish_cx + fish_r and pipe.x + pipe.width > fish_cx - fish_r:
                # Check if outside the gap
                gap_top = pipe.gap_y - pipe.gap_size / 2
                gap_bottom = pipe.gap_y + pipe.gap_size / 2
                if fish_cy - fish_r < gap_top or fish_cy + fish_r > gap_bottom:
                    self._on_death()
                    return

            # Check if pipe has been passed
            if not pipe.passed and pipe.x + pipe.width < fish_cx - fish_r:
                pipe.passed = True
                self.score += 1
                self._pipes_passed += 1

                # Milestone celebrations
                if self._pipes_passed == 10:
                    self._emit("milestone_10")
                elif self._pipes_passed == 25:
                    self._emit("milestone_25")

        # ── Cleanup offscreen pipes ─────────────────────────────────
        self._pipes = [p for p in self._pipes if p.x + p.width > -50]

        self.update()

    def _spawn_pipe(self):
        min_gap_y = self._ceiling_y + 120
        max_gap_y = self._ground_y - 120
        gap_y = random.uniform(min_gap_y, max_gap_y)
        # Gap shrinks over time
        gap_size = max(120, 200 - self._pipes_passed * 2)
        self._pipes.append(Pipe(
            x=self._screen_w + 20,
            gap_y=gap_y,
            gap_size=gap_size,
        ))

    def _on_death(self):
        if self._pipes_passed <= 1:
            self._died_early = True
            self._emit("died_immediately")
        elif self._pipes_passed >= 10:
            self._emit("died_long_run")
        else:
            self._emit("died_normal")
        self.end_game()

    def _flap(self):
        if self.state != GameState.PLAYING:
            return
        self._fish_vy = self._flap_strength

    # ── Input ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._flap()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._flap()
        elif event.key() == Qt.Key.Key_Escape:
            super().keyPressEvent(event)

    # ── Rendering ──────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.state == GameState.WAITING:
            p.fillRect(self.rect(), QColor(0, 0, 0, 40))
            p.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
            p.setPen(QPen(QColor(255, 255, 255, 200)))
            r = self.rect()
            r.setTop(r.center().y() - 80)
            p.drawText(r, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       "🐟 Flappy Swim 🐟")

            p.setFont(QFont("Segoe UI", 14))
            r2 = self.rect()
            r2.setTop(r.center().y() + 10)
            p.drawText(r2, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       "Click or Space to flap!")

            self._draw_countdown(p)
            p.end()
            return

        if self.state == GameState.GAME_OVER:
            self._draw_game_over(p)
            p.end()
            return

        # ── Playing ─────────────────────────────────────────────────
        # Sky gradient (very subtle)
        p.fillRect(self.rect(), QColor(20, 30, 60, 20))

        # Ground
        p.fillRect(0, int(self._ground_y), self._screen_w,
                   self._screen_h - int(self._ground_y),
                   QColor(80, 60, 40, 100))
        p.setPen(QPen(QColor(100, 180, 80, 150), 3))
        p.drawLine(0, int(self._ground_y), self._screen_w, int(self._ground_y))

        # Ceiling
        p.fillRect(0, 0, self._screen_w, int(self._ceiling_y),
                   QColor(40, 40, 60, 80))

        # Pipes
        for pipe in self._pipes:
            x = int(pipe.x)
            w = int(pipe.width)
            gap_top = int(pipe.gap_y - pipe.gap_size / 2)
            gap_bottom = int(pipe.gap_y + pipe.gap_size / 2)

            # Top pipe
            color = pipe.color
            darker = QColor(color.red() - 20, color.green() - 20,
                            color.blue() - 20, color.alpha())
            p.fillRect(x, int(self._ceiling_y), w, gap_top - int(self._ceiling_y), color)
            # Pipe cap (top)
            p.fillRect(x - 4, gap_top - 16, w + 8, 16, darker)

            # Bottom pipe
            p.fillRect(x, gap_bottom, w, int(self._ground_y) - gap_bottom, color)
            # Pipe cap (bottom)
            p.fillRect(x - 4, gap_bottom, w + 8, 16, darker)

            # Highlight stripe
            p.fillRect(x + 6, int(self._ceiling_y), 4,
                       gap_top - int(self._ceiling_y),
                       QColor(255, 255, 255, 40))
            p.fillRect(x + 6, gap_bottom, 4,
                       int(self._ground_y) - gap_bottom,
                       QColor(255, 255, 255, 40))

        # HUD
        self._draw_score_hud(p)

        # Big score in center
        p.setFont(QFont("Segoe UI", 36, QFont.Weight.Bold))
        p.setPen(QPen(QColor(255, 255, 255, 60)))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignHCenter
                   | Qt.AlignmentFlag.AlignTop, f"\n\n{self.score}")

        p.end()
