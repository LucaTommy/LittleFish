"""
Catch & Snack — food items fall from the top of the screen.
Move the mouse to guide the fish and catch them.

Personality hooks:
  - Miss 3 in a row → fish gets visibly frustrated, tries harder or gives up
  - Catch streak → tiny celebration particle
  - Game over → dramatic reaction based on performance
"""

import random
import math
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QPainterPath
from PyQt6.QtWidgets import QApplication

from games.game_manager import DesktopGame, GameState

# ── Food items ─────────────────────────────────────────────────────────

FOOD_KINDS = [
    {"emoji": "🍕", "points": 10, "color": QColor(255, 200, 50)},
    {"emoji": "🍩", "points": 15, "color": QColor(200, 130, 70)},
    {"emoji": "🍎", "points": 10, "color": QColor(220, 50, 50)},
    {"emoji": "🍪", "points": 20, "color": QColor(180, 140, 80)},
    {"emoji": "⭐", "points": 50, "color": QColor(255, 215, 0)},
    {"emoji": "🐛", "points": -10, "color": QColor(100, 160, 60)},  # Bad! Dodge it
]


@dataclass
class FallingFood:
    x: float
    y: float
    kind_idx: int
    speed: float
    size: float = 30.0
    caught: bool = False
    missed: bool = False
    alpha: float = 1.0
    # Visual wobble
    wobble_phase: float = field(default_factory=lambda: random.uniform(0, 6.28))


# ── The Game ───────────────────────────────────────────────────────────

class CatchSnackGame(DesktopGame):

    name = "Catch & Snack"
    description = "Catch falling food with your fish!"

    def __init__(self, fish_widget):
        super().__init__(fish_widget)
        self._foods: list[FallingFood] = []
        self._spawn_timer: float = 0.0
        self._spawn_interval: float = 1.2  # seconds between spawns
        self._base_speed: float = 180.0     # pixels per second
        self._lives: int = 5
        self._miss_streak: int = 0
        self._catch_streak: int = 0
        self._total_caught: int = 0
        self._total_missed: int = 0
        self._difficulty_ramp: float = 0.0

        # Frustration state (personality)
        self._frustrated: bool = False
        self._giving_up: bool = False
        self._trying_harder: bool = False

        # Visual effects
        self._catch_flashes: list[dict] = []  # {x, y, timer, color}
        self._screen_w = 0
        self._screen_h = 0

    def _on_game_start(self):
        screen = QApplication.primaryScreen().geometry()
        self._screen_w = screen.width()
        self._screen_h = screen.height()
        self._foods.clear()
        self._catch_flashes.clear()
        self._lives = 5
        self._miss_streak = 0
        self._catch_streak = 0
        self._total_caught = 0
        self._total_missed = 0
        self._spawn_timer = 0.0
        self._spawn_interval = 1.2
        self._frustrated = False
        self._giving_up = False
        self._trying_harder = False
        self._difficulty_ramp = 0.0

    def _on_tick(self):
        if self.state != GameState.PLAYING:
            self.update()
            return

        dt = 0.016
        self._game_time += dt
        self._difficulty_ramp = min(self._game_time / 60.0, 1.0)  # Full ramp over 60s

        # ── Move fish toward mouse ──────────────────────────────────
        cursor = self.mapFromGlobal(self.cursor().pos())
        fish_hw = self.fish.width() // 2
        fish_hh = self.fish.height() // 2
        target_x = cursor.x() - fish_hw
        target_y = cursor.y() - fish_hh

        # Clamp to screen
        target_x = max(0, min(target_x, self._screen_w - self.fish.width()))
        target_y = max(0, min(target_y, self._screen_h - self.fish.height()))

        # Smooth follow (fish has slight lag — feels alive)
        fx = self.fish.pos().x()
        fy = self.fish.pos().y()
        lag = 0.15 if not self._trying_harder else 0.08  # Faster when trying harder
        new_x = fx + (target_x - fx) * lag
        new_y = fy + (target_y - fy) * lag
        self._teleport_fish(int(new_x), int(new_y))

        # ── Spawn food ──────────────────────────────────────────────
        self._spawn_timer += dt
        interval = self._spawn_interval * (1.0 - 0.4 * self._difficulty_ramp)
        if self._spawn_timer >= interval:
            self._spawn_timer = 0.0
            self._spawn_food()

        # ── Update food positions ───────────────────────────────────
        fish_rect = self._fish_rect()
        # Grow the catch hitbox a bit for forgiveness
        catch_rect = fish_rect.adjusted(-10, -10, 10, 10)

        for food in self._foods:
            if food.caught or food.missed:
                food.alpha -= dt * 3.0
                continue

            speed = food.speed * (1.0 + 0.5 * self._difficulty_ramp)
            food.y += speed * dt
            food.wobble_phase += dt * 3.0
            food.x += math.sin(food.wobble_phase) * 0.5

            # Check catch
            food_rect = QRect(int(food.x), int(food.y),
                              int(food.size), int(food.size))
            if catch_rect.intersects(food_rect):
                food.caught = True
                kind = FOOD_KINDS[food.kind_idx]
                self.score += kind["points"]
                if self.score < 0:
                    self.score = 0

                if kind["points"] > 0:
                    self._total_caught += 1
                    self._catch_streak += 1
                    self._miss_streak = 0
                    self._frustrated = False
                    self._giving_up = False

                    # Trying harder resets after a catch
                    if self._trying_harder:
                        self._trying_harder = False

                    # Streak celebration
                    if self._catch_streak % 5 == 0:
                        self._emit("streak")

                    self._catch_flashes.append({
                        "x": food.x, "y": food.y,
                        "timer": 0.4,
                        "color": kind["color"],
                        "text": f"+{kind['points']}",
                    })
                else:
                    # Ate a bug!
                    self._catch_flashes.append({
                        "x": food.x, "y": food.y,
                        "timer": 0.4,
                        "color": QColor(100, 200, 100),
                        "text": "Yuck!",
                    })
                    self._emit("ate_bad")
                continue

            # Check miss (fell off screen)
            if food.y > self._screen_h + 20:
                food.missed = True
                kind = FOOD_KINDS[food.kind_idx]
                if kind["points"] > 0:  # Only count good food as a miss
                    self._total_missed += 1
                    self._miss_streak += 1
                    self._catch_streak = 0
                    self._lives -= 1

                    # ── Personality: frustration ──
                    if self._miss_streak >= 3 and not self._frustrated:
                        self._frustrated = True
                        if random.random() < 0.5:
                            self._trying_harder = True
                            self._emit("frustrated_trying")
                        else:
                            self._giving_up = True
                            self._emit("frustrated_giving_up")
                    elif self._miss_streak >= 2:
                        self._emit("miss_streak")

                    if self._lives <= 0:
                        self._determine_ending()
                        self.end_game()
                        return

        # ── Clean up dead food ──────────────────────────────────────
        self._foods = [f for f in self._foods if f.alpha > 0]

        # ── Update catch flashes ────────────────────────────────────
        for flash in self._catch_flashes:
            flash["timer"] -= dt
            flash["y"] -= 40 * dt
        self._catch_flashes = [f for f in self._catch_flashes if f["timer"] > 0]

        self.update()

    def _spawn_food(self):
        margin = 80
        x = random.uniform(margin, self._screen_w - margin)
        # Weighted: mostly good food, occasional star, rare bug
        weights = [25, 20, 25, 15, 5, 10]
        kind_idx = random.choices(range(len(FOOD_KINDS)), weights=weights, k=1)[0]
        speed = self._base_speed + random.uniform(-30, 30)
        self._foods.append(FallingFood(
            x=x, y=-40, kind_idx=kind_idx, speed=speed,
        ))

    def _determine_ending(self):
        """Choose the right ending event based on performance."""
        if self._total_caught == 0:
            self._emit("total_fail")
        elif self._total_caught < 5:
            self._emit("bad_game")
        elif self._new_high_score:
            self._emit("new_record")
        else:
            self._emit("decent_game")

    # ── Rendering ──────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.state == GameState.WAITING:
            # Slight dim + game name
            p.fillRect(self.rect(), QColor(0, 0, 0, 40))
            p.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
            p.setPen(QPen(QColor(255, 255, 255, 200)))
            r = self.rect()
            r.setTop(r.center().y() - 80)
            p.drawText(r, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       "🐟 Catch & Snack 🐟")
            self._draw_countdown(p)
            p.end()
            return

        if self.state == GameState.GAME_OVER:
            self._draw_game_over(p)
            p.end()
            return

        # ── Playing ─────────────────────────────────────────────────
        # Subtle vignette
        p.fillRect(self.rect(), QColor(0, 0, 20, 15))

        # Draw food
        food_font = QFont("Segoe UI Emoji", 22)
        p.setFont(food_font)
        for food in self._foods:
            if food.alpha <= 0:
                continue
            alpha = max(0, min(255, int(food.alpha * 255)))
            kind = FOOD_KINDS[food.kind_idx]
            p.setOpacity(food.alpha)
            # Shadow
            p.setPen(QPen(QColor(0, 0, 0, alpha // 3)))
            p.drawText(int(food.x) + 2, int(food.y) + 2 + int(food.size),
                       kind["emoji"])
            # Emoji
            p.setPen(QPen(QColor(255, 255, 255, alpha)))
            p.drawText(int(food.x), int(food.y) + int(food.size),
                       kind["emoji"])
        p.setOpacity(1.0)

        # Draw catch flashes
        for flash in self._catch_flashes:
            alpha = int(255 * (flash["timer"] / 0.4))
            p.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
            color = QColor(flash["color"])
            color.setAlpha(alpha)
            p.setPen(QPen(color))
            p.drawText(int(flash["x"]), int(flash["y"]), flash["text"])

        # Draw HUD
        self._draw_score_hud(p)

        # Draw lives
        p.setFont(QFont("Segoe UI", 14))
        p.setPen(QPen(QColor(255, 100, 100, 200)))
        hearts = "❤️ " * self._lives + "🖤 " * (5 - self._lives)
        p.drawText(20, 60, hearts.strip())

        # Draw streak indicator
        if self._catch_streak >= 3:
            p.setPen(QPen(QColor(255, 200, 50, 200)))
            p.drawText(20, 85, f"🔥 x{self._catch_streak}")

        # Frustration indicator
        if self._frustrated:
            p.setFont(QFont("Segoe UI", 12))
            if self._trying_harder:
                p.setPen(QPen(QColor(255, 150, 50, 180)))
                p.drawText(20, 105, "😤 Trying harder!")
            elif self._giving_up:
                p.setPen(QPen(QColor(150, 150, 200, 180)))
                p.drawText(20, 105, "😩 This is hopeless...")

        p.end()

    def mouseMoveEvent(self, event):
        # Mouse tracking drives the fish — handled in _on_tick
        pass

    def mousePressEvent(self, event):
        # Click could be a dash/boost later
        pass
