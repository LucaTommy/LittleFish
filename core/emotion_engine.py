"""
Emotion engine v2 for Little Fish.

Three-layer architecture:
  Layer 1 — EMOTIONS: Internal states (floats 0.0-1.0) with momentum,
            compound blending, vulnerability windows, and mood arcs.
  Layer 2 — REACTIONS: Computed from emotions + triggers (handled by behavior engine).
  Layer 3 — CHARACTER: Personality constants that modulate how emotions express
            (handled by personality.py + user_profile.py).

Key improvements over v1:
  - Emotional momentum: sustained moods become harder to shift
  - Compound emotions: tracks the top-2 blend, not just dominant
  - Mood arcs: slow multi-hour trajectories, not random spikes
  - Energy budget: daily energy that depletes with activity
  - Vulnerability windows: emotional aftereffects (crash after excitement, etc.)
  - User-profile awareness: chronotype, age, usage all modulate baselines
  - Frustration stacking: repeated annoyances compound
"""

import datetime
import json
import math
import time
import threading
import random
from pathlib import Path
from typing import Optional


# ── Emotion names ────────────────────────────────────────────────────

EMOTIONS = [
    "happy", "bored", "curious", "sleepy",
    "excited", "worried", "focused",
    "frustrated", "content",   # new emotions
]

# ── Baselines (neutral resting state) ────────────────────────────────

BASELINE = {
    "happy":      0.35,
    "bored":      0.1,
    "curious":    0.25,
    "sleepy":     0.0,
    "excited":    0.05,
    "worried":    0.0,
    "focused":    0.15,
    "frustrated": 0.0,
    "content":    0.2,
}

# ── Tick timing ──────────────────────────────────────────────────────

TICK_INTERVAL = 0.5     # seconds between ticks
BASE_DECAY = 0.015      # per tick, toward baseline (slower than v1's 0.02)

# ── Momentum: emotions held longer become "stickier" ─────────────────
# After being above threshold for MOMENTUM_BUILDUP_TICKS, decay rate halves.
# After being above for 2x that, it halves again. Max 4x reduction.

MOMENTUM_THRESHOLD = 0.4            # emotion value must be above this
MOMENTUM_BUILDUP_TICKS = 120       # ~60 seconds at 0.5s ticks
MOMENTUM_MAX_MULTIPLIER = 0.25     # at max momentum, decay is 25% of normal

# ── Energy budget ────────────────────────────────────────────────────
# Starts at 1.0 each day, depletes with activity, recharges with rest.
# Affects how strongly emotions spike and how quickly he tires.

ENERGY_DRAIN_PER_HOUR = 0.05       # passive drain
ENERGY_DRAIN_ACTIVE = 0.02         # extra per behavior triggered
ENERGY_RECHARGE_IDLE = 0.03        # per 15 min idle
ENERGY_RECHARGE_SLEEP = 0.15       # when screen locked / fish sleeping

# ── Vulnerability windows ────────────────────────────────────────────
# After an emotion peaks and drops, the opposite emotion gets a brief boost.

VULNERABILITY_MAP = {
    "excited":  ("sleepy",     0.08, 180),   # mild post-excitement wind-down
    "worried":  ("happy",      0.10, 180),   # relief after worry
    "focused":  ("bored",      0.12, 240),   # post-focus drift
    "frustrated": ("content",  0.08, 120),   # relief after frustration resolves
    "happy":    ("bored",      0.05, 180),   # mild comedown
}
# Format: source_emotion -> (target_emotion, boost_amount, duration_secs)

# ── Frustration stacking ────────────────────────────────────────────
# Annoyances within a time window compound instead of resetting.

FRUSTRATION_WINDOW = 300   # 5 minutes
FRUSTRATION_ESCALATION = [0.1, 0.15, 0.25, 0.4, 0.6]  # each successive annoyance

# ── Seasonal events ──────────────────────────────────────────────────

SEASONAL_EVENTS = {
    (12, 25): ("happy", 0.3, "Christmas"),
    (12, 24): ("excited", 0.2, "Christmas Eve"),
    (10, 31): ("excited", 0.3, "Halloween"),
    (12, 31): ("excited", 0.3, "New Year's Eve"),
    (1, 1):   ("happy", 0.3, "New Year"),
    (2, 14):  ("happy", 0.2, "Valentine's Day"),
    (7, 15):  ("happy", 0.4, "Birthday"),
}

# ── Weather effects ──────────────────────────────────────────────────

WEATHER_EFFECTS = {
    "sunny":         ("happy", 0.15),
    "clear":         ("happy", 0.1),
    "partly cloudy": ("happy", 0.05),
    "cloudy":        ("bored", 0.05),
    "overcast":      ("sleepy", 0.05),
    "rain":          ("sleepy", 0.1),
    "drizzle":       ("sleepy", 0.08),
    "snow":          ("excited", 0.15),
    "thunder":       ("worried", 0.15),
    "fog":           ("sleepy", 0.1),
    "mist":          ("curious", 0.05),
}


# ── File paths ───────────────────────────────────────────────────────

def _appdata_dir() -> Path:
    import os
    appdata = os.environ.get("APPDATA", "")
    d = Path(appdata) / "LittleFish" if appdata else Path.home() / ".littlefish"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _mood_memory_path() -> Path:
    return _appdata_dir() / "mood_memory.json"

def _trust_path() -> Path:
    return _appdata_dir() / "trust.json"

def _emotion_state_path() -> Path:
    return _appdata_dir() / "emotion_state.json"


class EmotionEngine:
    """
    Layer 1 of the three-layer system.
    Manages internal emotional states with momentum, energy, and vulnerability.
    """

    def __init__(self, personality: Optional[dict] = None, user_profile=None):
        # Core state
        self.values: dict[str, float] = dict(BASELINE)
        self.personality = personality or {}
        self._user_profile = user_profile  # UserProfile instance or None

        # Timing
        self._last_tick = time.monotonic()
        self._session_start = time.monotonic()

        # Monday malus
        self._monday_malus_until: float = 0.0

        # Night owl mode (loaded from emotion_config.json)
        self._night_owl = False

        # Effective baselines (modified by profile + personality)
        self._effective_baseline = dict(BASELINE)
        self._apply_personality_baselines()

        # ── Momentum tracking ─────────────────────────────────────
        # For each emotion, how many consecutive ticks it's been above threshold
        self._momentum_ticks: dict[str, int] = {e: 0 for e in EMOTIONS}

        # ── Energy budget ─────────────────────────────────────────
        self._energy = self._load_energy()
        self._last_energy_drain = time.monotonic()

        # ── Vulnerability windows ─────────────────────────────────
        # Active vulnerabilities: {source_emotion: expire_time}
        self._vulnerabilities: dict[str, float] = {}
        self._peak_tracker: dict[str, float] = {e: 0.0 for e in EMOTIONS}

        # ── Frustration stacking ──────────────────────────────────
        self._frustration_events: list[float] = []  # timestamps of recent annoyances

        # ── Mood arc ──────────────────────────────────────────────
        # Slow-moving target that the baselines drift toward over hours
        self._mood_arc_target: dict[str, float] = dict(BASELINE)
        self._mood_arc_timer: float = 0.0

        # ── Compound emotion tracking ────────────────────────────
        self._last_compound: tuple[str, str] = ("content", "curious")

        # ── Seasonal ──────────────────────────────────────────────
        self._seasonal_applied_today: str = ""
        self._check_seasonal()

        # ── Weather ───────────────────────────────────────────────
        self._weather_condition: str = ""
        self._weather_last_check: float = 0.0
        self._fetch_weather_async()

        # ── Mood memory (carry-over from yesterday) ──────────────
        self._load_mood_memory()

        # ── Trust (backward-compatible) ──────────────────────────
        self._trust = self._load_trust()
        self._trust_save_timer: float = 0.0

        # ── Load persisted emotional state if recent ─────────────
        self._load_emotion_state()

    # ==================================================================
    # Public API
    # ==================================================================

    def update(self, dt: float):
        """Called frequently. Only ticks every TICK_INTERVAL seconds."""
        now = time.monotonic()
        if now - self._last_tick < TICK_INTERVAL:
            return
        self._last_tick = now

        self._decay()
        self._update_momentum()
        self._update_energy(now)
        self._check_vulnerability_triggers()
        self._update_mood_arc()

        # Periodic weather refresh (every 30 min)
        if now - self._weather_last_check > 1800:
            self._fetch_weather_async()

        # Periodic trust save (every 5 min)
        self._trust_save_timer += TICK_INTERVAL
        if self._trust_save_timer > 300:
            self._trust_save_timer = 0
            self._save_trust()

        # Save emotion state every 2 minutes for persistence
        if int(now) % 120 < 1:
            self._save_emotion_state()

    def spike(self, emotion: str, amount: float):
        """Increase an emotion, modulated by energy and profile."""
        if emotion not in self.values:
            return
        # Energy modulates spike strength
        effective = amount * self._energy_spike_multiplier()
        # Profile energy multiplier
        if self._user_profile:
            effective *= self._user_profile.energy_multiplier_now()
        self.values[emotion] = min(1.0, self.values[emotion] + effective)

    def reduce(self, emotion: str, amount: float):
        """Decrease an emotion by amount, clamped to [0, 1]."""
        if emotion in self.values:
            self.values[emotion] = max(0.0, self.values[emotion] - amount)

    def dominant_emotion(self) -> str:
        """Return the emotion with the highest current value."""
        return max(self.values, key=self.values.get)

    def compound_emotion(self) -> tuple[str, str]:
        """Return the top-2 emotions as a compound mood."""
        sorted_emos = sorted(self.values.items(), key=lambda x: x[1], reverse=True)
        primary = sorted_emos[0][0]
        secondary = sorted_emos[1][0] if len(sorted_emos) > 1 else primary
        self._last_compound = (primary, secondary)
        return (primary, secondary)

    def compound_emotion_label(self) -> str:
        """Human-readable compound emotion string."""
        p, s = self.compound_emotion()
        if p == s:
            return p
        # Only show secondary if it's significant (>0.2)
        if self.values.get(s, 0) > 0.2:
            return f"{p} but {s}"
        return p

    def get(self, emotion: str) -> float:
        return self.values.get(emotion, 0.0)

    @property
    def energy(self) -> float:
        """Current energy level 0.0-1.0."""
        return self._energy

    def drain_energy(self, amount: float = ENERGY_DRAIN_ACTIVE):
        """Called when fish performs an active behavior."""
        self._energy = max(0.0, self._energy - amount)

    def wake_up(self):
        """Forcefully wake the fish — called from chat or click."""
        self.values["sleepy"] = max(0.0, self.values["sleepy"] - 0.6)
        self._momentum_ticks["sleepy"] = 0
        self.spike("curious", 0.2)
        self._energy = min(1.0, self._energy + 0.05)

    def on_conversation(self):
        """Called when the user chats — small energy recharge + wake nudge."""
        self._energy = min(1.0, self._energy + 0.02)
        if self.values.get("sleepy", 0) > 0.4:
            self.values["sleepy"] = max(0.15, self.values["sleepy"] - 0.2)

    # ==================================================================
    # Signal methods — called by SystemMonitor / widget
    # ==================================================================

    def on_late_night(self):
        if self._night_owl:
            return  # night owls don't get sleepy from late_night event
        # Respect chronotype — night owls don't get sleepy as early
        if self._user_profile:
            threshold = self._user_profile.chronotype_curve.get("late_night_threshold", 23)
            hour = datetime.datetime.now().hour
            if hour < threshold and hour > 12:
                return  # not late for this user
        self.spike("sleepy", 0.2)

    def on_idle_15min(self):
        self.spike("bored", 0.3)

    def on_idle_45min(self):
        if not self._night_owl:
            self.spike("sleepy", 0.15)
        self.spike("bored", 0.1)
        # Recharge energy during idle
        self._energy = min(1.0, self._energy + ENERGY_RECHARGE_IDLE)

    def on_code_editor_active(self):
        self.spike("focused", 0.4)
        self.reduce("bored", 0.2)

    def on_youtube_watching(self):
        self.spike("happy", 0.3)

    def on_cpu_high(self):
        self.spike("worried", 0.2)

    def on_cpu_spike(self):
        self.spike("worried", 0.4)

    def on_battery_low(self):
        self.spike("worried", 0.4)

    def on_fish_clicked(self):
        self.spike("curious", 0.5)
        self.spike("happy", 0.2)
        # Clicking should ALWAYS wake the fish up decisively
        if self.values.get("sleepy", 0) > 0.3:
            self.values["sleepy"] = max(0.1, self.values["sleepy"] - 0.5)
            self._momentum_ticks["sleepy"] = 0  # reset sleepy momentum
        # Small energy boost from interaction
        self._energy = min(1.0, self._energy + 0.02)

    def on_mic_active(self):
        self.spike("curious", 0.3)

    def on_user_returned(self):
        self.spike("excited", 0.6)
        self.reduce("sleepy", 0.3)
        self._momentum_ticks["sleepy"] = 0
        # Energy boost on return
        self._energy = min(1.0, self._energy + 0.15)

    def on_morning(self):
        if self._user_profile:
            gh = self._user_profile.chronotype_curve.get("greeting_hour", 9)
            hour = datetime.datetime.now().hour
            if abs(hour - gh) <= 1:
                self.spike("happy", 0.15)
                return
        self.spike("happy", 0.1)

    def on_monday(self):
        self._monday_malus_until = time.monotonic() + 1800

    def on_battery_plugged(self):
        self.spike("happy", 0.3)
        self._trust_positive()

    def on_music_detected(self):
        self.spike("happy", 0.2)
        self.reduce("bored", 0.15)

    def on_game_detected(self):
        self.spike("excited", 0.3)
        self.reduce("bored", 0.2)

    def on_cpu_normal(self):
        self.spike("happy", 0.15)
        self.reduce("worried", 0.3)

    def on_battery_full(self):
        self.spike("excited", 0.3)
        self.spike("happy", 0.2)

    def on_ram_high(self):
        self.spike("worried", 0.3)

    def on_usb_connected(self):
        self.spike("curious", 0.3)

    def on_screen_locked(self):
        self.spike("sleepy", 0.4)
        self._energy = min(1.0, self._energy + ENERGY_RECHARGE_SLEEP)

    def on_screen_unlocked(self):
        self.spike("excited", 0.5)
        self.spike("happy", 0.3)

    def on_midnight(self):
        if not self._night_owl:
            self.spike("sleepy", 0.3)

    def on_new_hour(self):
        self.spike("curious", 0.1)

    def on_clipboard_changed(self):
        self.spike("curious", 0.1)

    def on_network_lost(self):
        self.spike("worried", 0.3)

    def on_network_restored(self):
        self.spike("happy", 0.2)
        self.reduce("worried", 0.2)

    def on_fullscreen_entered(self):
        self.spike("focused", 0.3)
        self.reduce("bored", 0.2)

    def on_fullscreen_exited(self):
        self.spike("curious", 0.15)

    def on_compliment(self):
        self.spike("happy", 0.6)
        self.spike("excited", 0.3)
        self._trust_positive()

    def on_insult(self):
        self.spike("worried", 0.4)
        self.reduce("happy", 0.3)
        self._register_frustration()
        self._trust_negative()

    def on_name_called(self):
        self.spike("curious", 0.3)
        self.spike("happy", 0.2)

    def on_whisper_detected(self):
        self.spike("curious", 0.4)

    def on_singing_detected(self):
        self.spike("happy", 0.3)
        self.spike("excited", 0.2)

    # ── New v2 signal methods ────────────────────────────────────

    def on_rapid_app_switching(self):
        """User is rapidly switching apps — frustrating/restless."""
        self._register_frustration()
        self.spike("curious", 0.15)

    def on_error_detected(self):
        """Compile error, crash, etc."""
        self.spike("worried", 0.15)
        self.spike("curious", 0.1)

    def on_long_work_session(self, hours: float):
        """Called when user has been working continuously."""
        # Energy drain scales with duration
        drain = min(0.3, hours * 0.08)
        self._energy = max(0.0, self._energy - drain)
        if hours > 2:
            self.spike("focused", 0.2)
            self.spike("worried", 0.1)  # mild concern
        if hours > 4:
            self.spike("worried", 0.2)
            self.reduce("happy", 0.1)

    def on_question_ignored(self):
        """Fish asked something and user didn't respond."""
        self._register_frustration()
        self.reduce("happy", 0.1)
        self.spike("bored", 0.15)

    def on_game_finished(self, won: bool):
        """User finished a game with the fish."""
        if won:
            self.spike("happy", 0.2)
            self.spike("excited", 0.15)
        else:
            self.spike("curious", 0.1)
            # slightly smug
            self.spike("happy", 0.1)

    def on_petting(self):
        """Slow mouse movement detected as petting."""
        self.spike("happy", 0.4)
        self.spike("content", 0.3)
        self._trust_positive()

    def on_shaken(self):
        """Fish was shaken roughly."""
        self.spike("worried", 0.5)
        self.reduce("happy", 0.2)
        self._register_frustration()
        self._trust_negative()

    # ==================================================================
    # Trust level (backward-compatible with v1)
    # ==================================================================

    @property
    def trust_level(self) -> float:
        return self._trust.get("level", 0.5)

    def _trust_positive(self):
        lvl = self._trust.get("level", 0.5)
        self._trust["level"] = min(1.0, lvl + 0.005)
        self._trust["positive"] = self._trust.get("positive", 0) + 1

    def _trust_negative(self):
        lvl = self._trust.get("level", 0.5)
        self._trust["level"] = max(0.0, lvl - 0.01)
        self._trust["negative"] = self._trust.get("negative", 0) + 1

    def on_positive_interaction(self):
        self._trust_positive()

    def on_negative_interaction(self):
        self._trust_negative()

    def _load_trust(self) -> dict:
        try:
            p = _trust_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return {"level": 0.5, "positive": 0, "negative": 0}

    def _save_trust(self):
        try:
            _trust_path().write_text(json.dumps(self._trust, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ==================================================================
    # Seasonal awareness
    # ==================================================================

    def _check_seasonal(self):
        now = datetime.date.today()
        key = (now.month, now.day)
        day_str = now.isoformat()
        if day_str == self._seasonal_applied_today:
            return
        if key in SEASONAL_EVENTS:
            emotion, amount, _ = SEASONAL_EVENTS[key]
            self.spike(emotion, amount)
            self._seasonal_applied_today = day_str

    def get_seasonal_event(self) -> Optional[str]:
        now = datetime.date.today()
        key = (now.month, now.day)
        if key in SEASONAL_EVENTS:
            return SEASONAL_EVENTS[key][2]
        return None

    # ==================================================================
    # Weather integration
    # ==================================================================

    def _fetch_weather_async(self):
        self._weather_last_check = time.monotonic()
        thread = threading.Thread(target=self._fetch_weather_thread, daemon=True)
        thread.start()

    def _fetch_weather_thread(self):
        try:
            from urllib.request import urlopen, Request
            from urllib.error import URLError
            req = Request("https://wttr.in/?format=%C", headers={"User-Agent": "LittleFish"})
            with urlopen(req, timeout=5) as resp:
                condition = resp.read().decode("utf-8").strip().lower()
                self._weather_condition = condition
                self._apply_weather(condition)
        except Exception:
            pass

    def _apply_weather(self, condition: str):
        for keyword, (emotion, amount) in WEATHER_EFFECTS.items():
            if keyword in condition:
                self.spike(emotion, amount)
                return

    @property
    def weather(self) -> str:
        return self._weather_condition

    # ==================================================================
    # Mood memory (yesterday affects today)
    # ==================================================================

    def _load_mood_memory(self):
        try:
            p = _mood_memory_path()
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            if data.get("date") == yesterday:
                interactions = data.get("interactions", 0)
                if interactions < 3:
                    self.spike("bored", 0.2)
                    self.reduce("happy", 0.1)
                elif interactions > 20:
                    self.spike("happy", 0.15)
                    self.spike("content", 0.1)

                # v2: carry over dominant mood slightly
                prev_dominant = data.get("dominant", "")
                if prev_dominant in self.values:
                    self.spike(prev_dominant, 0.08)  # subtle carryover
        except (OSError, json.JSONDecodeError):
            pass

    def save_mood_memory(self, interaction_count: int):
        try:
            data = {
                "date": datetime.date.today().isoformat(),
                "dominant": self.dominant_emotion(),
                "compound": list(self.compound_emotion()),
                "interactions": interaction_count,
                "emotions": {k: round(v, 3) for k, v in self.values.items()},
                "energy": round(self._energy, 3),
            }
            _mood_memory_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ==================================================================
    # MOMENTUM SYSTEM
    # ==================================================================

    def _update_momentum(self):
        """Track how long each emotion has been above threshold."""
        for e in EMOTIONS:
            if self.values.get(e, 0) >= MOMENTUM_THRESHOLD:
                self._momentum_ticks[e] = self._momentum_ticks.get(e, 0) + 1
            else:
                # Momentum bleeds off gradually, not instantly
                current = self._momentum_ticks.get(e, 0)
                if current > 0:
                    self._momentum_ticks[e] = max(0, current - 2)

    def _momentum_decay_multiplier(self, emotion: str) -> float:
        """
        How much momentum slows down decay.
        Returns 1.0 (no effect) to MOMENTUM_MAX_MULTIPLIER (max stickiness).
        Sleepy momentum is capped — we never want the fish permanently stuck asleep.
        """
        ticks = self._momentum_ticks.get(emotion, 0)
        if ticks < MOMENTUM_BUILDUP_TICKS:
            return 1.0
        # Sleepy can only get 2x sticky (0.5 multiplier), not 4x
        max_mult = 0.5 if emotion == "sleepy" else MOMENTUM_MAX_MULTIPLIER
        # Scale from 1.0 down to max_mult over 4x buildup ticks
        progress = min(1.0, (ticks - MOMENTUM_BUILDUP_TICKS) / (MOMENTUM_BUILDUP_TICKS * 3))
        return 1.0 - progress * (1.0 - max_mult)

    # ==================================================================
    # ENERGY BUDGET
    # ==================================================================

    def _load_energy(self) -> float:
        """Load energy from persisted state, or start fresh."""
        try:
            p = _emotion_state_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                saved_date = data.get("energy_date", "")
                today = datetime.date.today().isoformat()
                if saved_date == today:
                    return data.get("energy", 1.0)
        except (OSError, json.JSONDecodeError):
            pass
        return 1.0  # fresh day, full energy

    def _update_energy(self, now: float):
        """Passive energy drain over time."""
        elapsed = now - self._last_energy_drain
        if elapsed >= 3600:  # every hour
            self._energy = max(0.0, self._energy - ENERGY_DRAIN_PER_HOUR)
            self._last_energy_drain = now

            # Low energy makes fish tired — but respect night owl
            night_owl = getattr(self, '_night_owl', False)
            if self._energy < 0.3 and not night_owl:
                self.spike("sleepy", 0.05)
                self.reduce("excited", 0.05)
            if self._energy < 0.15 and not night_owl:
                self.spike("sleepy", 0.08)

    def _energy_spike_multiplier(self) -> float:
        """When energy is low, emotions spike less intensely."""
        if self._energy > 0.5:
            return 1.0
        # Linear scale from 1.0 at 0.5 energy to 0.5 at 0 energy
        return 0.5 + self._energy

    # ==================================================================
    # VULNERABILITY WINDOWS
    # ==================================================================

    def _check_vulnerability_triggers(self):
        """
        When an emotion that was high starts dropping, trigger vulnerability.
        E.g., excited was 0.8, now dropping below 0.4 → trigger sleepy boost.
        """
        now = time.monotonic()

        for emotion in EMOTIONS:
            current = self.values.get(emotion, 0)
            peak = self._peak_tracker.get(emotion, 0)

            # Track peaks
            if current > peak:
                self._peak_tracker[emotion] = current

            # Check for significant drop from peak
            if emotion in VULNERABILITY_MAP and peak > 0.6 and current < 0.35:
                if emotion not in self._vulnerabilities:
                    target_emo, boost, duration = VULNERABILITY_MAP[emotion]
                    self._vulnerabilities[emotion] = now + duration
                    self.spike(target_emo, boost)
                    # Reset peak
                    self._peak_tracker[emotion] = current

        # Clean expired vulnerabilities
        expired = [e for e, t in self._vulnerabilities.items() if now > t]
        for e in expired:
            del self._vulnerabilities[e]

    # ==================================================================
    # FRUSTRATION STACKING
    # ==================================================================

    def _register_frustration(self):
        """Register an annoyance. More annoyances in a window = bigger reaction."""
        now = time.monotonic()
        # Clear old events outside the window
        self._frustration_events = [
            t for t in self._frustration_events
            if now - t < FRUSTRATION_WINDOW
        ]
        self._frustration_events.append(now)

        # Escalating response
        count = len(self._frustration_events)
        idx = min(count - 1, len(FRUSTRATION_ESCALATION) - 1)
        amount = FRUSTRATION_ESCALATION[idx]
        self.values["frustrated"] = min(1.0, self.values.get("frustrated", 0) + amount)

        # High frustration reduces happy
        if count >= 3:
            self.reduce("happy", 0.1)
        if count >= 5:
            self.reduce("happy", 0.2)
            self.reduce("content", 0.15)

    @property
    def frustration_level(self) -> int:
        """How many frustration events in the current window."""
        now = time.monotonic()
        return len([t for t in self._frustration_events if now - t < FRUSTRATION_WINDOW])

    # ==================================================================
    # MOOD ARCS
    # ==================================================================

    def _update_mood_arc(self):
        """
        Slowly shift baseline targets based on time of day and profile.
        Creates natural multi-hour emoji trajectories.
        """
        self._mood_arc_timer += TICK_INTERVAL
        if self._mood_arc_timer < 60:  # update arc every 60 seconds
            return
        self._mood_arc_timer = 0

        hour = datetime.datetime.now().hour

        # Base arc: natural daily rhythm
        arc = dict(BASELINE)

        # Time-of-day arc
        night_owl = getattr(self, '_night_owl', False)
        if 6 <= hour <= 10:       # Morning
            arc["happy"] += 0.1
            arc["excited"] += 0.05
            arc["content"] += 0.05
        elif 10 <= hour <= 14:    # Midday
            arc["focused"] += 0.08
            arc["content"] += 0.08
        elif 14 <= hour <= 17:    # Afternoon
            arc["content"] += 0.05
            arc["bored"] += 0.03
        elif 17 <= hour <= 20:    # Evening
            arc["content"] += 0.1
            if not night_owl:
                arc["sleepy"] += 0.02
        elif 20 <= hour <= 23:    # Night
            arc["content"] += 0.05
            arc["curious"] += 0.03
            if not night_owl:
                arc["sleepy"] += 0.05
        else:                      # Late night / early morning
            arc["curious"] += 0.05
            if not night_owl:
                arc["sleepy"] += 0.08

        # Profile-based arc adjustments
        if self._user_profile:
            if self._user_profile.is_peak_hour(hour):
                arc["happy"] += 0.05
                arc["excited"] += 0.03
                arc["sleepy"] -= 0.05
            else:
                arc["sleepy"] += 0.05
                arc["excited"] -= 0.03

        # Clamp arc values
        for e in EMOTIONS:
            arc[e] = max(0.0, min(0.6, arc.get(e, 0.0)))

        self._mood_arc_target = arc

    # ==================================================================
    # CORE DECAY (the heartbeat)
    # ==================================================================

    def _decay(self):
        """Move each emotion toward its effective baseline, modulated by momentum."""
        now = time.monotonic()
        for e in EMOTIONS:
            baseline = self._effective_baseline.get(e, 0.0)

            # Monday malus
            if e == "happy" and now < self._monday_malus_until:
                baseline = max(0.0, baseline - 0.1)

            # Blend baseline toward mood arc target (slow drift)
            arc_target = self._mood_arc_target.get(e, baseline)
            baseline = baseline * 0.7 + arc_target * 0.3

            # Time-of-day modifier
            baseline = max(0.0, min(1.0, baseline + self._time_modifier(e)))

            # Energy-sleepy gate: high energy suppresses sleepy baseline
            if e == "sleepy" and self._energy > 0.5:
                # Scale down sleepy baseline proportionally to energy
                suppress = (self._energy - 0.5) * 0.8  # 0 at 0.5 energy, 0.4 at 1.0
                baseline = max(0.0, baseline - suppress)

            # Calculate effective decay rate
            decay = BASE_DECAY * self._momentum_decay_multiplier(e)

            # Sleepy decays faster when energy is high
            if e == "sleepy" and self._energy > 0.6:
                decay *= 2.0

            current = self.values[e]
            if abs(current - baseline) < decay:
                self.values[e] = baseline
            elif current > baseline:
                self.values[e] = current - decay
            else:
                self.values[e] = current + decay

    def _time_modifier(self, emotion: str) -> float:
        now = datetime.datetime.now()
        hour = now.hour
        mod = 0.0

        night_owl = getattr(self, '_night_owl', False)

        if 8 <= hour <= 11:
            if emotion == "happy":
                mod += 0.1
            elif emotion == "excited":
                mod += 0.05
        elif hour >= 23 or hour <= 5:
            if not night_owl:
                if emotion == "sleepy":
                    mod += 0.12
                elif emotion == "happy":
                    mod -= 0.05
                elif emotion == "excited":
                    mod -= 0.05
        elif 17 <= hour <= 22:
            if emotion == "sleepy" and not night_owl:
                mod += 0.03

        # Friday boost
        if now.weekday() == 4:
            if emotion == "happy":
                mod += 0.05
            elif emotion == "excited":
                mod += 0.05

        return mod

    def _apply_personality_baselines(self):
        """Modify baselines based on personality config + user overrides."""
        if "curiosity_baseline" in self.personality:
            self._effective_baseline["curious"] = self.personality["curiosity_baseline"] * 0.5

        # Load user emotion overrides from emotion_config.json
        try:
            p = _emotion_state_path().parent / "emotion_config.json"
            if p.exists():
                overrides = json.loads(p.read_text(encoding="utf-8"))
                self._night_owl = overrides.get("night_owl", False)
                for emo in EMOTIONS:
                    if emo in overrides:
                        val = max(0.0, min(0.6, float(overrides[emo])))
                        self._effective_baseline[emo] = val
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    # ==================================================================
    # Emotion state persistence (for session continuity)
    # ==================================================================

    def _save_emotion_state(self):
        """Save current emotional state for warm restart."""
        try:
            data = {
                "values": {k: round(v, 4) for k, v in self.values.items()},
                "energy": round(self._energy, 4),
                "energy_date": datetime.date.today().isoformat(),
                "momentum": dict(self._momentum_ticks),
                "saved_at": datetime.datetime.now().isoformat(),
            }
            _emotion_state_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_emotion_state(self):
        """Load persisted emotional state if recent (within 30 min)."""
        try:
            p = _emotion_state_path()
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            saved_at = data.get("saved_at", "")
            if not saved_at:
                return
            saved_dt = datetime.datetime.fromisoformat(saved_at)
            delta = (datetime.datetime.now() - saved_dt).total_seconds()
            if delta < 1800:  # 30 minutes — resume where we left off
                saved_values = data.get("values", {})
                for e in EMOTIONS:
                    if e in saved_values:
                        self.values[e] = saved_values[e]
                self._momentum_ticks = data.get("momentum", self._momentum_ticks)
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    # ==================================================================
    # Snapshot for external systems
    # ==================================================================

    def snapshot(self) -> dict:
        """Full state snapshot for shared_state / launcher / debugging."""
        return {
            "values": {k: round(v, 3) for k, v in self.values.items()},
            "dominant": self.dominant_emotion(),
            "compound": list(self.compound_emotion()),
            "compound_label": self.compound_emotion_label(),
            "energy": round(self._energy, 3),
            "frustration_level": self.frustration_level,
            "momentum": {k: v for k, v in self._momentum_ticks.items() if v > 0},
            "active_vulnerabilities": list(self._vulnerabilities.keys()),
            "trust": round(self.trust_level, 3),
            "weather": self._weather_condition,
        }

    def get_emotion_context_for_chat(self) -> str:
        """Generate emotion context string for AI chat system prompt."""
        primary, secondary = self.compound_emotion()
        energy = self._energy
        frustration = self.frustration_level

        parts = [f"You are currently feeling {primary}."]

        if secondary != primary and self.values.get(secondary, 0) > 0.2:
            parts.append(f"There's also an undercurrent of {secondary}.")

        if energy < 0.3:
            parts.append("You're running low on energy. Responses should be shorter and more subdued.")
        elif energy > 0.8:
            parts.append("You're energetic right now.")

        if frustration >= 3:
            parts.append("You're getting frustrated. Show it subtly — shorter responses, slight edge.")
        elif frustration >= 5:
            parts.append("You're genuinely annoyed. Be terse. Don't fake positivity.")

        # Check for active vulnerability windows
        if self._vulnerabilities:
            sources = list(self._vulnerabilities.keys())
            if "excited" in sources:
                parts.append("You're coming down from excitement. Feeling a bit drained.")
            if "focused" in sources:
                parts.append("You just came out of deep focus. A bit spacey.")

        return " ".join(parts)
