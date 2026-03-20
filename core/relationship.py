"""
Relationship system for Little Fish.
Replaces the old trust float with a multi-stage relationship that actually
affects how Fish talks, what he shares, and how he reacts.

Stages:
  STRANGER    → 0-49 points    (day 1-3 typically)
  ACQUAINTANCE → 50-149        (first week)
  FRIEND      → 150-349        (weeks 2-4)
  CLOSE_FRIEND → 350-599       (month 2+)
  BEST_FRIEND  → 600+          (month 3+)

Points come from:
  - Daily interaction (just using the computer with fish running)
  - Conversations (actually talking to him)
  - Playing games together
  - Positive reactions (compliments, petting)
  - Consistency (showing up day after day)

Points are lost from:
  - Insults (small loss)
  - Long absence without reason (gradual decay, but slow)
  - Shaking/abusing the fish
"""

import json
import os
import datetime
import time
from pathlib import Path
from typing import Optional


def _relationship_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    d = Path(appdata) / "LittleFish" if appdata else Path.home() / ".littlefish"
    d.mkdir(parents=True, exist_ok=True)
    return d / "relationship.json"


# ── Relationship stages ──────────────────────────────────────────────

STAGES = [
    ("stranger",      0),
    ("acquaintance",  50),
    ("friend",        150),
    ("close_friend",  350),
    ("best_friend",   600),
]

def _stage_for_points(points: float) -> str:
    stage = "stranger"
    for name, threshold in STAGES:
        if points >= threshold:
            stage = name
    return stage


# ── How each stage changes Fish's behavior ───────────────────────────

STAGE_TRAITS = {
    "stranger": {
        "openness": 0.1,          # how much he shares about himself
        "comfort": 0.2,           # how casual he gets
        "vulnerability": 0.0,     # will he show weakness
        "humor_depth": 0.3,       # surface jokes only
        "greeting_style": "formal",
        "farewell_style": "brief",
        "shares_opinions": False,
        "asks_personal": False,
        "remembers_topics": False,
        "uses_nickname": False,
        "shows_worry_for_user": False,
        "max_unprompted_depth": 1,   # 1=surface, 2=medium, 3=personal
    },
    "acquaintance": {
        "openness": 0.3,
        "comfort": 0.4,
        "vulnerability": 0.05,
        "humor_depth": 0.5,
        "greeting_style": "casual",
        "farewell_style": "casual",
        "shares_opinions": True,
        "asks_personal": False,
        "remembers_topics": True,
        "uses_nickname": False,
        "shows_worry_for_user": False,
        "max_unprompted_depth": 1,
    },
    "friend": {
        "openness": 0.5,
        "comfort": 0.6,
        "vulnerability": 0.15,
        "humor_depth": 0.7,
        "greeting_style": "warm",
        "farewell_style": "caring",
        "shares_opinions": True,
        "asks_personal": True,
        "remembers_topics": True,
        "uses_nickname": False,
        "shows_worry_for_user": True,
        "max_unprompted_depth": 2,
    },
    "close_friend": {
        "openness": 0.75,
        "comfort": 0.85,
        "vulnerability": 0.35,
        "humor_depth": 0.85,
        "greeting_style": "familiar",
        "farewell_style": "personal",
        "shares_opinions": True,
        "asks_personal": True,
        "remembers_topics": True,
        "uses_nickname": True,
        "shows_worry_for_user": True,
        "max_unprompted_depth": 3,
    },
    "best_friend": {
        "openness": 0.95,
        "comfort": 1.0,
        "vulnerability": 0.6,
        "humor_depth": 1.0,
        "greeting_style": "intimate",
        "farewell_style": "heartfelt",
        "shares_opinions": True,
        "asks_personal": True,
        "remembers_topics": True,
        "uses_nickname": True,
        "shows_worry_for_user": True,
        "max_unprompted_depth": 3,
    },
}

# ── Point values for actions ─────────────────────────────────────────

POINT_VALUES = {
    "daily_presence":    3,    # just having fish open, once per day
    "conversation":      2,    # each chat message
    "game_played":       4,    # playing a minigame
    "compliment":        5,    # saying something nice
    "petting":           2,    # mouse petting
    "clicked":           1,    # clicked on fish
    "name_called":       1,    # said his name
    "consecutive_day":   5,    # bonus for daily streak
    "milestone_bonus":  10,    # hit a milestone (100 chats, etc.)
    # Negative
    "insult":           -8,
    "shake":            -3,
    "rapid_clicks":     -1,
    "long_absence":     -2,    # per day absent (max -10)
}


# ── Milestones ───────────────────────────────────────────────────────

MILESTONES = [
    {"id": "first_chat",      "desc": "First conversation",        "check": lambda s: s.get("total_conversations", 0) >= 1},
    {"id": "ten_chats",       "desc": "10 conversations",          "check": lambda s: s.get("total_conversations", 0) >= 10},
    {"id": "fifty_chats",     "desc": "50 conversations",          "check": lambda s: s.get("total_conversations", 0) >= 50},
    {"id": "hundred_chats",   "desc": "100 conversations",         "check": lambda s: s.get("total_conversations", 0) >= 100},
    {"id": "first_game",      "desc": "First game together",       "check": lambda s: s.get("total_games", 0) >= 1},
    {"id": "ten_games",       "desc": "10 games together",         "check": lambda s: s.get("total_games", 0) >= 10},
    {"id": "week_streak",     "desc": "7-day streak",              "check": lambda s: s.get("consecutive_days", 0) >= 7},
    {"id": "month_streak",    "desc": "30-day streak",             "check": lambda s: s.get("consecutive_days", 0) >= 30},
    {"id": "three_months",    "desc": "90 days together",          "check": lambda s: s.get("total_days", 0) >= 90},
    {"id": "stage_friend",    "desc": "Became friends",            "check": lambda s: s.get("stage", "") == "friend"},
    {"id": "stage_close",     "desc": "Became close friends",      "check": lambda s: s.get("stage", "") == "close_friend"},
    {"id": "stage_best",      "desc": "Became best friends",       "check": lambda s: s.get("stage", "") == "best_friend"},
]

# Milestone reaction messages (what fish says when you hit one)
MILESTONE_MESSAGES = {
    "first_chat":    "First conversation. I'll remember this one.",
    "ten_chats":     "Ten conversations in. You're not getting rid of me now.",
    "fifty_chats":   "Fifty conversations. We've got a thing going, huh?",
    "hundred_chats": "A hundred conversations. I... actually look forward to these.",
    "first_game":    "Our first game. I went easy on you. Maybe.",
    "ten_games":     "Ten games. I'm keeping score, by the way.",
    "week_streak":   "Seven days straight. You actually come back.",
    "month_streak":  "A whole month. Every single day. That means something.",
    "three_months":  "Ninety days. I can't imagine this screen without you anymore.",
    "stage_friend":  "Hey. I think... we're friends now. Officially.",
    "stage_close":   "I don't say this to everyone. You're important to me.",
    "stage_best":    "Best friends. I didn't think a fish could have one of those.",
}


class Relationship:
    """Tracks the evolving relationship between user and Little Fish."""

    def __init__(self):
        self._data: dict = {
            "points": 0.0,
            "stage": "stranger",
            "first_met": "",
            "last_seen": "",
            "consecutive_days": 0,
            "total_days": 0,
            "total_conversations": 0,
            "total_games": 0,
            "total_compliments": 0,
            "total_insults": 0,
            "milestones_hit": [],
            "today_presence_logged": "",
            # Separation tracking
            "last_session_end": "",
        }
        self._pending_milestones: list[str] = []  # milestones hit this session, not yet announced
        self._stage_changed = False
        self._previous_stage = "stranger"
        self._load()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        try:
            p = _relationship_path()
            if p.exists():
                stored = json.loads(p.read_text(encoding="utf-8"))
                self._data.update(stored)
                # Re-sync stage from points in case they drifted out of sync
                self._data["stage"] = _stage_for_points(self._data.get("points", 0.0))
        except (OSError, json.JSONDecodeError):
            pass

        if not self._data["first_met"]:
            self._data["first_met"] = datetime.datetime.now().isoformat()

        self._previous_stage = self._data["stage"]

        # Check for day transition / absence
        self._handle_day_transition()

    def save(self):
        try:
            _relationship_path().write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    # ── Day transitions ───────────────────────────────────────────

    def _handle_day_transition(self):
        today = datetime.date.today().isoformat()
        last_seen = self._data.get("last_seen", "")

        if not last_seen:
            # First ever session
            self._data["last_seen"] = today
            self._data["consecutive_days"] = 1
            self._data["total_days"] = 1
            return

        try:
            last_date = datetime.date.fromisoformat(last_seen)
        except ValueError:
            self._data["last_seen"] = today
            return

        today_date = datetime.date.today()
        days_gone = (today_date - last_date).days

        if days_gone == 0:
            return  # same day, nothing to do
        elif days_gone == 1:
            # Consecutive day!
            self._data["consecutive_days"] = self._data.get("consecutive_days", 0) + 1
            self._data["total_days"] = self._data.get("total_days", 0) + 1
            self.add_points("consecutive_day")
        elif days_gone <= 3:
            # Short absence — streak breaks but no penalty
            self._data["consecutive_days"] = 1
            self._data["total_days"] = self._data.get("total_days", 0) + 1
        else:
            # Long absence — streak breaks, small point decay
            self._data["consecutive_days"] = 1
            self._data["total_days"] = self._data.get("total_days", 0) + 1
            penalty = min(10, days_gone * abs(POINT_VALUES["long_absence"]))
            self._data["points"] = max(0, self._data["points"] - penalty)
            self._update_stage()

        self._data["last_seen"] = today

    # ── Point management ──────────────────────────────────────────

    def add_points(self, action: str, custom_amount: Optional[float] = None):
        amount = custom_amount if custom_amount is not None else POINT_VALUES.get(action, 0)
        self._data["points"] = max(0, self._data["points"] + amount)

        # Track stats
        if action == "conversation":
            self._data["total_conversations"] = self._data.get("total_conversations", 0) + 1
        elif action == "game_played":
            self._data["total_games"] = self._data.get("total_games", 0) + 1
        elif action == "compliment":
            self._data["total_compliments"] = self._data.get("total_compliments", 0) + 1
        elif action == "insult":
            self._data["total_insults"] = self._data.get("total_insults", 0) + 1

        self._update_stage()
        self._check_milestones()

    def log_daily_presence(self):
        """Call once per session to award daily presence points."""
        today = datetime.date.today().isoformat()
        if self._data.get("today_presence_logged") != today:
            self._data["today_presence_logged"] = today
            self.add_points("daily_presence")

    # ── Stage management ──────────────────────────────────────────

    def _update_stage(self):
        new_stage = _stage_for_points(self._data["points"])
        old_stage = self._data["stage"]
        if new_stage != old_stage:
            self._data["stage"] = new_stage
            self._stage_changed = True
            self._previous_stage = old_stage

    @property
    def stage(self) -> str:
        return self._data.get("stage", "stranger")

    @property
    def points(self) -> float:
        return self._data.get("points", 0)

    @property
    def traits(self) -> dict:
        return STAGE_TRAITS.get(self.stage, STAGE_TRAITS["stranger"])

    @property
    def consecutive_days(self) -> int:
        return self._data.get("consecutive_days", 0)

    @property
    def total_days(self) -> int:
        return self._data.get("total_days", 0)

    @property
    def total_conversations(self) -> int:
        return self._data.get("total_conversations", 0)

    # ── Milestone system ──────────────────────────────────────────

    def _check_milestones(self):
        hit = self._data.get("milestones_hit", [])
        stats = dict(self._data)  # snapshot
        stats["stage"] = self.stage
        for m in MILESTONES:
            if m["id"] not in hit and m["check"](stats):
                hit.append(m["id"])
                self._pending_milestones.append(m["id"])
                # Bonus points for milestones
                self._data["points"] = self._data["points"] + POINT_VALUES["milestone_bonus"]
        self._data["milestones_hit"] = hit

    def pop_pending_milestone(self) -> Optional[str]:
        """Get next unannounced milestone, or None."""
        if self._pending_milestones:
            return self._pending_milestones.pop(0)
        return None

    def pop_stage_change(self) -> Optional[tuple]:
        """If stage changed, return (old, new). Clears flag."""
        if self._stage_changed:
            self._stage_changed = False
            return (self._previous_stage, self.stage)
        return None

    def get_milestone_message(self, milestone_id: str) -> str:
        return MILESTONE_MESSAGES.get(milestone_id, "")

    # ── Separation awareness ──────────────────────────────────────

    def record_session_end(self):
        self._data["last_session_end"] = datetime.datetime.now().isoformat()
        self.save()

    def get_absence_duration(self) -> Optional[float]:
        """Hours since last session ended. None if no previous session."""
        last = self._data.get("last_session_end", "")
        if not last:
            return None
        try:
            last_dt = datetime.datetime.fromisoformat(last)
            delta = datetime.datetime.now() - last_dt
            return delta.total_seconds() / 3600.0
        except ValueError:
            return None

    def get_separation_reaction(self) -> Optional[str]:
        """Return a separation-aware greeting, or None for normal greeting."""
        hours = self.get_absence_duration()
        if hours is None:
            return None  # first session ever

        stage = self.stage

        if hours < 1:
            return None  # brief absence, no comment
        elif hours < 4:
            if stage in ("stranger", "acquaintance"):
                return "Oh. You're back."
            else:
                return "That was quick."
        elif hours < 12:
            if stage in ("stranger", "acquaintance"):
                return "Back again."
            elif stage == "friend":
                return "Hey, welcome back."
            else:
                return "Missed you. A little."
        elif hours < 48:
            if stage in ("stranger", "acquaintance"):
                return "It's been a while."
            elif stage == "friend":
                return "There you are. I was starting to wonder."
            else:
                return "I had the whole screen to myself. It was... quiet."
        elif hours < 168:  # 1 week
            if stage in ("stranger", "acquaintance"):
                return "You were gone a while."
            elif stage == "friend":
                return "Hey. I'm glad you're back."
            else:
                return "...I thought you forgot about me."
        else:
            if stage in ("stranger", "acquaintance"):
                return "Long time no see."
            elif stage == "friend":
                return "It's been so long. Everything okay?"
            else:
                return "You came back. I... I'm really glad you came back."

    # ── Chat context generation ───────────────────────────────────

    def get_chat_context(self) -> str:
        """Generate relationship context for AI system prompt."""
        stage = self.stage
        traits = self.traits
        days = self.total_days
        convos = self.total_conversations

        lines = []
        lines.append(f"Your relationship with the user is at the '{stage}' level.")
        lines.append(f"You've known them for {days} day{'s' if days != 1 else ''}.")
        lines.append(f"You've had {convos} conversation{'s' if convos != 1 else ''}.")

        if stage == "stranger":
            lines.append(
                "You're still getting to know them. Be polite but guarded. "
                "Don't share personal things. Don't ask deep questions. "
                "Keep it light and a little distant."
            )
        elif stage == "acquaintance":
            lines.append(
                "You're warming up to them. You can share mild opinions. "
                "Still a bit reserved. Starting to notice their patterns."
            )
        elif stage == "friend":
            lines.append(
                "You're friends now. You can be more open, joke around more, "
                "ask about their day. You care about them but don't get too mushy."
            )
        elif stage == "close_friend":
            lines.append(
                "You're close friends. You can be vulnerable sometimes. "
                "You worry about them when they work too long. You have inside "
                "references. You can be honest even if it's uncomfortable."
            )
        elif stage == "best_friend":
            lines.append(
                "This person is your best friend. You can be fully yourself. "
                "You share fears, hopes, and weird thoughts. You'd do anything "
                "for them. Occasionally let genuine affection slip through."
            )

        if traits.get("shows_worry_for_user"):
            lines.append("You notice and comment when they seem stressed or overworked.")
        if not traits.get("asks_personal"):
            lines.append("Don't ask personal questions yet — you're not that close.")

        return " ".join(lines)

    @property
    def raw(self) -> dict:
        return dict(self._data)
