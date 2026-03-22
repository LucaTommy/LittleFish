"""
Animation engine for Little Fish.
Handles breathing, blinking, face transitions, reaction animations,
and complex multi-step animation sequences from the animation library.
All timing in seconds. Called every frame (~16ms) from the main widget.
"""

import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# Easing functions — never linear for character animation
# ---------------------------------------------------------------------------

def ease_in_out_sine(t: float) -> float:
    return 0.5 * (1.0 - math.cos(math.pi * t))

def ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3

def ease_in_cubic(t: float) -> float:
    return t ** 3


# ---------------------------------------------------------------------------
# Blink state
# ---------------------------------------------------------------------------

class BlinkPhase(Enum):
    OPEN = auto()
    CLOSING = auto()
    CLOSED = auto()
    OPENING = auto()


@dataclass
class BlinkState:
    phase: BlinkPhase = BlinkPhase.OPEN
    progress: float = 0.0          # 0.0 = fully open, 1.0 = fully closed
    timer: float = 0.0             # countdown to next event
    next_blink_in: float = 3.0     # seconds until next blink
    close_duration: float = 0.08   # seconds for the close phase
    open_duration: float = 0.08    # seconds for the open phase
    hold_duration: float = 0.02    # pause at closed before opening
    blinks_remaining: int = 0      # for double-blink

    def randomize_interval(self):
        self.next_blink_in = random.uniform(2.5, 6.0)


# ---------------------------------------------------------------------------
# Reaction animation keyframes
# ---------------------------------------------------------------------------

@dataclass
class Keyframe:
    time: float            # seconds from reaction start
    scale: float = 1.0
    rotation: float = 0.0  # degrees
    offset_x: float = 0.0
    offset_y: float = 0.0


class ReactionType(Enum):
    FLINCH = auto()
    WIGGLE = auto()
    BOUNCE = auto()
    STRETCH = auto()
    NOD = auto()
    HEAD_TILT = auto()
    SQUISH_H = auto()    # horizontal squish (hit left/right edge)
    SQUISH_V = auto()    # vertical squish (hit top/bottom edge)
    DIZZY = auto()       # rapid clicking → spiral
    PURR = auto()        # petted → gentle sway
    SHAKE_OFF = auto()   # after being shaken
    RAGE_SHAKE = auto()  # CPU spike → rapid jitter


REACTION_KEYFRAMES: dict[ReactionType, list[Keyframe]] = {
    ReactionType.FLINCH: [
        Keyframe(time=0.00, scale=1.0),
        Keyframe(time=0.08, scale=0.85),
        Keyframe(time=0.20, scale=1.0),
    ],
    ReactionType.WIGGLE: [
        Keyframe(time=0.00, rotation=0),
        Keyframe(time=0.075, rotation=8),
        Keyframe(time=0.15, rotation=-8),
        Keyframe(time=0.225, rotation=8),
        Keyframe(time=0.30, rotation=-8),
        Keyframe(time=0.375, rotation=8),
        Keyframe(time=0.45, rotation=-8),
        Keyframe(time=0.525, rotation=8),
        Keyframe(time=0.60, rotation=0),
    ],
    ReactionType.BOUNCE: [
        Keyframe(time=0.00, scale=1.0),
        Keyframe(time=0.08, scale=1.1),
        Keyframe(time=0.16, scale=0.95),
        Keyframe(time=0.26, scale=1.0),
    ],
    ReactionType.STRETCH: [
        Keyframe(time=0.00, scale=1.0),
        Keyframe(time=0.30, scale=1.12, offset_y=-1.0),
        Keyframe(time=0.50, scale=1.12, offset_y=-1.0),
        Keyframe(time=0.80, scale=0.97, offset_y=0.5),
        Keyframe(time=1.00, scale=1.0),
    ],
    ReactionType.NOD: [
        Keyframe(time=0.00, offset_y=0),
        Keyframe(time=0.12, offset_y=2.0),
        Keyframe(time=0.25, offset_y=0),
    ],
    ReactionType.HEAD_TILT: [
        Keyframe(time=0.00, rotation=0),
        Keyframe(time=0.20, rotation=-12),
        Keyframe(time=0.70, rotation=-12),
        Keyframe(time=0.90, rotation=0),
    ],
    ReactionType.SQUISH_H: [
        Keyframe(time=0.00, scale=1.0),
        Keyframe(time=0.06, scale=0.80),  # squash wide
        Keyframe(time=0.15, scale=1.08),
        Keyframe(time=0.25, scale=0.96),
        Keyframe(time=0.35, scale=1.0),
    ],
    ReactionType.SQUISH_V: [
        Keyframe(time=0.00, scale=1.0, offset_y=0),
        Keyframe(time=0.06, scale=0.85, offset_y=2.0),
        Keyframe(time=0.15, scale=1.06, offset_y=-1.0),
        Keyframe(time=0.25, scale=0.97, offset_y=0),
        Keyframe(time=0.35, scale=1.0),
    ],
    ReactionType.DIZZY: [
        Keyframe(time=0.00, rotation=0),
        Keyframe(time=0.10, rotation=15),
        Keyframe(time=0.20, rotation=-15),
        Keyframe(time=0.30, rotation=12),
        Keyframe(time=0.40, rotation=-12),
        Keyframe(time=0.50, rotation=8),
        Keyframe(time=0.60, rotation=-8),
        Keyframe(time=0.70, rotation=0),
    ],
    ReactionType.PURR: [
        Keyframe(time=0.00, offset_x=0, scale=1.0),
        Keyframe(time=0.15, offset_x=1.5, scale=1.02),
        Keyframe(time=0.30, offset_x=-1.5, scale=1.02),
        Keyframe(time=0.45, offset_x=1.0, scale=1.01),
        Keyframe(time=0.60, offset_x=-1.0, scale=1.01),
        Keyframe(time=0.80, offset_x=0, scale=1.0),
    ],
    ReactionType.SHAKE_OFF: [
        Keyframe(time=0.00, rotation=0, offset_x=0),
        Keyframe(time=0.08, rotation=20, offset_x=3),
        Keyframe(time=0.16, rotation=-20, offset_x=-3),
        Keyframe(time=0.24, rotation=15, offset_x=2),
        Keyframe(time=0.32, rotation=-15, offset_x=-2),
        Keyframe(time=0.40, rotation=8, offset_x=1),
        Keyframe(time=0.50, rotation=0, offset_x=0),
    ],
    ReactionType.RAGE_SHAKE: [
        Keyframe(time=0.00, offset_x=0, offset_y=0),
        Keyframe(time=0.04, offset_x=2, offset_y=-1),
        Keyframe(time=0.08, offset_x=-2, offset_y=1),
        Keyframe(time=0.12, offset_x=3, offset_y=-1),
        Keyframe(time=0.16, offset_x=-3, offset_y=1),
        Keyframe(time=0.20, offset_x=2, offset_y=0),
        Keyframe(time=0.24, offset_x=-2, offset_y=-1),
        Keyframe(time=0.28, offset_x=1, offset_y=0),
        Keyframe(time=0.35, offset_x=0, offset_y=0),
    ],
}


@dataclass
class ActiveReaction:
    reaction_type: ReactionType
    keyframes: list[Keyframe]
    elapsed: float = 0.0
    duration: float = 0.0

    def __post_init__(self):
        self.duration = self.keyframes[-1].time if self.keyframes else 0.0


# ---------------------------------------------------------------------------
# Face transition
# ---------------------------------------------------------------------------

@dataclass
class FaceTransition:
    """Cross-fade between two face states over 300ms."""
    from_state: str = "happy"
    to_state: str = "happy"
    progress: float = 1.0   # 1.0 = fully arrived at to_state
    duration: float = 0.3


# ---------------------------------------------------------------------------
# Main Animator
# ---------------------------------------------------------------------------

class Animator:
    def __init__(self):
        # Breathing
        self._birth_time = time.monotonic()
        self.breath_scale: float = 1.0

        # Blinking
        self.blink = BlinkState()
        self.blink.randomize_interval()

        # Face
        self.current_face: str = "happy"
        self.face_transition = FaceTransition()

        # Reactions (FIFO queue)
        self._reaction_queue: list[ReactionType] = []
        self._active_reaction: Optional[ActiveReaction] = None

        # Particles
        self.particles: list[dict] = []
        self._particle_timer: float = 0.0

        # Combined output for renderer
        self.scale: float = 1.0
        self.rotation: float = 0.0
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0

        # State flags
        self.is_talking: bool = False
        self.is_dragging: bool = False

        # Look-around idle animation
        self._look_active: bool = False
        self._look_elapsed: float = 0.0
        self._look_targets: list[tuple] = []
        self._look_idx: int = 0
        self.idle_gaze_x: float = 0.0
        self.idle_gaze_y: float = 0.0

        # Animation sequence player
        self._seq_active = None        # AnimSequence or None
        self._seq_step_idx: int = 0
        self._seq_step_timer: float = 0.0
        self._seq_offset_x: float = 0.0
        self._seq_offset_y: float = 0.0
        self._seq_gaze_override = None  # (dx, dy) or None
        self.active_prop = None         # AnimProp or None (for renderer)
        self.is_playing_sequence: bool = False
        self.on_step_executed = None     # callback(step, seq_name) or None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, dt: float):
        """Called every frame. dt is seconds since last frame."""
        self._update_breathing(dt)
        self._update_blink(dt)
        self._update_face_transition(dt)
        self._update_reactions(dt)
        self._update_look_around(dt)
        self._update_particles(dt)
        self._update_sequence(dt)
        self._compose_transforms()

    def set_face(self, state: str):
        """Request a face state change with cross-fade."""
        if state != self.face_transition.to_state:
            self.face_transition = FaceTransition(
                from_state=self.face_transition.to_state,
                to_state=state,
                progress=0.0,
            )
            self.current_face = state

    def queue_reaction(self, reaction_type: ReactionType):
        """Add a reaction to the queue."""
        self._reaction_queue.append(reaction_type)

    def trigger_double_blink(self):
        """Force a double-blink (surprise)."""
        self.blink.blinks_remaining = 2
        self.blink.phase = BlinkPhase.CLOSING
        self.blink.timer = 0.0
        self.blink.close_duration = 0.06
        self.blink.open_duration = 0.06

    def trigger_slow_blink(self):
        """Force a slow contentment blink."""
        self.blink.phase = BlinkPhase.CLOSING
        self.blink.timer = 0.0
        self.blink.close_duration = 0.20
        self.blink.open_duration = 0.20

    def trigger_look_around(self):
        """Start a look-around sequence — eyes shift in a random pattern."""
        self._look_active = True
        self._look_elapsed = 0.0
        self._look_idx = 0
        patterns = [
            [(-0.8, 0, 1.0), (0, 0, 0.3), (0.8, 0, 1.0), (0, 0, 0.4)],
            [(0.7, -0.5, 0.8), (-0.5, -0.3, 0.6), (0, 0, 0.4)],
            [(0, -0.7, 0.6), (0.6, 0, 0.5), (-0.4, 0.2, 0.5), (0, 0, 0.4)],
            [(-0.6, -0.3, 0.7), (0.6, -0.3, 0.7), (0, 0, 0.4)],
        ]
        self._look_targets = random.choice(patterns)

    def trigger_nod_off(self):
        """Nod off — eyes slowly close, hold 2s, then slowly reopen."""
        self.blink.phase = BlinkPhase.CLOSING
        self.blink.timer = 0.0
        self.blink.close_duration = 0.4
        self.blink.open_duration = 0.5
        self.blink.hold_duration = 2.0

    def play_sequence(self, sequence):
        """Start playing an AnimSequence from the animation library."""
        if self._seq_active is not None:
            return False  # already playing
        self._seq_active = sequence
        self._seq_step_idx = 0
        self._seq_step_timer = 0.0
        self._seq_offset_x = 0.0
        self._seq_offset_y = 0.0
        self._seq_gaze_override = None
        self.active_prop = None
        self.is_playing_sequence = True
        sequence.last_played = time.monotonic()
        # Execute the first step immediately if delay is 0
        if sequence.steps and sequence.steps[0].delay <= 0:
            self._execute_seq_step(sequence.steps[0])
            self._seq_step_idx = 1
        return True

    def stop_sequence(self):
        """Stop the current animation sequence."""
        self._seq_active = None
        self._seq_step_idx = 0
        self._seq_step_timer = 0.0
        self._seq_offset_x = 0.0
        self._seq_offset_y = 0.0
        self._seq_gaze_override = None
        self.active_prop = None
        self.is_playing_sequence = False

    # ------------------------------------------------------------------
    # Breathing
    # ------------------------------------------------------------------

    def _update_breathing(self, dt: float):
        elapsed = time.monotonic() - self._birth_time
        self.breath_scale = 1.0 + 0.015 * math.sin(2.0 * math.pi * elapsed / 3.5)

    # ------------------------------------------------------------------
    # Blinking
    # ------------------------------------------------------------------

    def _update_blink(self, dt: float):
        if self.is_talking:
            self.blink.progress = 0.0
            return

        b = self.blink

        if b.phase == BlinkPhase.OPEN:
            b.progress = 0.0
            b.next_blink_in -= dt
            if b.next_blink_in <= 0:
                b.phase = BlinkPhase.CLOSING
                b.timer = 0.0
                # Normal blink durations (may be overridden by slow/double)
                if b.blinks_remaining == 0:
                    b.close_duration = 0.08
                    b.open_duration = 0.08
                    b.hold_duration = 0.02

        elif b.phase == BlinkPhase.CLOSING:
            b.timer += dt
            t = min(b.timer / b.close_duration, 1.0)
            b.progress = ease_out_cubic(t)
            if t >= 1.0:
                b.phase = BlinkPhase.CLOSED
                b.timer = 0.0

        elif b.phase == BlinkPhase.CLOSED:
            b.progress = 1.0
            b.timer += dt
            if b.timer >= b.hold_duration:
                b.phase = BlinkPhase.OPENING
                b.timer = 0.0

        elif b.phase == BlinkPhase.OPENING:
            b.timer += dt
            t = min(b.timer / b.open_duration, 1.0)
            b.progress = 1.0 - ease_out_cubic(t)
            if t >= 1.0:
                if b.blinks_remaining > 0:
                    b.blinks_remaining -= 1
                    b.phase = BlinkPhase.CLOSING
                    b.timer = 0.0
                else:
                    b.phase = BlinkPhase.OPEN
                    b.progress = 0.0
                    b.randomize_interval()

    # ------------------------------------------------------------------
    # Face transition
    # ------------------------------------------------------------------

    def _update_face_transition(self, dt: float):
        ft = self.face_transition
        if ft.progress < 1.0:
            ft.progress = min(ft.progress + dt / ft.duration, 1.0)

    def get_face_blend(self) -> tuple[str, str, float]:
        """Returns (from_state, to_state, blend_t) where blend_t 0→1 ease-in-out."""
        ft = self.face_transition
        t = ease_in_out_sine(ft.progress)
        return ft.from_state, ft.to_state, t

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    def _update_reactions(self, dt: float):
        # Start next reaction if none active
        if self._active_reaction is None and self._reaction_queue:
            rtype = self._reaction_queue.pop(0)
            kf = REACTION_KEYFRAMES.get(rtype, [])
            if kf:
                self._active_reaction = ActiveReaction(
                    reaction_type=rtype,
                    keyframes=list(kf),
                )

        if self._active_reaction is None:
            return

        r = self._active_reaction
        r.elapsed += dt

        if r.elapsed >= r.duration:
            self._active_reaction = None
            return

        # Interpolate between keyframes
        kf = r.keyframes
        # Find the two keyframes we're between
        for i in range(len(kf) - 1):
            if kf[i].time <= r.elapsed <= kf[i + 1].time:
                seg_duration = kf[i + 1].time - kf[i].time
                if seg_duration > 0:
                    t = (r.elapsed - kf[i].time) / seg_duration
                    t = ease_out_cubic(t)
                else:
                    t = 1.0
                self._reaction_scale = _lerp(kf[i].scale, kf[i + 1].scale, t)
                self._reaction_rotation = _lerp(kf[i].rotation, kf[i + 1].rotation, t)
                self._reaction_offset_x = _lerp(kf[i].offset_x, kf[i + 1].offset_x, t)
                self._reaction_offset_y = _lerp(kf[i].offset_y, kf[i + 1].offset_y, t)
                return

    # ------------------------------------------------------------------
    # Look-around idle animation
    # ------------------------------------------------------------------

    def _update_look_around(self, dt: float):
        """Smoothly animate eye gaze for idle look-around."""
        if not self._look_active:
            self.idle_gaze_x += (0 - self.idle_gaze_x) * min(dt * 3, 0.3)
            self.idle_gaze_y += (0 - self.idle_gaze_y) * min(dt * 3, 0.3)
            if abs(self.idle_gaze_x) < 0.01:
                self.idle_gaze_x = 0.0
            if abs(self.idle_gaze_y) < 0.01:
                self.idle_gaze_y = 0.0
            return

        if self._look_idx >= len(self._look_targets):
            self._look_active = False
            return

        tx, ty, dur = self._look_targets[self._look_idx]
        self._look_elapsed += dt

        speed = min(dt * 4.0, 0.3)
        self.idle_gaze_x += (tx - self.idle_gaze_x) * speed
        self.idle_gaze_y += (ty - self.idle_gaze_y) * speed

        if self._look_elapsed >= dur:
            self._look_elapsed = 0.0
            self._look_idx += 1

    # ------------------------------------------------------------------
    # Compose final transform values
    # ------------------------------------------------------------------

    def _compose_transforms(self):
        self.scale = self.breath_scale
        self.rotation = 0.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        if self._active_reaction is not None:
            self.scale *= getattr(self, '_reaction_scale', 1.0)
            self.rotation += getattr(self, '_reaction_rotation', 0.0)
            self.offset_x += getattr(self, '_reaction_offset_x', 0.0)
            self.offset_y += getattr(self, '_reaction_offset_y', 0.0)

        # Add sequence offsets (smoothly interpolated)
        if self._seq_active is not None:
            self.offset_x += self._seq_offset_x
            self.offset_y += self._seq_offset_y

    # ------------------------------------------------------------------
    # Animation sequence player
    # ------------------------------------------------------------------

    def _update_sequence(self, dt: float):
        """Advance the animation sequence player."""
        if self._seq_active is None:
            return

        seq = self._seq_active
        if self._seq_step_idx >= len(seq.steps):
            self.stop_sequence()
            return

        self._seq_step_timer += dt
        step = seq.steps[self._seq_step_idx]

        if self._seq_step_timer >= step.delay:
            self._execute_seq_step(step)
            self._seq_step_idx += 1
            self._seq_step_timer = 0.0

            # Check if sequence is done
            if self._seq_step_idx >= len(seq.steps):
                self.stop_sequence()

        # Smooth gaze override toward target
        if self._seq_gaze_override is not None:
            tx, ty = self._seq_gaze_override
            speed = min(dt * 4.0, 0.3)
            self.idle_gaze_x += (tx - self.idle_gaze_x) * speed
            self.idle_gaze_y += (ty - self.idle_gaze_y) * speed

    def _execute_seq_step(self, step):
        """Execute a single animation step."""
        from core.animation_library import AnimProp

        if step.face is not None:
            self.set_face(step.face)

        if step.reaction is not None:
            rtype = ReactionType[step.reaction]
            self.queue_reaction(rtype)

        if step.particle is not None:
            for _ in range(step.particle_count):
                self.spawn_particle(step.particle)

        if step.prop is not None:
            self.active_prop = step.prop

        if step.hide_prop:
            self.active_prop = None

        if step.blink == "slow":
            self.trigger_slow_blink()
        elif step.blink == "double":
            self.trigger_double_blink()
        elif step.blink == "nod_off":
            self.trigger_nod_off()

        if step.offset_x != 0.0 or step.offset_y != 0.0:
            self._seq_offset_x = step.offset_x
            self._seq_offset_y = step.offset_y

        if step.look_dir is not None:
            self._seq_gaze_override = step.look_dir
            if step.look_dir == (0.0, 0.0):
                self._seq_gaze_override = None

        if self.on_step_executed and self._seq_active:
            self.on_step_executed(step, self._seq_active.name)

    # ------------------------------------------------------------------
    # Particles
    # ------------------------------------------------------------------

    def spawn_particle(self, kind: str):
        """Spawn a particle effect.
        Kinds: zzz, sparkle, sweat, heart, question, exclamation, music,
               confetti, star, stars, spiral, snow, leaf, spark, antenna_down,
               rain, firework, dust, sleep_bubble, emote_coffee, emote_book,
               emote_music, lightning
        """
        # Position relative to 32x32 canvas
        if kind == "zzz":
            x = random.randint(24, 28)
            y = random.randint(2, 8)
        elif kind == "sparkle":
            x = random.randint(2, 30)
            y = random.randint(2, 10)
        elif kind == "sweat":
            x = random.randint(24, 28)
            y = random.randint(6, 12)
        elif kind == "heart":
            x = random.randint(2, 8)
            y = random.randint(1, 6)
        elif kind == "question":
            x = random.randint(24, 28)
            y = random.randint(1, 5)
        elif kind == "exclamation":
            x = random.randint(24, 28)
            y = random.randint(1, 5)
        elif kind == "music":
            x = random.randint(3, 8) if random.random() < 0.5 else random.randint(24, 28)
            y = random.randint(2, 8)
        elif kind == "confetti":
            x = random.randint(2, 30)
            y = random.randint(0, 4)
        elif kind == "star":
            x = random.randint(4, 28)
            y = random.randint(1, 6)
        elif kind == "stars":
            x = random.randint(6, 26)
            y = random.randint(0, 4)
        elif kind == "spiral":
            x = 16
            y = 2
        elif kind == "snow":
            x = random.randint(0, 31)
            y = -2
        elif kind == "leaf":
            x = random.randint(0, 31)
            y = -2
        elif kind == "spark":
            x = random.randint(6, 26)
            y = random.randint(20, 26)
        elif kind == "antenna_down":
            x = 16
            y = 0
        elif kind == "rain":
            x = random.randint(0, 31)
            y = -2
        elif kind == "firework":
            x = random.randint(4, 28)
            y = random.randint(0, 6)
        elif kind == "dust":
            x = random.randint(8, 24)
            y = random.randint(24, 28)
        elif kind == "sleep_bubble":
            x = random.randint(24, 28)
            y = random.randint(2, 6)
        elif kind == "lightning":
            x = 16
            y = 0
        elif kind.startswith("emote_"):
            x = random.randint(2, 8)
            y = random.randint(0, 4)
        else:
            x, y = 16, 4

        vy = -6.0
        life = 1.4
        vx = 0.0
        if kind == "confetti":
            vx = random.uniform(-8.0, 8.0)
            vy = random.uniform(-4.0, 2.0)
            life = 1.8
        elif kind == "sweat":
            vy = 5.0
            life = 0.9
        elif kind == "music":
            vx = random.choice([-3.0, 3.0])
        elif kind == "stars":
            vx = random.uniform(-4.0, 4.0)
            vy = random.uniform(-3.0, 0.0)
            life = 1.5
        elif kind == "spiral":
            vx = 0.0
            vy = -2.0
            life = 1.2
        elif kind == "snow":
            vx = random.uniform(-3.0, 3.0)
            vy = random.uniform(6.0, 12.0)
            life = 3.0
        elif kind == "leaf":
            vx = random.uniform(-5.0, 5.0)
            vy = random.uniform(4.0, 8.0)
            life = 3.5
        elif kind == "spark":
            vx = random.uniform(-6.0, 6.0)
            vy = random.uniform(-8.0, -4.0)
            life = 0.6
        elif kind == "antenna_down":
            vx = 0.0
            vy = 0.0
            life = 2.0
        elif kind == "rain":
            vx = random.uniform(-1.0, 1.0)
            vy = random.uniform(14.0, 20.0)
            life = 2.0
        elif kind == "firework":
            vx = random.uniform(-10.0, 10.0)
            vy = random.uniform(-12.0, -2.0)
            life = 1.2
        elif kind == "dust":
            vx = random.uniform(-4.0, 4.0)
            vy = random.uniform(-3.0, -1.0)
            life = 0.7
        elif kind == "sleep_bubble":
            vx = random.uniform(0.5, 1.5)
            vy = random.uniform(-2.0, -1.0)
            life = 2.5
        elif kind == "lightning":
            vx = 0.0
            vy = 0.0
            life = 0.3
        elif kind.startswith("emote_"):
            vx = 0.0
            vy = -3.0
            life = 2.5

        self.particles.append({
            "kind": kind,
            "x": float(x),
            "y": float(y),
            "vx": vx,
            "vy": vy,
            "life": life,
            "max_life": life,
            "alpha": 255,
        })

    def _update_particles(self, dt: float):
        """Move particles, fade, and remove dead ones."""
        alive = []
        for p in self.particles:
            p["life"] -= dt
            if p["life"] <= 0:
                continue
            p["y"] += p["vy"] * dt
            p["x"] += p.get("vx", 0.0) * dt
            # Fade out in last 30% of life
            frac = p["life"] / p["max_life"]
            if frac < 0.3:
                p["alpha"] = int(255 * (frac / 0.3))
            alive.append(p)
        self.particles = alive


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
