"""
App reaction system for Little Fish.

Loads reaction data from app_reactions.json, matches against the active window
title and process name, respects per-category cooldowns, and gates reactions
by relationship stage so early-days fish is quiet and longtime-companion fish
has opinions.
"""

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional


# Relationship stage ordering for min_stage gating
_STAGE_ORDER = {
    "stranger": 0,
    "acquaintance": 1,
    "friend": 2,
    "close_friend": 3,
    "best_friend": 4,
}


def _data_path() -> Path:
    """Locate app_reactions.json — works both in dev and frozen builds."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent.parent
    return base / "config" / "app_reactions.json"


def _load_reactions() -> dict:
    """Load and cache the reaction data."""
    p = _data_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"categories": {}}


class AppReactions:
    """Matches active window/process against reaction database with cooldowns."""

    def __init__(self):
        self._data = _load_reactions()
        self._category_cooldowns: dict[str, float] = {}  # category -> last_trigger time
        self._last_trigger_key: str = ""  # avoid repeating same trigger

    def check(self, window_title: str, process_name: str,
              relationship_stage: str = "stranger") -> Optional[dict]:
        """
        Check if the current window matches any reaction trigger.

        Returns dict with keys: text, emotion, emotion_amount, category
        or None if no match / on cooldown.
        """
        title_lower = window_title.lower() if window_title else ""
        proc_lower = process_name.lower() if process_name else ""
        now = time.monotonic()
        stage_rank = _STAGE_ORDER.get(relationship_stage, 0)

        categories = self._data.get("categories", {})

        for cat_name, cat_data in categories.items():
            cooldown = cat_data.get("cooldown", 600)
            last = self._category_cooldowns.get(cat_name, 0.0)
            if now - last < cooldown:
                continue

            triggers = cat_data.get("triggers", {})
            for trigger_key, reactions in triggers.items():
                tk = trigger_key.lower()
                # Match trigger against window title OR process name
                if tk not in title_lower and tk not in proc_lower:
                    continue

                # Don't repeat the exact same trigger back-to-back
                if trigger_key == self._last_trigger_key:
                    continue

                # Filter reactions by relationship stage
                eligible = [
                    r for r in reactions
                    if _STAGE_ORDER.get(r.get("min_stage", "stranger"), 0) <= stage_rank
                ]
                if not eligible:
                    continue

                pick = random.choice(eligible)
                self._category_cooldowns[cat_name] = now
                self._last_trigger_key = trigger_key

                return {
                    "text": pick["text"],
                    "emotion": cat_data.get("emotion"),
                    "emotion_amount": cat_data.get("emotion_amount", 0.15),
                    "category": cat_name,
                }

        return None
