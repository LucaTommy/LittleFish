"""
Emotion-driven movement engine for LittleFish.

Movement states map directly to emotional state — the fish moves because
it *feels* something, not because a random timer fired.

Uses steering behaviours with arrival deceleration for natural easing.
"""

from __future__ import annotations

import math
import random
import time
from enum import Enum, auto
from typing import TYPE_CHECKING

from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

if TYPE_CHECKING:
    from core.emotion_engine import EmotionEngine
    from widget.fish_widget import FishWidget


# ======================================================================
# Movement states
# ======================================================================

class MovementState(Enum):
    IDLE = auto()       # Subtle micro-drifts.  Content / neutral.
    WANDER = auto()     # Slow, meandering path. Bored / restless.
    CURIOUS = auto()    # Quick dash toward stimulus, then watch.
    RETREAT = auto()    # Scoot away from fast-approaching cursor.
    SETTLE = auto()     # Walk to an edge/corner.  Sleepy / very content.
    CHASE = auto()      # Follow cursor lazily.   Playful mood.


# ======================================================================
# Per-state physics tuning
# ======================================================================

_STATE_CONFIG: dict[MovementState, dict] = {
    MovementState.IDLE: {
        "max_speed": 12.0,        # px/s — barely perceptible
        "acceleration": 25.0,     # px/s²
        "slow_radius": 10.0,      # begin decelerating this far from target
    },
    MovementState.WANDER: {
        "max_speed": 75.0,        # leisurely stroll
        "acceleration": 55.0,
        "slow_radius": 80.0,
    },
    MovementState.CURIOUS: {
        "max_speed": 380.0,       # quick dash
        "acceleration": 750.0,
        "slow_radius": 55.0,
    },
    MovementState.RETREAT: {
        "max_speed": 480.0,       # fast scoot
        "acceleration": 1100.0,
        "slow_radius": 35.0,
    },
    MovementState.SETTLE: {
        "max_speed": 55.0,        # calm walk to edge
        "acceleration": 35.0,
        "slow_radius": 45.0,
    },
    MovementState.CHASE: {
        "max_speed": 110.0,       # leisurely follow
        "acceleration": 90.0,
        "slow_radius": 90.0,
    },
}

# ── Cursor thresholds ────────────────────────────────────────────────
_RETREAT_PROXIMITY = 180         # px — cursor must be this close
_RETREAT_CURSOR_SPEED = 900      # px/s — and moving this fast *toward* fish
_CHASE_PROXIMITY = 400           # px — start following inside this radius
_CHASE_GIVE_UP_SEC = 8.0         # seconds of chasing before bored

# ── Wander timing ────────────────────────────────────────────────────
_WANDER_PAUSE_MIN = 2.0          # seconds resting between waypoints
_WANDER_PAUSE_MAX = 5.5
_WANDER_DRIFT_FREQ = 0.7        # Hz sine wobble on the path

# ── Idle drift ────────────────────────────────────────────────────────
_IDLE_DRIFT_MIN = 3.0            # seconds between micro-drifts
_IDLE_DRIFT_MAX = 7.0

# ── Settle ────────────────────────────────────────────────────────────
_SETTLE_LINGER_MIN = 12.0        # seconds sitting at an edge

# ── Curious ───────────────────────────────────────────────────────────
_CURIOUS_WATCH_SEC = 2.5         # seconds watching after arriving
_CURIOUS_CURSOR_SPEED = 1400     # px/s cursor speed triggers curiosity

# ── Cooldowns ─────────────────────────────────────────────────────────
_STATE_CHANGE_COOLDOWN = 0.6     # seconds — prevents flicker


# ======================================================================
# Engine
# ======================================================================

class MovementEngine:
    """Reads emotions, tracks the cursor, and moves the fish widget."""

    def __init__(self, fish: "FishWidget", emotions: "EmotionEngine"):
        self._fish = fish
        self._emo = emotions

        # ── State ────────────────────────────────────────────────────
        self._state = MovementState.IDLE
        self._prev_state = MovementState.IDLE
        self._state_time: float = 0.0       # seconds in current state
        self._cooldown: float = 0.0         # seconds before next transition

        # ── Physics ──────────────────────────────────────────────────
        self._vx: float = 0.0
        self._vy: float = 0.0
        self._target_x: float | None = None
        self._target_y: float | None = None

        # ── Cursor tracking ──────────────────────────────────────────
        self._cursor_hist: list[tuple[float, int, int]] = []
        self._cursor_speed: float = 0.0     # px/s averaged over 0.15 s

        # ── State-specific timers ────────────────────────────────────
        self._idle_drift_cd: float = random.uniform(_IDLE_DRIFT_MIN, _IDLE_DRIFT_MAX)
        self._wander_pause_cd: float = 0.0
        self._chase_elapsed: float = 0.0
        self._settled: bool = False
        self._curious_arrived: bool = False
        self._curious_watch_cd: float = 0.0

        # ── Pause (drag / momentum / game) ───────────────────────────
        self._paused: bool = False
        self._pause_until: float = 0.0

        # ── Worried jitter (Feature 2) ───────────────────────────────
        self._jitter_cd: float = 0.0  # countdown until next jitter

        # ── Focused speed multiplier (Feature 4) ─────────────────────
        self._focused_speed_mult: float = 1.0  # 1.0 = normal, 0.3 = focused

    # ── Public API ───────────────────────────────────────────────────

    @property
    def state(self) -> MovementState:
        return self._state

    @property
    def is_moving(self) -> bool:
        return math.hypot(self._vx, self._vy) > 2.0

    def pause(self, duration: float = 3.0):
        """Pause the engine (drag, flick momentum, games)."""
        self._paused = True
        self._pause_until = time.monotonic() + duration
        self._vx = 0.0
        self._vy = 0.0

    def resume(self):
        self._paused = False

    def _is_deep_sleep(self) -> bool:
        try:
            return self._fish.is_deeply_asleep()
        except AttributeError:
            sleepy_val = self._emo.values.get("sleepy", 0)
            return sleepy_val >= 0.7 or self._emo.dominant_emotion() == "sleepy"

    def _is_busy(self) -> bool:
        """True when an animation sequence is playing (hobbies etc)."""
        try:
            return self._fish.animator.is_playing_sequence
        except AttributeError:
            return False

    def notify_stimulus(self, x: int, y: int):
        """Something interesting appeared at *(x, y)* — maybe dash over."""
        if self._is_deep_sleep() or self._is_busy():
            return
        if self._emo.values.get("curious", 0) > 0.15:
            self._target_x = float(x)
            self._target_y = float(y)
            self._enter(MovementState.CURIOUS)

    def force_wander(self):
        """Behaviour engine says 'go wander'."""
        if self._is_deep_sleep() or self._is_busy():
            return
        self._enter(MovementState.WANDER)

    def force_chase(self):
        """Behaviour engine says 'follow the cursor'."""
        if self._is_deep_sleep() or self._is_busy():
            return
        self._enter(MovementState.CHASE)

    def force_settle(self, x: float | None = None, y: float | None = None):
        """Walk to a specific edge spot, or auto-pick nearest."""
        if self._is_deep_sleep() or self._is_busy():
            return
        if x is not None and y is not None:
            self._target_x = x
            self._target_y = y
        else:
            self._pick_settle_target()
        self._settled = False
        self._enter(MovementState.SETTLE)

    # ── Main tick (called every frame from fish_widget._on_tick) ─────

    def update(self, dt: float):
        if self._paused:
            if time.monotonic() >= self._pause_until:
                self._paused = False
            else:
                return

        self._track_cursor(dt)
        self._state_time += dt
        self._cooldown = max(0.0, self._cooldown - dt)

        # Animation sequence override — freeze movement during hobbies etc.
        if self._is_busy():
            if self._state != MovementState.IDLE:
                self._enter(MovementState.IDLE)
            self._vx = 0.0
            self._vy = 0.0
            return

        # Sleep override — stop movement when fish is asleep.
        if self._is_deep_sleep():
            if self._state != MovementState.IDLE:
                self._enter(MovementState.IDLE)
            self._vx = 0.0
            self._vy = 0.0
            return

        if self._cooldown <= 0:
            self._evaluate_transitions()

        self._tick_state(dt)
        self._apply_physics(dt)

    # ── Cursor ───────────────────────────────────────────────────────

    def _track_cursor(self, dt: float):
        now = time.monotonic()
        c = QCursor.pos()
        self._cursor_hist.append((now, c.x(), c.y()))
        # Keep last 0.15 s
        cutoff = now - 0.15
        self._cursor_hist = [h for h in self._cursor_hist if h[0] >= cutoff]
        if len(self._cursor_hist) >= 2:
            f = self._cursor_hist[0]
            l = self._cursor_hist[-1]
            elapsed = l[0] - f[0]
            if elapsed > 0.005:
                self._cursor_speed = math.hypot(l[1] - f[1], l[2] - f[2]) / elapsed
        else:
            self._cursor_speed = 0.0

    def _cursor_approaching(self) -> bool:
        """Is the cursor getting closer to the fish?"""
        if len(self._cursor_hist) < 2:
            return False
        fx, fy = self._fish_center()
        f = self._cursor_hist[0]
        l = self._cursor_hist[-1]
        d0 = math.hypot(f[1] - fx, f[2] - fy)
        d1 = math.hypot(l[1] - fx, l[2] - fy)
        return d1 < d0

    def _cursor_dist(self) -> float:
        fx, fy = self._fish_center()
        c = QCursor.pos()
        return math.hypot(c.x() - fx, c.y() - fy)

    # ── Helpers ──────────────────────────────────────────────────────

    def _fish_center(self) -> tuple[float, float]:
        p = self._fish.pos()
        return p.x() + self._fish.width() / 2, p.y() + self._fish.height() / 2

    def _screen_rect(self):
        scr = self._fish.screen() or QApplication.primaryScreen()
        return scr.availableGeometry() if scr else None

    def _dist_to_target(self) -> float:
        if self._target_x is None or self._target_y is None:
            return float("inf")
        fx, fy = self._fish_center()
        return math.hypot(self._target_x - fx, self._target_y - fy)

    def _is_playful(self) -> bool:
        v = self._emo.values
        return (v.get("happy", 0) > 0.35
                and v.get("excited", 0) > 0.15
                and v.get("sleepy", 0) < 0.3)

    # ── State transitions ────────────────────────────────────────────

    def _enter(self, st: MovementState):
        if st == self._state:
            return
        self._prev_state = self._state
        self._state = st
        self._state_time = 0.0
        self._cooldown = _STATE_CHANGE_COOLDOWN

        if st == MovementState.IDLE:
            self._target_x = self._target_y = None
            self._idle_drift_cd = random.uniform(_IDLE_DRIFT_MIN, _IDLE_DRIFT_MAX)
        elif st == MovementState.WANDER:
            self._pick_wander_target()
            self._wander_pause_cd = 0.0
        elif st == MovementState.CURIOUS:
            self._curious_arrived = False
            self._curious_watch_cd = 0.0
        elif st == MovementState.RETREAT:
            self._pick_retreat_target()
        elif st == MovementState.SETTLE:
            if self._target_x is None:
                self._pick_settle_target()
            self._settled = False
        elif st == MovementState.CHASE:
            self._chase_elapsed = 0.0

    def _evaluate_transitions(self):
        v = self._emo.values
        cdist = self._cursor_dist()

        # ── Highest priority: RETREAT ────────────────────────────────
        if (self._state != MovementState.RETREAT
                and cdist < _RETREAT_PROXIMITY
                and self._cursor_speed > _RETREAT_CURSOR_SPEED
                and self._cursor_approaching()):
            self._enter(MovementState.RETREAT)
            return

        # Don't interrupt retreat/curious mid-action
        if self._state == MovementState.RETREAT and self._target_x is not None:
            return
        if self._state == MovementState.CURIOUS and not self._curious_done():
            return

        # ── CURIOUS: fast cursor anywhere on screen ──────────────────
        if (self._state not in (MovementState.CURIOUS, MovementState.RETREAT)
                and self._cursor_speed > _CURIOUS_CURSOR_SPEED
                and v.get("curious", 0) > 0.2):
            c = QCursor.pos()
            self._target_x = float(c.x())
            self._target_y = float(c.y())
            self._enter(MovementState.CURIOUS)
            return

        # Stay in chase while conditions hold
        if self._state == MovementState.CHASE:
            if (cdist < _CHASE_PROXIMITY
                    and self._is_playful()
                    and self._chase_elapsed < _CHASE_GIVE_UP_SEC):
                return

        # ── CHASE: playful + cursor nearby ───────────────────────────
        if (self._state != MovementState.CHASE
                and self._is_playful()
                and cdist < _CHASE_PROXIMITY
                and random.random() < 0.008):  # gradual onset
            self._enter(MovementState.CHASE)
            return

        # ── DEEP SLEEP: high sleepy → freeze in place ────────────────
        if v.get("sleepy", 0) >= 0.7:
            if self._state != MovementState.IDLE:
                self._enter(MovementState.IDLE)
                self._vx = 0.0
                self._vy = 0.0
            return

        # ── SETTLE: sleepy or very content ───────────────────────────
        if (v.get("sleepy", 0) > 0.4
                or (v.get("content", 0) > 0.5 and v.get("bored", 0) < 0.2)):
            if self._state != MovementState.SETTLE:
                self._enter(MovementState.SETTLE)
            return

        # ── WANDER: bored / restless ─────────────────────────────────
        if v.get("bored", 0) > 0.25:
            if self._state != MovementState.WANDER:
                self._enter(MovementState.WANDER)
            return

        # ── Default: IDLE ────────────────────────────────────────────
        if self._state != MovementState.IDLE and self._state_time > 3.0:
            self._enter(MovementState.IDLE)

    # ── Target picking ───────────────────────────────────────────────

    def _pick_wander_target(self):
        bounds = self._screen_rect()
        if not bounds:
            return
        margin = 120
        fx, fy = self._fish_center()
        angle = random.uniform(0, 2 * math.pi)
        dist = random.uniform(100, 300)
        x = fx + math.cos(angle) * dist
        y = fy + math.sin(angle) * dist
        x = max(bounds.left() + margin, min(x, bounds.right() - margin))
        y = max(bounds.top() + margin, min(y, bounds.bottom() - margin))
        self._target_x = x
        self._target_y = y

    def _pick_retreat_target(self):
        fx, fy = self._fish_center()
        c = QCursor.pos()
        dx = fx - c.x()
        dy = fy - c.y()
        d = math.hypot(dx, dy)
        if d < 1:
            dx, dy, d = 1.0, 0.0, 1.0
        dist = random.uniform(200, 350)
        nx = fx + (dx / d) * dist
        ny = fy + (dy / d) * dist
        bounds = self._screen_rect()
        if bounds:
            m = 30
            w = self._fish.width()
            h = self._fish.height()
            nx = max(bounds.left() + m, min(nx, bounds.right() - w - m))
            ny = max(bounds.top() + m, min(ny, bounds.bottom() - h - m))
        self._target_x = nx
        self._target_y = ny

    def _pick_settle_target(self):
        bounds = self._screen_rect()
        if not bounds:
            return
        fx, fy = self._fish_center()
        w = self._fish.width()
        h = self._fish.height()
        candidates = [
            (bounds.left() + 10, fy),                                    # left
            (bounds.right() - w - 10, fy),                               # right
            (fx, bounds.bottom() - h - 10),                              # bottom
            (bounds.left() + 10, bounds.bottom() - h - 10),             # bottom-left
            (bounds.right() - w - 10, bounds.bottom() - h - 10),        # bottom-right
        ]
        best = min(candidates, key=lambda c: math.hypot(c[0] - fx, c[1] - fy))
        self._target_x, self._target_y = best

    # ── Per-state tick ───────────────────────────────────────────────

    def _tick_state(self, dt: float):
        dispatch = {
            MovementState.IDLE: self._tick_idle,
            MovementState.WANDER: self._tick_wander,
            MovementState.CURIOUS: self._tick_curious,
            MovementState.RETREAT: self._tick_retreat,
            MovementState.SETTLE: self._tick_settle,
            MovementState.CHASE: self._tick_chase,
        }
        dispatch[self._state](dt)

    def _tick_idle(self, dt: float):
        self._idle_drift_cd -= dt
        if self._idle_drift_cd <= 0:
            fx, fy = self._fish_center()
            self._target_x = fx + random.uniform(-8, 8)
            self._target_y = fy + random.uniform(-5, 5)
            self._idle_drift_cd = random.uniform(_IDLE_DRIFT_MIN, _IDLE_DRIFT_MAX)

    def _tick_wander(self, dt: float):
        if self._target_x is None:
            self._wander_pause_cd -= dt
            if self._wander_pause_cd <= 0:
                self._pick_wander_target()
            return

        # Gentle sine-wave perpendicular drift for organic path
        speed = math.hypot(self._vx, self._vy)
        if speed > 5:
            px = -self._vy / speed
            py = self._vx / speed
            drift = math.sin(self._state_time * _WANDER_DRIFT_FREQ * 2 * math.pi) * 12.0
            self._vx += px * drift * dt
            self._vy += py * drift * dt

        if self._dist_to_target() < 15:
            self._target_x = None
            self._target_y = None
            self._vx *= 0.3
            self._vy *= 0.3
            self._wander_pause_cd = random.uniform(_WANDER_PAUSE_MIN, _WANDER_PAUSE_MAX)

    def _tick_curious(self, dt: float):
        if not self._curious_arrived:
            if self._target_x is not None and self._dist_to_target() < 30:
                self._curious_arrived = True
                self._curious_watch_cd = 0.0
                self._target_x = None
                self._target_y = None
                self._vx *= 0.1
                self._vy *= 0.1
        else:
            self._curious_watch_cd += dt
            if self._curious_watch_cd >= _CURIOUS_WATCH_SEC:
                self._enter(MovementState.IDLE)

    def _tick_retreat(self, dt: float):
        if self._target_x is not None and self._dist_to_target() < 20:
            self._target_x = None
            self._target_y = None
            self._vx *= 0.2
            self._vy *= 0.2
        if self._target_x is None and self._state_time > 0.8:
            self._enter(MovementState.IDLE)

    def _tick_settle(self, dt: float):
        if not self._settled:
            if self._target_x is not None and self._dist_to_target() < 20:
                self._settled = True
                self._target_x = None
                self._target_y = None
                self._vx = 0.0
                self._vy = 0.0
        # Stay settled until emotion transitions us out

    def _tick_chase(self, dt: float):
        self._chase_elapsed += dt
        if self._chase_elapsed > _CHASE_GIVE_UP_SEC:
            self._enter(MovementState.IDLE)
            return

        c = QCursor.pos()
        fx, fy = self._fish_center()
        dx = c.x() - fx
        dy = c.y() - fy
        dist = math.hypot(dx, dy)

        if dist > 50:
            keep = 80.0
            if dist > keep:
                ratio = (dist - keep) / dist
                self._target_x = fx + dx * ratio
                self._target_y = fy + dy * ratio
            else:
                self._target_x = None
                self._target_y = None

        if dist > _CHASE_PROXIMITY * 1.5:
            self._enter(MovementState.IDLE)

    def _curious_done(self) -> bool:
        return self._curious_arrived and self._curious_watch_cd >= _CURIOUS_WATCH_SEC

    # ── Steering physics ─────────────────────────────────────────────

    def _apply_physics(self, dt: float):
        cfg = _STATE_CONFIG[self._state]
        max_spd = cfg["max_speed"]
        accel = cfg["acceleration"]
        slow_r = cfg["slow_radius"]

        # Feature 4: Focused stillness — reduce speeds
        focused_val = self._emo.values.get("focused", 0.0)
        if focused_val > 0.5 and self._emo.dominant_emotion() == "focused":
            intensity = min(1.0, (focused_val - 0.5) * 2.0)  # 0..1 over 0.5..1.0
            self._focused_speed_mult = 1.0 - 0.7 * intensity  # down to 0.3
        else:
            self._focused_speed_mult = 1.0
        max_spd *= self._focused_speed_mult
        accel *= self._focused_speed_mult

        # Feature 2: Worried jitter
        worried_val = self._emo.values.get("worried", 0.0)
        if worried_val > 0.5 and self._emo.dominant_emotion() == "worried":
            self._jitter_cd -= dt
            if self._jitter_cd <= 0:
                self._jitter_cd = 0.5
                intensity = min(1.0, (worried_val - 0.5) * 2.0)  # 0..1
                jitter_px = 1.0 + 2.0 * intensity  # 1-3 px
                self._vx += random.uniform(-jitter_px, jitter_px) / max(dt, 0.001)
                self._vy += random.uniform(-jitter_px, jitter_px) / max(dt, 0.001)

        # Feature 2: Edge avoidance when worried
        if worried_val > 0.5:
            self._apply_edge_avoidance(dt, worried_val)

        if self._target_x is not None and self._target_y is not None:
            fx, fy = self._fish_center()
            dx = self._target_x - fx
            dy = self._target_y - fy
            dist = math.hypot(dx, dy)

            if dist < 1:
                self._vx *= 0.8
                self._vy *= 0.8
            else:
                nx = dx / dist
                ny = dy / dist
                # Arrival: decelerate near target
                desired = max_spd * min(1.0, dist / slow_r) if slow_r > 0 else max_spd
                dvx = nx * desired
                dvy = ny * desired
                # Steering force
                sx = dvx - self._vx
                sy = dvy - self._vy
                sm = math.hypot(sx, sy)
                cap = accel * dt
                if sm > cap:
                    sx = sx / sm * cap
                    sy = sy / sm * cap
                self._vx += sx
                self._vy += sy
        else:
            # No target — smooth friction
            decay = 1.0 - min(3.0 * dt, 0.95)
            self._vx *= decay
            self._vy *= decay

        # Clamp speed
        spd = math.hypot(self._vx, self._vy)
        if spd > max_spd:
            self._vx = self._vx / spd * max_spd
            self._vy = self._vy / spd * max_spd

        # Dead zone
        if spd < 0.5:
            return

        # Move the widget
        pos = self._fish.pos()
        nx = pos.x() + self._vx * dt
        ny = pos.y() + self._vy * dt

        # Screen bounds — hard clamp (stop at edges, no bounce)
        bounds = self._screen_rect()
        if bounds:
            w = self._fish.width()
            h = self._fish.height()
            m = 10
            left_lim = float(bounds.left() + m)
            right_lim = float(bounds.right() - w - m)
            top_lim = float(bounds.top() + m)
            bot_lim = float(bounds.bottom() - h - m)
            if nx < left_lim:
                nx = left_lim
                self._vx = 0.0
            elif nx > right_lim:
                nx = right_lim
                self._vx = 0.0
            if ny < top_lim:
                ny = top_lim
                self._vy = 0.0
            elif ny > bot_lim:
                ny = bot_lim
                self._vy = 0.0

        self._fish.move(int(nx), int(ny))

    # ── Edge avoidance (Feature 2: worried) ──────────────────────────

    def _apply_edge_avoidance(self, dt: float, worry: float):
        """Push the fish away from screen edges when worried.
        Repulsion zone is 150px scaled by worry intensity."""
        bounds = self._screen_rect()
        if not bounds:
            return
        fx, fy = self._fish_center()
        w = self._fish.width()
        h = self._fish.height()
        intensity = min(1.0, (worry - 0.5) * 2.0)  # 0..1
        zone = 150.0
        force = 200.0 * intensity  # px/s push

        # Distances to each edge
        dl = fx - bounds.left()
        dr = bounds.right() - fx
        dt_ = fy - bounds.top()
        db = bounds.bottom() - fy

        push_x = 0.0
        push_y = 0.0
        if dl < zone:
            push_x += force * (1.0 - dl / zone)
        if dr < zone:
            push_x -= force * (1.0 - dr / zone)
        if dt_ < zone:
            push_y += force * (1.0 - dt_ / zone)
        if db < zone:
            push_y -= force * (1.0 - db / zone)

        self._vx += push_x * dt
        self._vy += push_y * dt
