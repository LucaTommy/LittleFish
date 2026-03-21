"""
Autonomous behavior engine for Little Fish.
Runs on a QTimer, ticking every 45 seconds. Each tick has a chance to trigger
a behavior from the pool valid for the current emotion/time/system state.

v2: Profile-aware, relationship-aware, escalation ladders, opinions, backstory.
"""

import random
import time
import datetime
from dataclasses import dataclass, field
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


BEHAVIOR_TICK_MS = 30_000      # 30 seconds
BEHAVIOR_CHANCE = 0.40          # 40% base


@dataclass
class Behavior:
    name: str
    category: str               # idle, time, curiosity, attention, work, world, personality, reactive, relationship
    action: str                 # signal payload: what to do
    message: Optional[str] = None
    cooldown: int = 300          # seconds before same behavior can repeat
    condition: Optional[Callable] = None   # extra condition check
    last_used: float = 0.0
    priority: int = 0           # higher = picked first when multiple valid


class BehaviorEngine(QObject):
    """Background behavior tick system. Emits signals for the widget to act on."""

    # Emitted when a behavior triggers. Widget connects to this.
    behavior_triggered = pyqtSignal(str, str)   # (action, message)

    # Emitted for special actions that need more context than (action, message)
    special_triggered = pyqtSignal(str, dict)   # (type, data)

    def __init__(self, emotion_getter, monitor=None, user_profile=None,
                 relationship=None, emotion_engine=None, parent=None):
        super().__init__(parent)
        self._emotion_getter = emotion_getter   # callable -> str
        self._monitor = monitor
        self._user_profile = user_profile       # UserProfile instance
        self._relationship = relationship       # Relationship instance
        self._emotion_engine = emotion_engine   # EmotionEngine for night_owl etc.
        self._intensity = 1.0                   # 0-1 scale from settings
        self._enabled = True
        self._last_interaction = time.monotonic()
        self._active_app = ""
        self._install_date = None
        self._birthday = None

        # Boredom escalation tracking
        self._boredom_level = 0        # 0-4, escalates with sustained boredom
        self._last_boredom_tick = 0.0
        self._boredom_escalation_interval = 180  # seconds between escalations

        # Break advocacy tracking
        self._break_reminders_given = 0
        self._last_break_reminder = 0.0

        self._behaviors = self._build_pool()

        self._timer = QTimer(self)
        self._timer.setInterval(BEHAVIOR_TICK_MS)
        self._timer.timeout.connect(self._tick)

    def start(self):
        if self._enabled:
            self._timer.start()

    def stop(self):
        self._timer.stop()

    def set_enabled(self, on: bool):
        self._enabled = on
        if on:
            self._timer.start()
        else:
            self._timer.stop()

    def set_intensity(self, pct: int):
        """pct 0-100 scales behavior_chance."""
        self._intensity = max(0.0, min(1.0, pct / 100.0))

    def record_interaction(self):
        self._last_interaction = time.monotonic()
        self._boredom_level = max(0, self._boredom_level - 1)

    def set_active_app(self, name: str):
        self._active_app = name.lower() if name else ""

    def set_install_date(self, d):
        self._install_date = d

    def set_birthday(self, d):
        self._birthday = d

    # ------------------------------------------------------------------

    def _tick(self):
        if not self._enabled:
            return

        emo = self._emotion_getter()
        now = time.monotonic()

        # When sleeping, only allow wake_up behavior
        if emo == "sleepy":
            for b in self._behaviors:
                if b.name == "wake_up" and now - b.last_used >= b.cooldown:
                    if b.condition and not b.condition(emo, 0, 0, 0, ""):
                        return
                    b.last_used = now
                    msg = b.message or ""
                    self.behavior_triggered.emit(b.action, msg)
                    return
            return

        # Talkativeness affects base chance
        talk_mult = 1.0
        if self._user_profile:
            talk_mult = self._user_profile.effective_chattiness()

        chance = BEHAVIOR_CHANCE * self._intensity * talk_mult

        # Emotion modifiers
        emo_mults = {
            "bored": 1.4, "focused": 0.5, "sleepy": 0.7,
            "excited": 1.2, "frustrated": 0.8, "content": 0.9,
            "curious": 1.1,
        }
        chance *= emo_mults.get(emo, 1.0)

        # Boredom escalation — sustained boredom increases activity
        if emo == "bored":
            if now - self._last_boredom_tick > self._boredom_escalation_interval:
                self._boredom_level = min(4, self._boredom_level + 1)
                self._last_boredom_tick = now
            chance *= (1.0 + self._boredom_level * 0.15)
        else:
            if self._boredom_level > 0 and now - self._last_boredom_tick > 60:
                self._boredom_level = max(0, self._boredom_level - 1)
                self._last_boredom_tick = now

        if random.random() > chance:
            return

        # Build pool of valid behaviors for current context
        hour = datetime.datetime.now().hour
        dow = datetime.datetime.now().weekday()  # 0=Mon
        idle_secs = now - self._last_interaction
        rel_stage = self._relationship.stage if self._relationship else "stranger"

        valid = []
        for b in self._behaviors:
            # Cooldown check
            if now - b.last_used < b.cooldown:
                continue
            # Condition check
            if b.condition and not b.condition(emo, hour, dow, idle_secs, self._active_app):
                continue
            valid.append(b)

        if not valid:
            return

        # Weighted selection: higher priority behaviors are more likely
        if any(b.priority > 0 for b in valid):
            weights = [1 + b.priority * 3 for b in valid]
            pick = random.choices(valid, weights=weights, k=1)[0]
        else:
            pick = random.choice(valid)

        pick.last_used = now

        # Track break reminder escalation so firm reminder can follow gentle
        if pick.name in ("break_gentle", "break_firm"):
            self._break_reminders_given += 1

        # Resolve dynamic messages for behaviors with no static message
        msg = pick.message or ""
        if not msg:
            msg = self._resolve_dynamic_message(pick.name)

        self.behavior_triggered.emit(pick.action, msg)

    # ------------------------------------------------------------------

    def _resolve_dynamic_message(self, behavior_name: str) -> str:
        """Generate message at runtime for behaviors that don't have static text."""
        resolvers = {
            "morning_greet": self.get_morning_greeting,
            "late_night": self.get_late_night_message,
            "bored_sigh_verbal": self.get_bored_escalation_message,
            "bored_poke": self.get_bored_escalation_message,
            "bored_dramatic": self.get_bored_escalation_message,
            "break_gentle": lambda: self.get_break_message("gentle"),
            "break_firm": lambda: self.get_break_message("firm"),
            "time_comment": lambda: random.choice([
                "It's the dead of night. Even the pixels are sleeping.",
                "Why are we awake right now?",
                "The 3am crowd is a different breed.",
            ]),
        }
        resolver = resolvers.get(behavior_name)
        if resolver:
            return resolver()
        return ""

    # ------------------------------------------------------------------

    def _build_pool(self) -> list[Behavior]:
        B = Behavior
        pool = []

        # === Idle & Ambient ===
        pool.append(B("fall_asleep", "idle", "sleep",
                       "zzz...", cooldown=1800,
                       condition=self._cond_fall_asleep))
        pool.append(B("wake_up", "idle", "wake_up",
                       "*yawns* ...huh?", cooldown=600,
                       condition=lambda e, h, d, idle, app: e == "sleepy"))
        pool.append(B("yawn", "idle", "yawn",
                       None, cooldown=120,
                       condition=lambda e, h, d, idle, app: e == "sleepy"))
        pool.append(B("stare_off", "idle", "stare",
                       None, cooldown=90))
        pool.append(B("stretch", "idle", "stretch",
                       None, cooldown=180))
        pool.append(B("look_around", "idle", "look_around",
                       None, cooldown=60))
        pool.append(B("spin", "idle", "spin",
                       None, cooldown=300,
                       condition=lambda e, h, d, idle, app: e in ("happy", "bored", "content")))
        pool.append(B("sigh", "idle", "sigh",
                       None, cooldown=180,
                       condition=lambda e, h, d, idle, app: e in ("bored", "frustrated")))

        # === Time-Triggered (profile-aware) ===
        pool.append(B("morning_greet", "time", "say",
                       None, cooldown=3600, priority=2,
                       condition=self._cond_morning_greet))
        pool.append(B("lunch_nudge", "time", "say",
                       "You eaten?", cooldown=3600,
                       condition=lambda e, h, d, idle, app: h == 12))
        pool.append(B("end_of_day", "time", "say",
                       "That's enough work for today, probably.", cooldown=3600,
                       condition=lambda e, h, d, idle, app: h == 17))
        pool.append(B("late_night", "time", "say",
                       None, cooldown=3600,
                       condition=self._cond_late_night))
        pool.append(B("midnight", "time", "sleepy_lock",
                       "*yawns deeply*", cooldown=3600,
                       condition=self._cond_midnight))
        pool.append(B("monday_grump", "time", "grumpy",
                       "Ugh. Monday.", cooldown=1800,
                       condition=lambda e, h, d, idle, app: d == 0 and h < 12))
        pool.append(B("friday_hype", "time", "say",
                       "It's Friday. Things are looking up.", cooldown=3600,
                       condition=lambda e, h, d, idle, app: d == 4 and h >= 14))
        pool.append(B("hour_chime", "time", "blink",
                       None, cooldown=3500,
                       condition=lambda e, h, d, idle, app: datetime.datetime.now().minute == 0))

        # === Curiosity ===
        pool.append(B("notice_youtube", "curiosity", "say",
                       "Oh, are we watching something?", cooldown=600,
                       condition=lambda e, h, d, idle, app: "youtube" in app))
        pool.append(B("notice_game", "curiosity", "excited",
                       "Oh nice, you're gaming.", cooldown=600,
                       condition=lambda e, h, d, idle, app: any(
                           g in app for g in ("steam", "epic", "game"))))
        pool.append(B("cpu_spike", "curiosity", "worried",
                       "Something's working hard...", cooldown=300))

        # === Attention-Seeking (boredom escalation) ===
        pool.append(B("relocate", "attention", "wander",
                       None, cooldown=300,
                       condition=lambda e, h, d, idle, app: e == "bored"))
        pool.append(B("throw_particle", "attention", "throw_particle",
                       None, cooldown=120,
                       condition=lambda e, h, d, idle, app: e == "bored"))
        pool.append(B("random_bounce", "attention", "bounce",
                       None, cooldown=180,
                       condition=lambda e, h, d, idle, app: e == "bored"))
        pool.append(B("stare_at_cursor", "attention", "follow_cursor",
                       None, cooldown=300,
                       condition=lambda e, h, d, idle, app: e == "bored" and idle > 60))
        pool.append(B("little_dance", "attention", "dance",
                       None, cooldown=300,
                       condition=lambda e, h, d, idle, app: e == "bored"))
        pool.append(B("blow_bubble", "attention", "bubble_particle",
                       None, cooldown=240,
                       condition=lambda e, h, d, idle, app: e == "bored"))
        pool.append(B("peek_edge", "attention", "peek_edge",
                       None, cooldown=300,
                       condition=lambda e, h, d, idle, app: e == "bored"))

        # Boredom escalation behaviors (only at higher boredom levels)
        pool.append(B("bored_sigh_verbal", "attention", "say",
                       None, cooldown=300, priority=1,
                       condition=self._cond_bored_escalation_1))
        pool.append(B("bored_poke", "attention", "say",
                       None, cooldown=600, priority=2,
                       condition=self._cond_bored_escalation_2))
        pool.append(B("bored_dramatic", "attention", "say",
                       None, cooldown=900, priority=3,
                       condition=self._cond_bored_escalation_3))

        # === Work-Aware ===
        pool.append(B("focus_mode", "work", "focus",
                       None, cooldown=600,
                       condition=lambda e, h, d, idle, app: any(
                           c in app for c in ("code", "vscode", "visual studio"))))
        pool.append(B("stackoverflow_sympathy", "work", "say",
                       "Struggling, huh?", cooldown=600,
                       condition=lambda e, h, d, idle, app: "stackoverflow" in app))
        pool.append(B("github_nod", "work", "say",
                       "Respect.", cooldown=600,
                       condition=lambda e, h, d, idle, app: "github" in app))

        # === Break advocacy (profile-aware) ===
        pool.append(B("break_gentle", "work", "say",
                       None, cooldown=3600, priority=1,
                       condition=self._cond_break_gentle))
        pool.append(B("break_firm", "work", "say",
                       None, cooldown=7200, priority=2,
                       condition=self._cond_break_firm))

        # === World-Aware ===
        pool.append(B("time_comment", "world", "say",
                       None, cooldown=3600,
                       condition=lambda e, h, d, idle, app: h >= 2 and h <= 5))

        # === Personality Moments ===
        pool.append(B("random_thought", "personality", "thought",
                       None, cooldown=600))
        pool.append(B("rate_app", "personality", "rate_app",
                       None, cooldown=1800,
                       condition=lambda e, h, d, idle, app: bool(app)))
        pool.append(B("screen_peek", "curiosity", "screen_peek",
                       None, cooldown=1200, priority=1,
                       condition=lambda e, h, d, idle, app: bool(app) and idle > 30))

        # === Opinion sharing (relationship-gated) ===
        pool.append(B("share_opinion", "personality", "opinion",
                       None, cooldown=1800,
                       condition=self._cond_can_share_opinion))

        # === Backstory fragments (relationship-gated) ===
        pool.append(B("backstory", "relationship", "backstory",
                       None, cooldown=7200, priority=2,
                       condition=self._cond_can_share_backstory))

        # === Milestone announcement ===
        pool.append(B("milestone", "relationship", "milestone",
                       None, cooldown=300, priority=5,
                       condition=self._cond_has_milestone))

        # === Separation greeting ===
        pool.append(B("separation_greeting", "relationship", "separation_greeting",
                       None, cooldown=600, priority=4,
                       condition=self._cond_separation_greeting_pending))

        # === Content behaviors ===
        pool.append(B("comfortable_silence", "personality", "comfortable_silence",
                       None, cooldown=1800,
                       condition=lambda e, h, d, idle, app: e == "content" and idle < 300))

        # === Animation Library Sequences ===
        # Daily life animations — triggered by time of day and emotion
        pool.append(B("anim_coffee", "animation", "play_anim",
                       "coffee_sip", cooldown=600,
                       condition=lambda e, h, d, idle, app: h >= 6 and h <= 11 and e in ("content", "happy", "sleepy")))
        pool.append(B("anim_yawn_stretch", "animation", "play_anim",
                       "yawn_stretch", cooldown=300,
                       condition=lambda e, h, d, idle, app: e in ("sleepy", "bored") or idle > 300))
        pool.append(B("anim_eat_snack", "animation", "play_anim",
                       "eat_snack", cooldown=900,
                       condition=lambda e, h, d, idle, app: h in (10, 11, 15, 16) and e in ("happy", "content", "bored")))
        pool.append(B("anim_read_book", "animation", "play_anim",
                       "read_book", cooldown=600,
                       condition=lambda e, h, d, idle, app: e in ("focused", "content", "bored") and idle > 120))
        pool.append(B("anim_nap", "animation", "play_anim",
                       "nap_blanket", cooldown=1200,
                       condition=lambda e, h, d, idle, app: e == "sleepy" and idle > 600))
        pool.append(B("anim_brush_teeth", "animation", "play_anim",
                       "brush_teeth", cooldown=3600,
                       condition=lambda e, h, d, idle, app: h >= 21 and h <= 23))
        pool.append(B("anim_morning_routine", "animation", "play_anim",
                       "morning_routine", cooldown=3600,
                       condition=lambda e, h, d, idle, app: h >= 6 and h <= 9))
        pool.append(B("anim_big_stretch", "animation", "play_anim",
                       "big_stretch", cooldown=600,
                       condition=lambda e, h, d, idle, app: idle > 300 and e in ("sleepy", "bored", "content")))
        pool.append(B("anim_monday_drama", "animation", "play_anim",
                       "monday_drama", cooldown=3600,
                       condition=lambda e, h, d, idle, app: d == 0 and h < 12))

        # Weather reaction animations
        pool.append(B("anim_rain_umbrella", "animation", "play_anim",
                       "rain_umbrella", cooldown=1800,
                       condition=self._cond_weather_rain))
        pool.append(B("anim_sunny_shades", "animation", "play_anim",
                       "sunny_shades", cooldown=1800,
                       condition=self._cond_weather_sunny))
        pool.append(B("anim_cold_shiver", "animation", "play_anim",
                       "cold_shiver", cooldown=1800,
                       condition=self._cond_weather_cold))
        pool.append(B("anim_heat_melt", "animation", "play_anim",
                       "heat_melt", cooldown=1800,
                       condition=self._cond_weather_hot))

        # Emotional animations — triggered by dominant emotion
        pool.append(B("anim_dramatic_tear", "animation", "play_anim",
                       "dramatic_tear", cooldown=600,
                       condition=lambda e, h, d, idle, app: e == "worried"))
        pool.append(B("anim_laugh_fall", "animation", "play_anim",
                       "laugh_fall", cooldown=600,
                       condition=lambda e, h, d, idle, app: e == "excited"))
        pool.append(B("anim_blush", "animation", "play_anim",
                       "blush", cooldown=300,
                       condition=lambda e, h, d, idle, app: e == "happy"))
        pool.append(B("anim_hide_face", "animation", "play_anim",
                       "hide_face", cooldown=600,
                       condition=lambda e, h, d, idle, app: e == "worried"))
        pool.append(B("anim_proud_puff", "animation", "play_anim",
                       "proud_puff", cooldown=300,
                       condition=lambda e, h, d, idle, app: e in ("happy", "excited")))
        pool.append(B("anim_existential_stare", "animation", "play_anim",
                       "existential_stare", cooldown=900,
                       condition=lambda e, h, d, idle, app: e == "bored" and idle > 300))
        pool.append(B("anim_sulk", "animation", "play_anim",
                       "sulk", cooldown=600,
                       condition=lambda e, h, d, idle, app: e == "frustrated"))
        pool.append(B("anim_excited_wiggle", "animation", "play_anim",
                       "excited_wiggle", cooldown=300,
                       condition=lambda e, h, d, idle, app: e == "excited"))
        pool.append(B("anim_victory", "animation", "play_anim",
                       "victory_pose", cooldown=300,
                       condition=lambda e, h, d, idle, app: e == "excited"))
        pool.append(B("anim_contemplate", "animation", "play_anim",
                       "contemplate", cooldown=600,
                       condition=lambda e, h, d, idle, app: e in ("curious", "content")))

        # Activity animations
        pool.append(B("anim_lift_weights", "animation", "play_anim",
                       "lift_weights", cooldown=900,
                       condition=lambda e, h, d, idle, app: e in ("happy", "excited", "focused")))
        pool.append(B("anim_type_frantic", "animation", "play_anim",
                       "type_frantic", cooldown=600,
                       condition=lambda e, h, d, idle, app: e == "focused" and any(
                           c in app for c in ("code", "vscode", "visual studio", "notepad"))))
        pool.append(B("anim_little_dance", "animation", "play_anim",
                       "little_dance", cooldown=600,
                       condition=lambda e, h, d, idle, app: e in ("happy", "excited") or "spotify" in app))
        pool.append(B("anim_stargaze", "animation", "play_anim",
                       "stargaze", cooldown=1800,
                       condition=lambda e, h, d, idle, app: h >= 21 or h <= 4))
        pool.append(B("anim_deep_focus", "animation", "play_anim",
                       "deep_focus", cooldown=600,
                       condition=lambda e, h, d, idle, app: e == "focused"))
        pool.append(B("anim_pushups", "animation", "play_anim",
                       "pushups", cooldown=900,
                       condition=lambda e, h, d, idle, app: e in ("bored", "focused") and idle > 180))
        pool.append(B("anim_head_bob", "animation", "play_anim",
                       "head_bob", cooldown=600,
                       condition=lambda e, h, d, idle, app: "spotify" in app or e == "happy"))

        # Silly animations — random chance when bored or happy
        pool.append(B("anim_chase_tail", "animation", "play_anim",
                       "chase_tail", cooldown=900,
                       condition=lambda e, h, d, idle, app: e in ("bored", "curious")))
        pool.append(B("anim_hiccup", "animation", "play_anim",
                       "hiccup", cooldown=600,
                       condition=lambda e, h, d, idle, app: True))
        pool.append(B("anim_sneeze_fly", "animation", "play_anim",
                       "sneeze_fly", cooldown=600,
                       condition=lambda e, h, d, idle, app: True))
        pool.append(B("anim_spooked", "animation", "play_anim",
                       "spooked_reflection", cooldown=1200,
                       condition=lambda e, h, d, idle, app: e in ("curious", "bored")))
        pool.append(B("anim_trip", "animation", "play_anim",
                       "trip", cooldown=900,
                       condition=lambda e, h, d, idle, app: e in ("bored", "sleepy", "happy")))
        pool.append(B("anim_statue", "animation", "play_anim",
                       "statue", cooldown=1200,
                       condition=lambda e, h, d, idle, app: e == "bored" and idle > 300))
        pool.append(B("anim_burp", "animation", "play_anim",
                       "burp", cooldown=900,
                       condition=lambda e, h, d, idle, app: e == "content"))
        pool.append(B("anim_jump_scare", "animation", "play_anim",
                       "jump_scare", cooldown=600,
                       condition=lambda e, h, d, idle, app: e in ("curious", "worried")))
        pool.append(B("anim_try_whistle", "animation", "play_anim",
                       "try_whistle", cooldown=900,
                       condition=lambda e, h, d, idle, app: e in ("bored", "happy", "content")))

        # Seasonal animations
        pool.append(B("anim_santa_gift", "animation", "play_anim",
                       "santa_gift", cooldown=3600, priority=3,
                       condition=self._cond_seasonal_christmas))
        pool.append(B("anim_new_year", "animation", "play_anim",
                       "new_year_fireworks", cooldown=3600, priority=3,
                       condition=self._cond_seasonal_new_year))
        pool.append(B("anim_valentine", "animation", "play_anim",
                       "valentine_hearts", cooldown=3600, priority=3,
                       condition=self._cond_seasonal_valentine))
        pool.append(B("anim_halloween", "animation", "play_anim",
                       "halloween_spook", cooldown=3600, priority=3,
                       condition=self._cond_seasonal_halloween))
        pool.append(B("anim_spring", "animation", "play_anim",
                       "spring_stretch", cooldown=3600,
                       condition=lambda e, h, d, idle, app: datetime.datetime.now().month in (3, 4, 5)))
        pool.append(B("anim_summer", "animation", "play_anim",
                       "summer_vibes", cooldown=3600,
                       condition=lambda e, h, d, idle, app: datetime.datetime.now().month in (6, 7, 8)))

        _thoughts = [
            "...hm.",
            "I was thinking about fish sticks. Nevermind.",
            "Do you think clouds have feelings?",
            "Interesting.",
            "I should organize my pixels.",
            "What if I'm the desktop and you're the pet?",
            "I wonder what wifi tastes like.",
            "Sometimes silence is the best conversation.",
            "I forget what I was going to say.",
            "The cursor moves but does it go anywhere?",
        ]

        _app_ratings = {
            "chrome": "Chrome. 6/10. Memory hog but we all use it.",
            "firefox": "Firefox. 7/10. Respectable choice.",
            "spotify": "Spotify. 8/10. Good taste required.",
            "discord": "Discord. 7/10. Say hi to the server for me.",
            "steam": "Steam. 9/10. The summer sale got me too.",
            "code": "VS Code. 8/10. You're productive today, I guess.",
            "notepad": "Notepad. 5/10. Minimalist, I respect it.",
        }

        _bored_escalation = {
            1: [
                "...",
                "Hm.",
                "It's quiet.",
            ],
            2: [
                "Hey.",
                "I'm bored.",
                "Do something interesting.",
            ],
            3: [
                "I'm going to start rearranging your desktop icons.",
                "This is the least fun I've ever had. And I've been a loading screen.",
                "I'm one minute away from learning to type and writing your emails.",
            ],
        }

        _break_messages = {
            "gentle": [
                "Maybe a quick stretch?",
                "You've been at it for a while.",
                "Water exists, you know.",
            ],
            "firm": [
                "Seriously. Take a break.",
                "Your eyes need rest. I can see them from here.",
                "I'm staging an intervention. Step away from the screen.",
            ],
        }

        # Store for runtime lookup
        self._thoughts = _thoughts
        self._app_ratings = _app_ratings
        self._bored_escalation = _bored_escalation
        self._break_messages = _break_messages
        self._separation_greeting_given = False

        return pool

    # ------------------------------------------------------------------
    # Dynamic message getters
    # ------------------------------------------------------------------

    def get_random_thought(self) -> str:
        return random.choice(self._thoughts)

    def get_app_rating(self) -> str:
        for app_key, rating in self._app_ratings.items():
            if app_key in self._active_app:
                return rating
        return f"Whatever this app is... 5/10."

    def get_opinion_message(self) -> str:
        """Get a relevant opinion based on current app or random."""
        from core.personality import get_opinion, get_random_opinion
        # Try to match current app to an opinion
        if self._active_app:
            for topic in ("discord", "spotify", "twitter", "reddit",
                          "zoom", "youtube", "steam", "vscode", "notepad", "chrome"):
                if topic in self._active_app:
                    op = get_opinion(topic)
                    if op:
                        return op["line"]
        # Random opinion
        _, op = get_random_opinion()
        return op["line"]

    def get_backstory_fragment(self) -> str:
        """Get a backstory fragment appropriate for relationship stage."""
        from core.personality import get_backstory_fragment
        stage = self._relationship.stage if self._relationship else "stranger"
        return get_backstory_fragment(stage) or ""

    def get_bored_escalation_message(self) -> str:
        level = max(1, min(3, self._boredom_level))
        return random.choice(self._bored_escalation.get(level, ["..."]))

    def get_break_message(self, intensity: str = "gentle") -> str:
        return random.choice(self._break_messages.get(intensity, ["Take a break."]))

    def get_morning_greeting(self) -> str:
        """Profile + relationship aware morning greeting."""
        rel_stage = self._relationship.stage if self._relationship else "stranger"
        greetings = {
            "stranger":     ["Morning.", "Hey.", "Good morning."],
            "acquaintance": ["Morning.", "Hey, good morning.", "Rise and shine. Or don't."],
            "friend":       ["Morning! How'd you sleep?", "Hey, good to see you.", "There you are."],
            "close_friend": ["Morning. Missed you.", "Hey. Ready for today?", "Good morning. I saved your seat."],
            "best_friend":  ["Morning, partner.", "Hey. Today's gonna be good, I can feel it.", "There's my favorite human."],
        }
        return random.choice(greetings.get(rel_stage, greetings["stranger"]))

    def get_late_night_message(self) -> str:
        """Profile-aware late night message."""
        if self._user_profile and self._user_profile.chronotype == "night_owl":
            return random.choice([
                "Late night session, huh? I'm here for it.",
                "The night shift. My favorite.",
                "Just us and the dark. I don't mind.",
            ])
        return random.choice([
            "It's late. Just saying.",
            "You should probably sleep.",
            "The bed is calling. I can hear it from here.",
        ])

    def get_milestone_data(self) -> tuple[str, str]:
        """Pop next milestone and return (id, message)."""
        if not self._relationship:
            return ("", "")
        mid = self._relationship.pop_pending_milestone()
        if mid:
            return (mid, self._relationship.get_milestone_message(mid))
        return ("", "")

    def get_separation_greeting(self) -> str:
        """Get absence-aware greeting."""
        if not self._relationship:
            return ""
        return self._relationship.get_separation_reaction() or ""

    # ------------------------------------------------------------------
    # Condition helpers
    # ------------------------------------------------------------------

    def _cond_morning_greet(self, e, h, d, idle, app) -> bool:
        greeting_hour = 9
        if self._user_profile:
            greeting_hour = self._user_profile.chronotype_curve.get("greeting_hour", 9)
        return h == greeting_hour

    def _cond_late_night(self, e, h, d, idle, app) -> bool:
        threshold = 23
        if self._user_profile:
            threshold = self._user_profile.chronotype_curve.get("late_night_threshold", 23)
        return h == threshold

    def _cond_fall_asleep(self, e, h, d, idle, app) -> bool:
        """Only fall asleep after 30 min idle AND if night_owl is off."""
        if idle < 1800:
            return False
        if self._emotion_engine and getattr(self._emotion_engine, '_night_owl', False):
            return False
        return True

    def _cond_midnight(self, e, h, d, idle, app) -> bool:
        """Only trigger midnight sleepy_lock if night_owl is off."""
        if h != 0:
            return False
        if self._emotion_engine and getattr(self._emotion_engine, '_night_owl', False):
            return False
        return True

    def _cond_bored_escalation_1(self, e, h, d, idle, app) -> bool:
        return e == "bored" and self._boredom_level >= 1

    def _cond_bored_escalation_2(self, e, h, d, idle, app) -> bool:
        return e == "bored" and self._boredom_level >= 2

    def _cond_bored_escalation_3(self, e, h, d, idle, app) -> bool:
        return e == "bored" and self._boredom_level >= 3

    def _cond_break_gentle(self, e, h, d, idle, app) -> bool:
        if self._user_profile and not self._user_profile.should_push_break():
            return False
        return idle < 60 and e == "focused" and self._break_reminders_given == 0

    def _cond_break_firm(self, e, h, d, idle, app) -> bool:
        if self._user_profile and not self._user_profile.should_push_break():
            return False
        push = 0.7
        if self._user_profile:
            from core.user_profile import AGE_MODIFIERS
            push = AGE_MODIFIERS.get(self._user_profile.age_group, {}).get("break_push_intensity", 0.7)
        return (idle < 60 and e == "focused" and
                self._break_reminders_given >= 1 and random.random() < push)

    def _cond_can_share_opinion(self, e, h, d, idle, app) -> bool:
        if not self._relationship:
            return False
        return self._relationship.traits.get("shares_opinions", False)

    def _cond_can_share_backstory(self, e, h, d, idle, app) -> bool:
        if not self._relationship:
            return False
        stage = self._relationship.stage
        return stage not in ("stranger",) and e in ("content", "happy", "bored")

    def _cond_has_milestone(self, e, h, d, idle, app) -> bool:
        if not self._relationship:
            return False
        return bool(self._relationship._pending_milestones)

    def _cond_separation_greeting_pending(self, e, h, d, idle, app) -> bool:
        if self._separation_greeting_given:
            return False
        if not self._relationship:
            return False
        return self._relationship.get_absence_duration() is not None

    # Weather condition helpers (for animation library)
    def _cond_weather_rain(self, e, h, d, idle, app) -> bool:
        if not self._emotion_engine:
            return False
        w = getattr(self._emotion_engine, 'weather', None) or ""
        wl = w.lower()
        return any(kw in wl for kw in ('rain', 'drizzle', 'shower'))

    def _cond_weather_sunny(self, e, h, d, idle, app) -> bool:
        if not self._emotion_engine:
            return False
        w = getattr(self._emotion_engine, 'weather', None) or ""
        wl = w.lower()
        return any(kw in wl for kw in ('sun', 'clear', 'fair'))

    def _cond_weather_cold(self, e, h, d, idle, app) -> bool:
        if not self._emotion_engine:
            return False
        w = getattr(self._emotion_engine, 'weather', None) or ""
        wl = w.lower()
        return any(kw in wl for kw in ('snow', 'cold', 'freeze', 'ice', 'blizzard'))

    def _cond_weather_hot(self, e, h, d, idle, app) -> bool:
        if not self._emotion_engine:
            return False
        w = getattr(self._emotion_engine, 'weather', None) or ""
        wl = w.lower()
        return any(kw in wl for kw in ('hot', 'heat', 'swelter'))

    # Seasonal condition helpers
    def _cond_seasonal_christmas(self, e, h, d, idle, app) -> bool:
        now = datetime.datetime.now()
        return now.month == 12 and now.day in (24, 25)

    def _cond_seasonal_new_year(self, e, h, d, idle, app) -> bool:
        now = datetime.datetime.now()
        return (now.month == 12 and now.day == 31) or (now.month == 1 and now.day == 1)

    def _cond_seasonal_valentine(self, e, h, d, idle, app) -> bool:
        now = datetime.datetime.now()
        return now.month == 2 and now.day == 14

    def _cond_seasonal_halloween(self, e, h, d, idle, app) -> bool:
        now = datetime.datetime.now()
        return now.month == 10 and now.day == 31
