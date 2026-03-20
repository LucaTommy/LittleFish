"""
Whack-a-Bubble — bubbles appear on screen, click to pop them.
Fish dashes to the bubble on click and pops it on contact.

Personality hooks:
  - Pop a bubble → tiny celebration, bounce
  - Miss badly → covers face, embarrassed
  - Fast pops → excited streak
  - Timeout → bubble drifts away, fish looks disappointed
"""

import random
import math
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QRadialGradient
from PyQt6.QtWidgets import QApplication

from games.game_manager import DesktopGame, GameState

# ── Bubble types ───────────────────────────────────────────────────────

BUBBLE_COLORS = [
    QColor(120, 200, 255, 180),   # Blue
    QColor(255, 150, 200, 180),   # Pink
    QColor(180, 255, 150, 180),   # Green
    QColor(255, 220, 100, 180),   # Gold
    QColor(200, 150, 255, 180),   # Purple
]


@dataclass
class Bubble:
    x: float
    y: float
    radius: float
    color: QColor
    points: int = 10
    lifetime: float = 3.0       # seconds before it drifts away
    age: float = 0.0
    popped: bool = False
    missed: bool = False
    pop_timer: float = 0.0      # animation timer after pop
    wobble_phase: float = field(default_factory=lambda: random.uniform(0, 6.28))
    drift_vx: float = field(default_factory=lambda: random.uniform(-15, 15))
    drift_vy: float = field(default_factory=lambda: random.uniform(-20, -5))


# ── The Game ───────────────────────────────────────────────────────────

class WhackABubbleGame(DesktopGame):

    name = "Whack-a-Bubble"
    description = "Pop the bubbles!"

    def __init__(self, fish_widget):
        super().__init__(fish_widget)
        self._bubbles: list[Bubble] = []
        self._spawn_timer: float = 0.0
        self._spawn_interval: float = 1.5
        self._max_bubbles: int = 4
        self._pops: int = 0
        self._misses: int = 0
        self._miss_streak: int = 0
        self._pop_streak: int = 0
        self._round_duration: float = 45.0  # seconds
        self._difficulty_ramp: float = 0.0

        # Fish dashing state
        self._dash_target: QPoint | None = None
        self._dash_speed: float = 1200.0  # px/s
        self._target_bubble_idx: int = -1

        # Pop effects
        self._pop_effects: list[dict] = []  # {x, y, timer, color, particles}

        # Personality
        self._embarrassed: bool = False
        self._embarr_timer: float = 0.0

        self._screen_w = 0
        self._screen_h = 0

    def _on_game_start(self):
        screen = QApplication.primaryScreen().geometry()
        self._screen_w = screen.width()
        self._screen_h = screen.height()
        self._bubbles.clear()
        self._pop_effects.clear()
        self._pops = 0
        self._misses = 0
        self._miss_streak = 0
        self._pop_streak = 0
        self._spawn_timer = 0.0
        self._dash_target = None
        self._target_bubble_idx = -1
        self._embarrassed = False
        self._embarr_timer = 0.0

    def _on_tick(self):
        if self.state != GameState.PLAYING:
            self.update()
            return

        dt = 0.016
        self._game_time += dt
        self._difficulty_ramp = min(self._game_time / self._round_duration, 1.0)

        # ── Time's up? ──────────────────────────────────────────────
        if self._game_time >= self._round_duration:
            self._determine_ending()
            self.end_game()
            return

        # ── Dash fish toward target ─────────────────────────────────
        if self._dash_target is not None:
            fc = self._fish_center()
            dx = self._dash_target.x() - fc.x()
            dy = self._dash_target.y() - fc.y()
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 20:
                # Arrived — check if bubble is still there
                self._on_dash_arrived()
                self._dash_target = None
            else:
                step = self._dash_speed * dt
                ratio = min(step / dist, 1.0)
                nx = self.fish.pos().x() + int(dx * ratio)
                ny = self.fish.pos().y() + int(dy * ratio)
                self._teleport_fish(nx, ny)

        # ── Spawn bubbles ───────────────────────────────────────────
        active_count = sum(1 for b in self._bubbles if not b.popped and not b.missed)
        self._spawn_timer += dt
        interval = self._spawn_interval * (1.0 - 0.4 * self._difficulty_ramp)
        max_b = self._max_bubbles + int(self._difficulty_ramp * 3)
        if self._spawn_timer >= interval and active_count < max_b:
            self._spawn_timer = 0.0
            self._spawn_bubble()

        # ── Update bubbles ──────────────────────────────────────────
        for i, bub in enumerate(self._bubbles):
            if bub.popped:
                bub.pop_timer -= dt
                continue
            if bub.missed:
                bub.drift_vy -= 10 * dt
                bub.y += bub.drift_vy * dt
                bub.x += bub.drift_vx * dt
                continue

            bub.age += dt
            bub.wobble_phase += dt * 2.0
            bub.x += math.sin(bub.wobble_phase) * 0.3
            bub.y += bub.drift_vy * dt * 0.2

            # Timeout — bubble drifts away
            if bub.age >= bub.lifetime:
                bub.missed = True
                self._misses += 1
                self._miss_streak += 1
                self._pop_streak = 0

                # Personality: embarrassment on miss streak
                if self._miss_streak >= 2:
                    self._embarrassed = True
                    self._embarr_timer = 1.5
                    self._emit("miss_badly")

                if i == self._target_bubble_idx:
                    self._dash_target = None
                    self._target_bubble_idx = -1

        # ── Clean up ────────────────────────────────────────────────
        self._bubbles = [b for b in self._bubbles
                         if not (b.popped and b.pop_timer <= 0)
                         and not (b.missed and b.y < -100)]

        # Update target index after cleanup
        if self._target_bubble_idx >= len(self._bubbles):
            self._target_bubble_idx = -1
            self._dash_target = None

        # ── Embarrassment cooldown ──────────────────────────────────
        if self._embarrassed:
            self._embarr_timer -= dt
            if self._embarr_timer <= 0:
                self._embarrassed = False

        # ── Update pop effects ──────────────────────────────────────
        for eff in self._pop_effects:
            eff["timer"] -= dt
            for p in eff["particles"]:
                p["x"] += p["vx"] * dt
                p["y"] += p["vy"] * dt
                p["vy"] += 200 * dt  # gravity
        self._pop_effects = [e for e in self._pop_effects if e["timer"] > 0]

        self.update()

    def _spawn_bubble(self):
        margin = 120
        x = random.uniform(margin, self._screen_w - margin)
        y = random.uniform(self._screen_h * 0.2, self._screen_h * 0.75)
        radius = random.uniform(25, 45)
        color = random.choice(BUBBLE_COLORS)
        lifetime = max(1.5, 3.5 - self._difficulty_ramp * 1.5)
        points = int(10 + (50 - radius))  # Smaller = more points
        self._bubbles.append(Bubble(
            x=x, y=y, radius=radius, color=color,
            points=points, lifetime=lifetime,
        ))

    def _on_dash_arrived(self):
        """Fish arrived at dash target — pop the bubble if still there."""
        if self._target_bubble_idx < 0:
            return
        if self._target_bubble_idx >= len(self._bubbles):
            return
        bub = self._bubbles[self._target_bubble_idx]
        if bub.popped or bub.missed:
            # Too late
            self._emit("miss_pop")
            return

        # Pop it!
        bub.popped = True
        bub.pop_timer = 0.3
        self.score += bub.points
        self._pops += 1
        self._pop_streak += 1
        self._miss_streak = 0
        self._embarrassed = False

        # Create pop effect
        particles = []
        for _ in range(8):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(80, 200)
            particles.append({
                "x": bub.x, "y": bub.y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed - 50,
            })
        self._pop_effects.append({
            "x": bub.x, "y": bub.y,
            "timer": 0.5,
            "color": bub.color,
            "particles": particles,
        })

        # Events
        if self._pop_streak >= 3:
            self._emit("pop_streak")
        else:
            self._emit("pop")

        self._target_bubble_idx = -1

    def _determine_ending(self):
        if self._pops == 0:
            self._emit("total_fail")
        elif self._misses > self._pops * 2:
            self._emit("bad_game")
        elif self._new_high_score:
            self._emit("new_record")
        else:
            self._emit("decent_game")

    # ── Input ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if self.state != GameState.PLAYING:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        click = event.pos()

        # Find closest bubble to click
        best_idx = -1
        best_dist = float("inf")
        for i, bub in enumerate(self._bubbles):
            if bub.popped or bub.missed:
                continue
            dx = click.x() - bub.x
            dy = click.y() - bub.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < bub.radius + 30 and dist < best_dist:  # Generous hitbox
                best_dist = dist
                best_idx = i

        if best_idx >= 0:
            bub = self._bubbles[best_idx]
            self._dash_target = QPoint(int(bub.x) - self.fish.width() // 2,
                                       int(bub.y) - self.fish.height() // 2)
            self._target_bubble_idx = best_idx
        else:
            # Clicked empty space — miss
            self._miss_streak += 1
            self._pop_streak = 0
            if self._miss_streak >= 3:
                self._embarrassed = True
                self._embarr_timer = 2.0
                self._emit("miss_badly")

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
                       "🫧 Whack-a-Bubble 🫧")
            self._draw_countdown(p)
            p.end()
            return

        if self.state == GameState.GAME_OVER:
            self._draw_game_over(p)
            p.end()
            return

        # ── Playing ─────────────────────────────────────────────────
        p.fillRect(self.rect(), QColor(0, 0, 30, 10))

        # Draw bubbles
        for bub in self._bubbles:
            if bub.popped:
                continue
            alpha_fade = 1.0
            if bub.missed:
                alpha_fade = 0.3
            elif bub.age > bub.lifetime * 0.7:
                # Flicker when about to expire
                alpha_fade = 0.5 + 0.5 * math.sin(bub.age * 15)

            r = bub.radius
            # Gradient bubble
            center = QPoint(int(bub.x), int(bub.y))
            grad = QRadialGradient(center.x() - r * 0.3, center.y() - r * 0.3, r * 1.2)
            c = QColor(bub.color)
            c.setAlpha(int(c.alpha() * alpha_fade))
            grad.setColorAt(0, QColor(255, 255, 255, int(120 * alpha_fade)))
            grad.setColorAt(0.4, c)
            grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), int(40 * alpha_fade)))

            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(255, 255, 255, int(80 * alpha_fade)), 1.5))
            p.drawEllipse(center, int(r), int(r))

            # Highlight
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, int(60 * alpha_fade))))
            p.drawEllipse(int(bub.x - r * 0.35), int(bub.y - r * 0.4),
                          int(r * 0.4), int(r * 0.25))

            # Points label
            if not bub.missed:
                p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                p.setPen(QPen(QColor(255, 255, 255, int(180 * alpha_fade))))
                p.drawText(QRectF(bub.x - r, bub.y - r, r * 2, r * 2),
                           Qt.AlignmentFlag.AlignCenter, str(bub.points))

        # Draw pop effects
        for eff in self._pop_effects:
            alpha = int(255 * (eff["timer"] / 0.5))
            for part in eff["particles"]:
                c = QColor(eff["color"])
                c.setAlpha(alpha)
                p.setBrush(QBrush(c))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(int(part["x"]), int(part["y"]), 5, 5)

        # HUD
        self._draw_score_hud(p)

        # Timer bar
        remaining = max(0, self._round_duration - self._game_time)
        frac = remaining / self._round_duration
        bar_w = int(200 * frac)
        p.fillRect(20, 50, 200, 8, QColor(60, 60, 80, 150))
        bar_color = QColor(100, 220, 100) if frac > 0.3 else QColor(255, 100, 80)
        p.fillRect(20, 50, bar_w, 8, bar_color)

        # Streak indicator
        if self._pop_streak >= 3:
            p.setFont(QFont("Segoe UI", 14))
            p.setPen(QPen(QColor(255, 200, 50, 200)))
            p.drawText(20, 82, f"🔥 x{self._pop_streak}")

        # Embarrassment
        if self._embarrassed:
            p.setFont(QFont("Segoe UI", 12))
            p.setPen(QPen(QColor(255, 150, 150, 180)))
            p.drawText(20, 100, "🙈 Oh no...")

        p.end()
