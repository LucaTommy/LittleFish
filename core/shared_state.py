"""
Shared state for Little Fish.
Writes a live-state JSON file to %APPDATA%/LittleFish/ that the launcher
(or any external tool) can read to display mood, uptime, and stats.
"""

import json
import time
import datetime
from pathlib import Path


def _state_dir() -> Path:
    """Return the shared state directory, creating it if needed."""
    import os
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        d = Path(appdata) / "LittleFish"
    else:
        d = Path.home() / ".littlefish"
    d.mkdir(parents=True, exist_ok=True)
    return d


STATE_PATH = _state_dir() / "state.json"
LOG_PATH = _state_dir() / "mood_log.json"


class SharedState:
    """Periodically writes fish state to a JSON file for external readers."""

    def __init__(self):
        self._start_time = time.monotonic()
        self._start_datetime = datetime.datetime.now().isoformat()
        self._interaction_count: int = 0
        self._games_played: int = 0
        self._phrases_said: int = 0

    def record_interaction(self):
        self._interaction_count += 1

    def record_game(self):
        self._games_played += 1

    def record_phrase(self):
        self._phrases_said += 1

    def write(self, emotions: dict, dominant: str, is_quiet: bool,
              compound: tuple = (), energy: float = 1.0,
              relationship_stage: str = "stranger", relationship_points: int = 0,
              fish_name: str = "Little Fish"):
        """Write current state to the shared JSON file."""
        uptime_secs = time.monotonic() - self._start_time
        state = {
            "version": 2,
            "pid": _get_pid(),
            "started_at": self._start_datetime,
            "updated_at": datetime.datetime.now().isoformat(),
            "uptime_seconds": int(uptime_secs),
            "uptime_human": _format_uptime(uptime_secs),
            "alive": True,
            "emotions": {k: round(v, 3) for k, v in emotions.items()},
            "dominant_emotion": dominant,
            "compound_emotion": list(compound) if compound else [dominant, dominant],
            "energy": round(energy, 3),
            "relationship_stage": relationship_stage,
            "relationship_points": relationship_points,
            "fish_name": fish_name,
            "quiet_mode": is_quiet,
            "stats": {
                "interactions": self._interaction_count,
                "games_played": self._games_played,
                "phrases_said": self._phrases_said,
            },
        }
        try:
            STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass

    def write_stopped(self):
        """Mark state as stopped (fish is quitting)."""
        try:
            if STATE_PATH.exists():
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                data["alive"] = False
                data["updated_at"] = datetime.datetime.now().isoformat()
                STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    def append_mood_log(self, dominant: str):
        """Append an hourly mood sample to the mood log."""
        entry = {
            "time": datetime.datetime.now().isoformat(),
            "mood": dominant,
        }
        try:
            log = []
            if LOG_PATH.exists():
                try:
                    log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    log = []
            # Keep last 168 entries (1 week at 1/hour)
            log.append(entry)
            if len(log) > 168:
                log = log[-168:]
            LOG_PATH.write_text(json.dumps(log, indent=1), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def read() -> dict:
        """Read the current shared state (used by launcher)."""
        try:
            if STATE_PATH.exists():
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return {"alive": False}

    @staticmethod
    def read_mood_log() -> list:
        """Read the mood history log."""
        try:
            if LOG_PATH.exists():
                return json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return []


def _get_pid() -> int:
    import os
    return os.getpid()


def _format_uptime(secs: float) -> str:
    hours = int(secs) // 3600
    mins = (int(secs) % 3600) // 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"
