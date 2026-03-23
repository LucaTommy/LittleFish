"""
Intelligence module for Little Fish.
Handles: persistent chat memory, schedule learning, todo list,
morning briefing, jokes/facts, clipboard analysis, app awareness.
"""

import json
import random
import datetime
import time
import re
from pathlib import Path
from typing import Optional

# Persistent storage directory
STATE_DIR = Path.home() / "AppData" / "Roaming" / "LittleFish"
STATE_DIR.mkdir(parents=True, exist_ok=True)

CHAT_HISTORY_PATH = STATE_DIR / "chat_history.json"
SCHEDULE_PATH = STATE_DIR / "schedule.json"
TODO_PATH = STATE_DIR / "todo.json"


# ---------------------------------------------------------------------------
# Persistent Chat Memory
# ---------------------------------------------------------------------------

MAX_PERSISTENT_HISTORY = 50


def load_chat_history() -> list[dict]:
    """Load persistent chat history from disk."""
    try:
        if CHAT_HISTORY_PATH.exists():
            data = json.loads(CHAT_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-MAX_PERSISTENT_HISTORY:]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_chat_history(history: list[dict]):
    """Save chat history to disk."""
    try:
        trimmed = history[-MAX_PERSISTENT_HISTORY:]
        CHAT_HISTORY_PATH.write_text(
            json.dumps(trimmed, indent=1, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Schedule Learner
# ---------------------------------------------------------------------------

class ScheduleTracker:
    """Track user activity patterns by hour/day to learn routines."""

    def __init__(self):
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            if SCHEDULE_PATH.exists():
                return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        return {"hourly_activity": {}, "last_update": ""}

    def _save(self):
        try:
            SCHEDULE_PATH.write_text(
                json.dumps(self._data, indent=1), encoding="utf-8"
            )
        except OSError:
            pass

    def record_activity(self):
        """Record that user is active right now."""
        now = datetime.datetime.now()
        key = f"{now.strftime('%A')}_{now.hour}"  # e.g. "Monday_9"
        counts = self._data.setdefault("hourly_activity", {})
        counts[key] = counts.get(key, 0) + 1
        self._data["last_update"] = now.isoformat()
        self._save()

    def is_usual_active_time(self) -> bool:
        """Check if the current time is when the user is usually active."""
        now = datetime.datetime.now()
        key = f"{now.strftime('%A')}_{now.hour}"
        counts = self._data.get("hourly_activity", {})
        return counts.get(key, 0) > 5

    def get_peak_hours(self) -> list[int]:
        """Return the top 5 most active hours across all days."""
        counts = self._data.get("hourly_activity", {})
        hour_totals: dict[int, int] = {}
        for key, count in counts.items():
            parts = key.rsplit("_", 1)
            if len(parts) == 2:
                try:
                    hour = int(parts[1])
                    hour_totals[hour] = hour_totals.get(hour, 0) + count
                except ValueError:
                    pass
        sorted_hours = sorted(hour_totals.items(), key=lambda x: x[1], reverse=True)
        return [h for h, _ in sorted_hours[:5]]


# ---------------------------------------------------------------------------
# Todo List
# ---------------------------------------------------------------------------

class TodoList:
    """Persistent todo list manageable via voice commands."""

    def __init__(self):
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            if TODO_PATH.exists():
                data = json.loads(TODO_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _save(self):
        try:
            TODO_PATH.write_text(
                json.dumps(self._items, indent=1, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def add(self, text: str) -> str:
        """Add a todo item. Returns confirmation message."""
        self._items.append({
            "text": text,
            "done": False,
            "added": datetime.datetime.now().isoformat(),
        })
        self._save()
        return f"Added: {text}"

    def complete(self, query: str) -> str:
        """Mark a todo as done by fuzzy matching. Returns status."""
        query_lower = query.lower()
        for item in self._items:
            if not item["done"] and query_lower in item["text"].lower():
                item["done"] = True
                self._save()
                return f"Done: {item['text']}"
        return f"Couldn't find a todo matching '{query}'"

    def remove(self, query: str) -> str:
        """Remove a todo by fuzzy matching."""
        query_lower = query.lower()
        for i, item in enumerate(self._items):
            if query_lower in item["text"].lower():
                removed = self._items.pop(i)
                self._save()
                return f"Removed: {removed['text']}"
        return f"Couldn't find a todo matching '{query}'"

    def list_pending(self) -> str:
        """Return formatted list of pending todos."""
        pending = [item for item in self._items if not item["done"]]
        if not pending:
            return "No todos! You're all caught up."
        lines = [f"{i+1}. {item['text']}" for i, item in enumerate(pending)]
        return "Your todos:\n" + "\n".join(lines)

    def count_pending(self) -> int:
        return sum(1 for item in self._items if not item["done"])


# ---------------------------------------------------------------------------
# Clipboard Analyzer
# ---------------------------------------------------------------------------

def analyze_clipboard(text: str) -> Optional[str]:
    """Analyze clipboard content and return a reaction type.
    Returns: 'code', 'url', 'long_text', or None.
    """
    if not text or len(text) < 3:
        return None
    text = text.strip()

    # URL detection
    if re.match(r'https?://\S+', text):
        return "url"

    # Code detection (common programming patterns)
    code_patterns = [
        r'(def |class |function |import |const |let |var |=>|{|}|\(\)|;$)',
        r'(public |private |static |return |if\s*\(|for\s*\(|while\s*\()',
        r'(<[a-z]+>|</[a-z]+>|<[A-Z]\w+)',
    ]
    for pattern in code_patterns:
        if re.search(pattern, text, re.MULTILINE):
            return "code"

    # Long text (paragraph-like)
    if len(text) > 200:
        return "long_text"

    return None


# ---------------------------------------------------------------------------
# App Awareness
# ---------------------------------------------------------------------------

APP_REACTIONS = {
    "discord": ("curious", "Oh, chatting with friends?"),
    "spotify": ("happy", None),  # None = no bubble, just emotion
    "steam": ("excited", "Game time!"),
    "chrome": (None, None),
    "firefox": (None, None),
    "code": ("focused", None),
    "slack": ("curious", "Work chat?"),
    "teams": ("curious", "Meeting time?"),
    "zoom": ("worried", "Oh, a call!"),
    "obs": ("excited", "Going live?"),
}


def get_app_reaction(process_name: str) -> tuple[Optional[str], Optional[str]]:
    """Return (emotion, bubble_text) for a detected app. Both can be None."""
    pname = process_name.lower().replace(".exe", "")
    for app_key, (emotion, text) in APP_REACTIONS.items():
        if app_key in pname:
            return emotion, text
    return None, None


# ---------------------------------------------------------------------------
# Morning Briefing
# ---------------------------------------------------------------------------

def generate_morning_briefing(weather: str, mood: str, todo_count: int) -> str:
    """Generate a morning briefing message."""
    parts = ["Good morning!"]

    if weather:
        parts.append(f"Weather: {weather}.")
    
    mood_comments = {
        "happy": "I'm feeling great today!",
        "sleepy": "Still waking up...",
        "excited": "I'm pumped for today!",
        "worried": "Hope today goes smoothly.",
        "bored": "Let's find something fun to do!",
        "curious": "I wonder what today brings!",
        "focused": "Ready to get things done.",
    }
    parts.append(mood_comments.get(mood, "Let's have a good day!"))

    if todo_count > 0:
        parts.append(f"You have {todo_count} todo{'s' if todo_count > 1 else ''} pending.")
    else:
        parts.append("No pending todos!")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Jokes & Facts
# ---------------------------------------------------------------------------

JOKES_AND_FACTS = [
    "Did you know octopuses have three hearts?",
    "A group of flamingos is called a 'flamboyance'!",
    "Honey never spoils — they found 3000-year-old honey in Egyptian tombs!",
    "Why don't fish play piano? Because you can't tuna fish!",
    "The shortest war in history lasted 38 minutes.",
    "Sea otters hold hands while sleeping so they don't drift apart.",
    "A day on Venus is longer than a year on Venus!",
    "Cows have best friends and get stressed when separated.",
    "Why do fish live in salt water? Because pepper makes them sneeze!",
    "Bananas are technically berries, but strawberries aren't!",
    "The average person walks about 100,000 miles in a lifetime.",
    "What do you call a fish without eyes? A fsh!",
    "Dolphins have names for each other!",
    "The moon has moonquakes!",
    "A jiffy is an actual unit of time: 1/100th of a second.",
    "Why did the fish blush? Because it saw the ocean's bottom!",
    "Elephants are the only animals that can't jump.",
    "Your nose can remember 50,000 different scents!",
    "What's a fish's favorite instrument? The bass guitar!",
    "Butterflies taste with their feet!",
]

_JOKES = [
    "Why don't fish play piano? Because you can't tuna fish!",
    "Why do fish live in salt water? Because pepper makes them sneeze!",
    "What do you call a fish without eyes? A fsh!",
    "Why did the fish blush? Because it saw the ocean's bottom!",
    "What's a fish's favorite instrument? The bass guitar!",
    "What do you call a lazy crayfish? A slobster!",
    "Where do fish keep their money? In the river bank!",
    "What did the fish say when it hit a wall? Dam!",
    "Why are fish so smart? Because they live in schools!",
    "What do sea monsters eat? Fish and ships!",
]

_FACTS = [
    "Did you know octopuses have three hearts?",
    "A group of flamingos is called a 'flamboyance'!",
    "Honey never spoils — they found 3000-year-old honey in Egyptian tombs!",
    "The shortest war in history lasted 38 minutes.",
    "Sea otters hold hands while sleeping so they don't drift apart.",
    "A day on Venus is longer than a year on Venus!",
    "Cows have best friends and get stressed when separated.",
    "Bananas are technically berries, but strawberries aren't!",
    "The average person walks about 100,000 miles in a lifetime.",
    "Dolphins have names for each other!",
    "The moon has moonquakes!",
    "A jiffy is an actual unit of time: 1/100th of a second.",
    "Elephants are the only animals that can't jump.",
    "Your nose can remember 50,000 different scents!",
    "Butterflies taste with their feet!",
    "A bolt of lightning is five times hotter than the surface of the sun!",
    "There are more stars in the universe than grains of sand on Earth!",
    "The human brain uses 20% of the body's total energy.",
    "Sharks have been around longer than trees!",
    "An octopus has blue blood!",
]


def get_random_joke_or_fact() -> str:
    """Return a random joke or fun fact."""
    return random.choice(JOKES_AND_FACTS)


def get_random_joke() -> str:
    """Return a random joke."""
    return random.choice(_JOKES)


def get_random_fact() -> str:
    """Return a random fun fact."""
    return random.choice(_FACTS)
