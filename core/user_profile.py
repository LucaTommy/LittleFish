"""
User profile for Little Fish.
Created during onboarding, persists across sessions.
Everything in the personality/emotion/behavior stack reads from this.

Profile data:
  - age_group: "teen" | "young_adult" | "adult" | "mature"
  - usage: "work" | "gaming" | "creative" | "browsing" | "mixed"
  - chronotype: "early_bird" | "normal" | "night_owl"
  - talkativeness: "quiet" | "normal" | "chatty"
  - fish_name: str (default "Little Fish")
  - onboarded: bool
  - onboarded_at: ISO datetime string
"""

import json
import os
from pathlib import Path
from typing import Optional


def _profile_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    d = Path(appdata) / "LittleFish" if appdata else Path.home() / ".littlefish"
    d.mkdir(parents=True, exist_ok=True)
    return d / "user_profile.json"


# ── Age group mapping ────────────────────────────────────────────────

AGE_GROUPS = {
    "teen":        {"min": 10, "max": 17},
    "young_adult": {"min": 18, "max": 25},
    "adult":       {"min": 26, "max": 40},
    "mature":      {"min": 41, "max": 999},
}

def age_to_group(age: int) -> str:
    for group, rng in AGE_GROUPS.items():
        if rng["min"] <= age <= rng["max"]:
            return group
    return "adult"


# ── Default profile ──────────────────────────────────────────────────

DEFAULT_PROFILE = {
    "onboarded": False,
    "onboarded_at": "",
    "age": 0,
    "age_group": "adult",
    "usage": "mixed",
    "chronotype": "normal",
    "talkativeness": "normal",
    "fish_name": "Little Fish",
}


# ── Profile parameters that affect downstream systems ────────────────

# How age_group modulates behavior
AGE_MODIFIERS = {
    "teen": {
        "humor_style": "memes_and_slang",
        "energy_multiplier": 1.3,
        "break_push_intensity": 0.5,      # less nagging
        "vocabulary_level": "casual",
        "reference_pool": "gaming_internet_school",
        "game_suggestions": ["reaction_test", "snake", "flappy", "whack_a_mole"],
        "chattiness_bonus": 0.15,
    },
    "young_adult": {
        "humor_style": "dry_and_ironic",
        "energy_multiplier": 1.1,
        "break_push_intensity": 0.7,
        "vocabulary_level": "normal",
        "reference_pool": "tech_culture_work",
        "game_suggestions": ["trivia", "typing_test", "minesweeper", "breakout"],
        "chattiness_bonus": 0.05,
    },
    "adult": {
        "humor_style": "deadpan_observational",
        "energy_multiplier": 1.0,
        "break_push_intensity": 0.9,       # pushes breaks harder
        "vocabulary_level": "normal",
        "reference_pool": "work_life_balance",
        "game_suggestions": ["minesweeper", "trivia", "typing_test", "memory"],
        "chattiness_bonus": 0.0,
    },
    "mature": {
        "humor_style": "warm_dry_wit",
        "energy_multiplier": 0.9,
        "break_push_intensity": 1.0,       # full nagging rights
        "vocabulary_level": "articulate",
        "reference_pool": "classic_thoughtful",
        "game_suggestions": ["trivia", "memory", "minesweeper", "typing_test"],
        "chattiness_bonus": -0.05,
    },
}

# How chronotype shifts energy across the day (hour -> energy multiplier)
CHRONOTYPE_CURVES = {
    "early_bird": {
        # High energy 6am-2pm, drops after
        "peak_start": 6, "peak_end": 14,
        "energy_peak": 1.3,
        "energy_off_peak": 0.7,
        "late_night_threshold": 22,     # starts nagging here
        "greeting_hour": 7,
    },
    "normal": {
        "peak_start": 9, "peak_end": 18,
        "energy_peak": 1.1,
        "energy_off_peak": 0.85,
        "late_night_threshold": 23,
        "greeting_hour": 9,
    },
    "night_owl": {
        # High energy 2pm-3am
        "peak_start": 14, "peak_end": 3,
        "energy_peak": 1.2,
        "energy_off_peak": 0.75,
        "late_night_threshold": 4,      # only nags at 4am
        "greeting_hour": 11,
    },
}

# How talkativeness maps to behavior
TALKATIVENESS_MAP = {
    "quiet":  {"initiation_multiplier": 0.3, "unprompted_interval_min": 900, "max_unprompted_per_hour": 2},
    "normal": {"initiation_multiplier": 1.0, "unprompted_interval_min": 300, "max_unprompted_per_hour": 5},
    "chatty": {"initiation_multiplier": 1.8, "unprompted_interval_min": 120, "max_unprompted_per_hour": 10},
}

# How usage type affects app relevance
USAGE_APP_RELEVANCE = {
    "work": {
        "relevant_apps": ["code", "vscode", "excel", "word", "outlook", "slack", "teams", "notion", "figma", "jira"],
        "reaction_style": "productivity_focused",
        "break_awareness": True,
    },
    "gaming": {
        "relevant_apps": ["steam", "epic", "discord", "obs", "twitch", "minecraft", "roblox", "valorant"],
        "reaction_style": "hype_and_chill",
        "break_awareness": False,
    },
    "creative": {
        "relevant_apps": ["photoshop", "illustrator", "blender", "premiere", "davinci", "obs", "audacity", "figma"],
        "reaction_style": "appreciative_curious",
        "break_awareness": True,
    },
    "browsing": {
        "relevant_apps": ["chrome", "firefox", "edge", "youtube", "reddit", "twitter"],
        "reaction_style": "commentary",
        "break_awareness": False,
    },
    "mixed": {
        "relevant_apps": [],
        "reaction_style": "general",
        "break_awareness": True,
    },
}


class UserProfile:
    """Persistent user profile created during onboarding."""

    def __init__(self):
        self._data: dict = dict(DEFAULT_PROFILE)
        self._load()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        try:
            p = _profile_path()
            if p.exists():
                stored = json.loads(p.read_text(encoding="utf-8"))
                self._data.update(stored)
        except (OSError, json.JSONDecodeError):
            pass

    def save(self):
        try:
            _profile_path().write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    # ── Onboarding ────────────────────────────────────────────────

    @property
    def is_onboarded(self) -> bool:
        return self._data.get("onboarded", False)

    def complete_onboarding(self, age: int, usage: str, chronotype: str,
                            talkativeness: str, fish_name: str):
        import datetime
        self._data["onboarded"] = True
        self._data["onboarded_at"] = datetime.datetime.now().isoformat()
        self._data["age"] = age
        self._data["age_group"] = age_to_group(age)
        self._data["usage"] = usage
        self._data["chronotype"] = chronotype
        self._data["talkativeness"] = talkativeness
        self._data["fish_name"] = fish_name.strip() or "Little Fish"
        self.save()

    def update_field(self, key: str, value):
        if key in DEFAULT_PROFILE:
            self._data[key] = value
            if key == "age":
                self._data["age_group"] = age_to_group(value)
            self.save()

    # ── Accessors ─────────────────────────────────────────────────

    @property
    def age(self) -> int:
        return self._data.get("age", 0)

    @property
    def age_group(self) -> str:
        return self._data.get("age_group", "adult")

    @property
    def usage(self) -> str:
        return self._data.get("usage", "mixed")

    @property
    def chronotype(self) -> str:
        return self._data.get("chronotype", "normal")

    @property
    def talkativeness(self) -> str:
        return self._data.get("talkativeness", "normal")

    @property
    def fish_name(self) -> str:
        return self._data.get("fish_name", "Little Fish")

    @property
    def raw(self) -> dict:
        return dict(self._data)

    # ── Derived helpers (used by emotion/behavior/chat systems) ───

    @property
    def age_mods(self) -> dict:
        return AGE_MODIFIERS.get(self.age_group, AGE_MODIFIERS["adult"])

    @property
    def chronotype_curve(self) -> dict:
        return CHRONOTYPE_CURVES.get(self.chronotype, CHRONOTYPE_CURVES["normal"])

    @property
    def talk_settings(self) -> dict:
        return TALKATIVENESS_MAP.get(self.talkativeness, TALKATIVENESS_MAP["normal"])

    @property
    def usage_config(self) -> dict:
        return USAGE_APP_RELEVANCE.get(self.usage, USAGE_APP_RELEVANCE["mixed"])

    def is_peak_hour(self, hour: Optional[int] = None) -> bool:
        """Is the given hour within user's peak energy window?"""
        import datetime
        if hour is None:
            hour = datetime.datetime.now().hour
        curve = self.chronotype_curve
        start, end = curve["peak_start"], curve["peak_end"]
        if start <= end:
            return start <= hour <= end
        # Wraps midnight (e.g. night_owl: 14-3)
        return hour >= start or hour <= end

    def energy_multiplier_now(self, hour: Optional[int] = None) -> float:
        """Current energy multiplier based on chronotype + age."""
        curve = self.chronotype_curve
        age_mult = self.age_mods["energy_multiplier"]
        if self.is_peak_hour(hour):
            return curve["energy_peak"] * age_mult
        return curve["energy_off_peak"] * age_mult

    def is_app_relevant(self, app_name: str) -> bool:
        """Check if an app is relevant to the user's stated usage."""
        if not app_name:
            return False
        relevant = self.usage_config.get("relevant_apps", [])
        if not relevant:
            return True  # 'mixed' mode — everything mildly relevant
        app_lower = app_name.lower()
        return any(r in app_lower for r in relevant)

    def should_push_break(self) -> bool:
        return self.usage_config.get("break_awareness", True)

    def effective_chattiness(self) -> float:
        """Combined chattiness from talkativeness + age bonus. 0-1 scale."""
        base = self.talk_settings["initiation_multiplier"]
        bonus = self.age_mods.get("chattiness_bonus", 0.0)
        return max(0.1, min(2.0, base + bonus))

    def get_chat_personality_context(self) -> str:
        """Generate a context string for the AI chat system prompt."""
        age = self.age
        group = self.age_group
        mods = self.age_mods
        name = self.fish_name

        lines = [f"Your name is {name}."]

        if group == "teen":
            lines.append(
                "The user is a teenager. Use casual language, light internet humor, "
                "and references to gaming, school, and internet culture. Keep it fun "
                "and relatable. Don't lecture. Be like a cool older sibling."
            )
        elif group == "young_adult":
            lines.append(
                "The user is a young adult. Dry, ironic humor works well. "
                "Reference tech culture, work life, and contemporary things. "
                "Be witty but not try-hard."
            )
        elif group == "adult":
            lines.append(
                "The user is an adult. Deadpan observational humor. "
                "Acknowledge the grind. Be relatable about work-life balance. "
                "Don't over-explain or be condescending."
            )
        elif group == "mature":
            lines.append(
                "The user is experienced. Warm but dry wit. Thoughtful observations. "
                "Don't try to be 'hip.' Be genuine, measured, and occasionally wise."
            )

        if mods["vocabulary_level"] == "casual":
            lines.append("Use casual, short sentences. Slang is fine sparingly.")
        elif mods["vocabulary_level"] == "articulate":
            lines.append("You can be slightly more articulate than usual.")

        return " ".join(lines)
