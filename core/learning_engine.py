"""
Learning Engine — local-only system that learns about the user over time.

Four pillars:
  1. Session distillation  — extract facts from conversations via Groq
  2. Behavioral patterns   — log and distill usage patterns
  3. Interaction quality   — track positive/negative signals, generate response rules
  4. Context injection     — feed learned knowledge back into the AI system prompt

All data lives in %APPDATA%/LittleFish/learning/.
Nothing leaves the machine except Groq API calls for distillation.
"""

import json
import os
import re
import threading
import time
import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _learning_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    d = Path(appdata) / "LittleFish" / "learning" if appdata else Path.home() / ".littlefish" / "learning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(path: Path, default):
    """Read JSON file, return *default* if missing or corrupt."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[LEARN] Failed to read {path.name}: {exc}")
    return default


def _write_json(path: Path, data):
    """Write JSON file atomically (write-then-rename)."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"[LEARN] Failed to write {path.name}: {exc}")


# ---------------------------------------------------------------------------
# Quality-signal patterns (compiled once)
# ---------------------------------------------------------------------------

_NEGATIVE_RE = re.compile(
    r"\b("
    r"no|wrong|nope|nah|stop|non hai capito|that'?s not what i meant"
    r"|nevermind|never mind|forget it|no aspetta|non intendevo"
    r"|sbagliato|che c'?entra|basta|sbagli|non capisco"
    r")\b",
    re.IGNORECASE,
)

_POSITIVE_RE = re.compile(
    r"\b("
    r"yes|exactly|perfect|perfetto|grazie|thanks|thank you|good|nice"
    r"|haha|lol|lmao|capito|giusto|bravo|great|correct|esatto|si!?"
    r"|awesome|love it|cool|that'?s right"
    r")\b",
    re.IGNORECASE,
)


class LearningEngine:
    """Local learning engine — observes interactions and distils knowledge."""

    # File names inside the learning directory
    _FACTS_FILE = "learned_facts.json"
    _PATTERNS_FILE = "behavior_patterns.json"
    _RULES_FILE = "response_rules.json"
    _QUALITY_FILE = "interaction_quality.json"
    _GRIEVANCES_FILE = "grievances.json"
    _ALARM_FILE = "alarm_history.json"
    _FOLLOWUPS_FILE = "pending_followups.json"

    def __init__(self, groq_keys: list[str], settings: dict):
        self._groq_keys = groq_keys or []
        self._key_index = 0
        self._settings = settings
        self._dir = _learning_dir()

        # Load persisted state
        self._facts: list[str] = _read_json(self._dir / self._FACTS_FILE, [])
        self._patterns: dict = _read_json(self._dir / self._PATTERNS_FILE,
                                          {"sessions": [], "distilled": {}})
        self._rules: list[str] = _read_json(self._dir / self._RULES_FILE, [])
        self._quality: dict = _read_json(self._dir / self._QUALITY_FILE, {
            "total_interactions": 0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "recent_negatives": [],
            "recent_positives": [],
        })

        # Grievances (Feature 1)
        self._grievances: list[dict] = _read_json(
            self._dir / self._GRIEVANCES_FILE, []
        )
        # Alarm history (Feature 2)
        self._alarm_history: dict = _read_json(
            self._dir / self._ALARM_FILE, {}
        )
        # Calendar sarcasm daily limit tracking
        self._alarm_sarcasm_today: dict[str, str] = {}  # name -> date string

        # Session bookkeeping
        self._session_start: float = 0.0
        self._session_interaction_count: int = 0
        self._followup_fired_this_session: bool = False

        print(f"[LEARN] Loaded {len(self._facts)} facts, "
              f"{len(self._patterns.get('sessions', []))} session logs, "
              f"{len(self._rules)} rules, "
              f"{self._quality.get('total_interactions', 0)} total interactions, "
              f"{len(self._grievances)} grievances")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_interaction(self, user_text: str, fish_response: str, emotion_state: dict):
        """Called after every chat exchange. Tracks quality signals."""
        try:
            signal = self._detect_quality_signal(user_text)
            q = self._quality
            q["total_interactions"] = q.get("total_interactions", 0) + 1
            self._session_interaction_count += 1

            if signal == "positive":
                q["positive"] = q.get("positive", 0) + 1
                entry = f"user said '{user_text[:80]}' after: {fish_response[:80]}"
                recents = q.setdefault("recent_positives", [])
                recents.append(entry)
                if len(recents) > 20:
                    q["recent_positives"] = recents[-20:]
            elif signal == "negative":
                q["negative"] = q.get("negative", 0) + 1
                entry = f"user said '{user_text[:80]}' after: {fish_response[:80]}"
                recents = q.setdefault("recent_negatives", [])
                recents.append(entry)
                if len(recents) > 20:
                    q["recent_negatives"] = recents[-20:]
            else:
                q["neutral"] = q.get("neutral", 0) + 1

            _write_json(self._dir / self._QUALITY_FILE, q)

            # Every 50 interactions → generate response rules in background
            if q["total_interactions"] % 50 == 0 and q["total_interactions"] > 0:
                print("[LEARN] 50-interaction milestone — generating response rules")
                threading.Thread(target=self._generate_response_rules, daemon=True).start()

        except Exception as exc:
            print(f"[LEARN] log_interaction error: {exc}")

    def log_session_start(self, timestamp: float):
        """Called when the app starts."""
        self._session_start = timestamp
        self._session_interaction_count = 0
        print(f"[LEARN] Session started at {datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M')}")

    def log_session_end(self, conversation_history: list):
        """Called on app quit. Logs the session and kicks off async distillation."""
        try:
            now = datetime.datetime.now()
            start_dt = datetime.datetime.fromtimestamp(self._session_start) if self._session_start else now
            duration = int((now - start_dt).total_seconds() / 60)

            # Build session entry
            session_entry = {
                "date": now.strftime("%Y-%m-%d"),
                "start_hour": start_dt.hour,
                "end_hour": now.hour,
                "duration_minutes": max(duration, 1),
                "interaction_count": self._session_interaction_count,
                "dominant_emotion": self._guess_dominant_emotion(conversation_history),
                "topics": self._extract_topics(conversation_history),
            }

            sessions = self._patterns.setdefault("sessions", [])
            sessions.append(session_entry)
            # Keep last 100 session logs
            if len(sessions) > 100:
                self._patterns["sessions"] = sessions[-100:]
            _write_json(self._dir / self._PATTERNS_FILE, self._patterns)
            print(f"[LEARN] Session logged: {duration}min, {self._session_interaction_count} interactions")

            # Distill session facts in background thread (never blocks quit)
            if conversation_history:
                history_copy = list(conversation_history)
                t = threading.Thread(
                    target=self._distill_session,
                    args=(history_copy,),
                    daemon=True,
                )
                t.start()
                # Grievance extraction (Feature 1)
                threading.Thread(
                    target=self._distill_grievances,
                    args=(history_copy,),
                    daemon=True,
                ).start()
                # Follow-up extraction (Feature 3)
                threading.Thread(
                    target=self._distill_followups,
                    args=(history_copy,),
                    daemon=True,
                ).start()

            # Every 7 sessions → distill patterns
            if len(sessions) % 7 == 0 and len(sessions) > 0:
                print("[LEARN] 7-session milestone — distilling behavioral patterns")
                threading.Thread(target=self._distill_patterns, daemon=True).start()

        except Exception as exc:
            print(f"[LEARN] log_session_end error: {exc}")

    def get_context_injection(self) -> str:
        """Return a formatted string to inject into the AI system prompt."""
        parts = []

        # Facts
        if self._facts:
            fact_str = " ".join(self._facts[:30])
            parts.append(f"[LEARNED ABOUT USER]\nFacts: {fact_str}")

        # Behavioral patterns
        distilled = self._patterns.get("distilled", {})
        if distilled:
            pattern_parts = []
            if distilled.get("peak_hours"):
                pattern_parts.append(f"Most active {distilled['peak_hours']}.")
            if distilled.get("avg_session_minutes"):
                pattern_parts.append(f"Average session {distilled['avg_session_minutes']} minutes.")
            if distilled.get("most_common_topics"):
                topics = ", ".join(distilled["most_common_topics"][:5])
                pattern_parts.append(f"Common topics: {topics}.")
            if distilled.get("mood_pattern"):
                pattern_parts.append(distilled["mood_pattern"])
            if pattern_parts:
                parts.append("Behavioral patterns: " + " ".join(pattern_parts))

        # Response rules
        if self._rules:
            rules_str = " ".join(self._rules[:10])
            parts.append(f"Response rules: {rules_str}")

        if not parts:
            return ""
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Quality signal detection
    # ------------------------------------------------------------------

    def _detect_quality_signal(self, user_text: str) -> str:
        """Classify user message as positive, negative, or neutral."""
        text = user_text.strip().lower()
        neg = bool(_NEGATIVE_RE.search(text))
        pos = bool(_POSITIVE_RE.search(text))
        if neg and not pos:
            return "negative"
        if pos and not neg:
            return "positive"
        if neg and pos:
            return "neutral"   # mixed signal
        return "neutral"

    # ------------------------------------------------------------------
    # Groq helpers
    # ------------------------------------------------------------------

    def _call_groq(self, system_prompt: str, user_prompt: str,
                   temperature: float = 0.3, max_tokens: int = 800) -> Optional[str]:
        """Call Groq LLM. Rotates keys on failure. Returns None if all fail."""
        try:
            import groq as groq_module
        except ImportError:
            print("[LEARN] groq module not installed — skipping distillation")
            return None

        for _ in range(len(self._groq_keys)):
            key = self._groq_keys[self._key_index]
            try:
                client = groq_module.Groq(api_key=key)
                completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return completion.choices[0].message.content.strip()
            except Exception as exc:
                print(f"[LEARN] Groq call failed (key {self._key_index}): {exc}")
                self._key_index = (self._key_index + 1) % len(self._groq_keys)

        print("[LEARN] All Groq keys exhausted — skipping")
        return None

    def _parse_json_response(self, text: str, expected_type=list):
        """Extract JSON from an LLM response that might include markdown fences."""
        if not text:
            return None
        # Strip markdown code fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, expected_type):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # ------------------------------------------------------------------
    # Pillar 1 — Session distillation
    # ------------------------------------------------------------------

    def _distill_session(self, conversation_history: list):
        """Extract facts from the last conversation. Runs in background thread."""
        try:
            if not self._groq_keys:
                return

            # Take last 20 messages
            recent = conversation_history[-20:]
            if len(recent) < 2:
                return

            convo_text = "\n".join(
                f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                for m in recent
            )

            response = self._call_groq(
                system_prompt=(
                    "Extract facts about the user from this conversation. "
                    "Return ONLY a JSON array of strings, each a short fact. "
                    'Example: ["User codes in Python", "User is Italian", '
                    '"User gets frustrated when things crash"] '
                    "Only include facts that would still be true tomorrow. "
                    "Return [] if nothing meaningful was learned. "
                    "Return ONLY the JSON array, nothing else."
                ),
                user_prompt=convo_text,
                temperature=0.2,
            )

            new_facts = self._parse_json_response(response, list)
            if not new_facts:
                print("[LEARN] Distillation returned no new facts")
                return

            # Filter to strings only
            new_facts = [f for f in new_facts if isinstance(f, str) and f.strip()]
            if not new_facts:
                return

            # Merge — deduplicate by lowercase
            existing_lower = {f.lower() for f in self._facts}
            added = 0
            for fact in new_facts:
                if fact.lower() not in existing_lower:
                    self._facts.append(fact)
                    existing_lower.add(fact.lower())
                    added += 1

            print(f"[LEARN] Distilled {added} new facts (total: {len(self._facts)})")

            # If over 100 facts, ask Groq to consolidate
            if len(self._facts) > 100:
                self._consolidate_facts()

            _write_json(self._dir / self._FACTS_FILE, self._facts)

        except Exception as exc:
            print(f"[LEARN] _distill_session error: {exc}")

    def _consolidate_facts(self):
        """Ask Groq to merge/deduplicate facts down to the 50 most important."""
        try:
            facts_text = json.dumps(self._facts, ensure_ascii=False)
            response = self._call_groq(
                system_prompt=(
                    "You are given a list of facts about a user. "
                    "Merge duplicates, remove trivial ones, and return "
                    "the 50 most important and distinct facts. "
                    "Return ONLY a JSON array of strings, nothing else."
                ),
                user_prompt=facts_text,
                max_tokens=2000,
            )

            consolidated = self._parse_json_response(response, list)
            if consolidated and len(consolidated) >= 10:
                self._facts = [f for f in consolidated if isinstance(f, str)]
                print(f"[LEARN] Consolidated facts: {len(self._facts)}")
            else:
                # Fallback: just trim to newest 80
                self._facts = self._facts[-80:]
                print("[LEARN] Consolidation failed — trimmed to 80")

        except Exception as exc:
            print(f"[LEARN] _consolidate_facts error: {exc}")

    # ------------------------------------------------------------------
    # Pillar 2 — Behavioral pattern distillation
    # ------------------------------------------------------------------

    def _distill_patterns(self):
        """Analyze session logs and extract usage patterns. Runs in background."""
        try:
            if not self._groq_keys:
                return

            sessions = self._patterns.get("sessions", [])
            if len(sessions) < 3:
                return

            # Send the last 30 session logs
            recent_sessions = sessions[-30:]
            sessions_text = json.dumps(recent_sessions, indent=2, ensure_ascii=False)

            response = self._call_groq(
                system_prompt=(
                    "Given these session logs, extract behavioral patterns about this user. "
                    "Return ONLY a JSON object with these keys: "
                    '{"peak_hours": "21-23", "avg_session_minutes": 90, '
                    '"most_common_topics": ["coding", "music"], '
                    '"mood_pattern": "usually focused, crashes make them frustrated", '
                    '"usage_frequency": "daily"}'
                ),
                user_prompt=sessions_text,
                temperature=0.2,
            )

            distilled = self._parse_json_response(response, dict)
            if distilled:
                self._patterns["distilled"] = distilled
                _write_json(self._dir / self._PATTERNS_FILE, self._patterns)
                print(f"[LEARN] Distilled patterns: {distilled}")
            else:
                print("[LEARN] Pattern distillation returned invalid response")

        except Exception as exc:
            print(f"[LEARN] _distill_patterns error: {exc}")

    # ------------------------------------------------------------------
    # Pillar 3 — Response rule generation
    # ------------------------------------------------------------------

    def _generate_response_rules(self):
        """Generate self-improvement rules based on interaction quality. Background."""
        try:
            if not self._groq_keys:
                return

            quality_text = json.dumps(self._quality, indent=2, ensure_ascii=False)

            response = self._call_groq(
                system_prompt=(
                    "You are Little Fish, a desktop companion. Based on this interaction "
                    "quality log, generate rules for yourself to respond better to this "
                    "specific user. Return ONLY a JSON array of rule strings, max 10 rules. "
                    'Example: ["Be more direct, user dislikes long explanations", '
                    '"User appreciates Italian phrases occasionally", '
                    '"Avoid jokes when user seems frustrated"]'
                ),
                user_prompt=quality_text,
                temperature=0.4,
            )

            rules = self._parse_json_response(response, list)
            if rules:
                self._rules = [r for r in rules if isinstance(r, str)][:10]
                _write_json(self._dir / self._RULES_FILE, self._rules)
                print(f"[LEARN] Generated {len(self._rules)} response rules")
            else:
                print("[LEARN] Rule generation returned invalid response")

        except Exception as exc:
            print(f"[LEARN] _generate_response_rules error: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Feature 1 — Grievance extraction
    # ------------------------------------------------------------------

    def _distill_grievances(self, conversation_history: list):
        """Extract grievances/promises from conversation. Runs in background."""
        try:
            if not self._groq_keys:
                return
            recent = conversation_history[-20:]
            if len(recent) < 2:
                return
            convo_text = "\n".join(
                f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                for m in recent
            )
            response = self._call_groq(
                system_prompt=(
                    "From this conversation, extract any promises the user made, "
                    "complaints they expressed, or bad habits they mentioned. "
                    "Return JSON array of strings. "
                    'Example: ["User promised to sleep before 2am", '
                    '"User complained about a family dispute", '
                    '"User said they would exercise more"]. '
                    "Return [] if none. Return ONLY the JSON array."
                ),
                user_prompt=convo_text,
                temperature=0.2,
            )
            new_items = self._parse_json_response(response, list)
            if not new_items:
                return
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            existing_lower = {g["text"].lower() for g in self._grievances}
            added = 0
            for item in new_items:
                if isinstance(item, str) and item.strip() and item.lower() not in existing_lower:
                    self._grievances.append({
                        "text": item.strip(),
                        "date": today,
                        "times_referenced": 0,
                    })
                    existing_lower.add(item.lower())
                    added += 1
            if added:
                # Keep max 50 grievances
                if len(self._grievances) > 50:
                    self._grievances = self._grievances[-50:]
                _write_json(self._dir / self._GRIEVANCES_FILE, self._grievances)
                print(f"[LEARN] Extracted {added} grievances (total: {len(self._grievances)})")
        except Exception as exc:
            print(f"[LEARN] _distill_grievances error: {exc}")

    def get_random_grievance(self) -> dict | None:
        """Return a random unresolved grievance (referenced < 3 times), or None."""
        import random
        eligible = [g for g in self._grievances if g.get("times_referenced", 0) < 3]
        if not eligible:
            return None
        chosen = random.choice(eligible)
        chosen["times_referenced"] = chosen.get("times_referenced", 0) + 1
        try:
            _write_json(self._dir / self._GRIEVANCES_FILE, self._grievances)
        except Exception:
            pass
        return chosen

    # ------------------------------------------------------------------
    # Feature 2 — Alarm history tracking
    # ------------------------------------------------------------------

    def log_alarm_result(self, name: str, acknowledged: bool):
        """Log whether an alarm was acknowledged or ignored."""
        try:
            key = name.strip().lower()
            if not key:
                return
            entry = self._alarm_history.setdefault(key, {
                "set_count": 0, "completed_count": 0, "ignored_count": 0,
            })
            if acknowledged:
                entry["completed_count"] = entry.get("completed_count", 0) + 1
            else:
                entry["ignored_count"] = entry.get("ignored_count", 0) + 1
            _write_json(self._dir / self._ALARM_FILE, self._alarm_history)
        except Exception as exc:
            print(f"[LEARN] log_alarm_result error: {exc}")

    def log_alarm_set(self, name: str):
        """Log that an alarm was set."""
        try:
            key = name.strip().lower()
            if not key:
                return
            entry = self._alarm_history.setdefault(key, {
                "set_count": 0, "completed_count": 0, "ignored_count": 0,
            })
            entry["set_count"] = entry.get("set_count", 0) + 1
            _write_json(self._dir / self._ALARM_FILE, self._alarm_history)
        except Exception as exc:
            print(f"[LEARN] log_alarm_set error: {exc}")

    def get_alarm_ignore_count(self, name: str) -> int:
        """Return how many times alarms matching this name have been ignored."""
        GYM_KEYWORDS = {'gym', 'workout', 'exercise', 'palestra', 'run', 'jog'}
        name_lower = name.strip().lower()
        total_ignored = 0
        for key, entry in self._alarm_history.items():
            # Check if the alarm name matches gym keywords
            key_words = set(key.split())
            name_words = set(name_lower.split())
            if key_words & GYM_KEYWORDS or name_words & GYM_KEYWORDS:
                if key_words & GYM_KEYWORDS and name_words & GYM_KEYWORDS:
                    total_ignored += entry.get("ignored_count", 0)
            elif key == name_lower:
                total_ignored += entry.get("ignored_count", 0)
        return total_ignored

    def check_alarm_sarcasm_today(self, name: str) -> bool:
        """Return True if sarcasm has NOT been fired for this alarm name today."""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        key = name.strip().lower()
        return self._alarm_sarcasm_today.get(key) != today

    def mark_alarm_sarcasm_fired(self, name: str):
        """Mark that sarcasm fired for this alarm name today."""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        self._alarm_sarcasm_today[name.strip().lower()] = today

    # ------------------------------------------------------------------
    # Feature 3 — Follow-up extraction
    # ------------------------------------------------------------------

    def _distill_followups(self, conversation_history: list):
        """Extract situations needing follow-up. Runs in background."""
        try:
            if not self._groq_keys:
                return
            recent = conversation_history[-20:]
            if len(recent) < 2:
                return
            convo_text = "\n".join(
                f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                for m in recent
            )
            response = self._call_groq(
                system_prompt=(
                    "From this conversation, identify any situations the user "
                    "mentioned that have a natural follow-up in 1-3 days. "
                    "Things like: problems they are dealing with, events coming up, "
                    "conflicts they mentioned, things they were waiting for. "
                    'Return JSON array: [{"topic": "...", "followup_question": "...", '
                    '"followup_after_hours": N}]. Max 3 items. Return [] if none. '
                    "Return ONLY the JSON array."
                ),
                user_prompt=convo_text,
                temperature=0.2,
            )
            new_followups = self._parse_json_response(response, list)
            if not new_followups:
                return
            now_ts = time.time()
            pending = _read_json(self._dir / self._FOLLOWUPS_FILE, [])
            added = 0
            for item in new_followups:
                if not isinstance(item, dict):
                    continue
                topic = item.get("topic", "")
                question = item.get("followup_question", "")
                hours = item.get("followup_after_hours", 48)
                if not topic or not question:
                    continue
                # Don't duplicate topics
                if any(p.get("topic", "").lower() == topic.lower() for p in pending):
                    continue
                pending.append({
                    "topic": topic,
                    "followup_question": question,
                    "followup_after_hours": hours,
                    "created_time": now_ts,
                    "used": False,
                })
                added += 1
            # Keep max 20 entries (10 active + 10 used)
            active = [p for p in pending if not p.get("used")]
            used = [p for p in pending if p.get("used")]
            if len(active) > 10:
                active = active[-10:]
            pending = active + used[-10:]
            _write_json(self._dir / self._FOLLOWUPS_FILE, pending)
            if added:
                print(f"[LEARN] Extracted {added} follow-ups")
        except Exception as exc:
            print(f"[LEARN] _distill_followups error: {exc}")

    def get_pending_followup(self) -> dict | None:
        """Return a follow-up whose time has come, or None."""
        if self._followup_fired_this_session:
            return None
        try:
            pending = _read_json(self._dir / self._FOLLOWUPS_FILE, [])
            now_ts = time.time()
            for item in pending:
                if item.get("used"):
                    continue
                created = item.get("created_time", 0)
                hours = item.get("followup_after_hours", 48)
                if now_ts >= created + hours * 3600:
                    return item
        except Exception:
            pass
        return None

    def mark_followup_used(self, topic: str):
        """Mark a follow-up as used so it won't fire again."""
        self._followup_fired_this_session = True
        try:
            pending = _read_json(self._dir / self._FOLLOWUPS_FILE, [])
            for item in pending:
                if item.get("topic", "").lower() == topic.lower():
                    item["used"] = True
            _write_json(self._dir / self._FOLLOWUPS_FILE, pending)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _guess_dominant_emotion(self, conversation_history: list) -> str:
        """Rough heuristic for session's dominant emotion from conversation."""
        if not conversation_history:
            return "neutral"
        # Count emotion-related keywords in assistant messages
        text = " ".join(
            m.get("content", "")
            for m in conversation_history
            if m.get("role") == "user"
        ).lower()
        emotions = {
            "happy": len(re.findall(r"\b(haha|lol|nice|great|awesome|love)\b", text)),
            "frustrated": len(re.findall(r"\b(bug|crash|error|broken|wrong|ugh)\b", text)),
            "focused": len(re.findall(r"\b(code|build|fix|implement|debug|test)\b", text)),
            "curious": len(re.findall(r"\b(how|why|what|explain|tell me)\b", text)),
            "bored": len(re.findall(r"\b(bored|boring|nothing|meh)\b", text)),
        }
        if not any(emotions.values()):
            return "neutral"
        return max(emotions, key=emotions.get)

    def _extract_topics(self, conversation_history: list) -> list:
        """Extract rough topic tags from conversation."""
        if not conversation_history:
            return []
        text = " ".join(
            m.get("content", "")
            for m in conversation_history
            if m.get("role") == "user"
        ).lower()

        topic_patterns = {
            "coding": r"\b(code|coding|python|debug|build|function|class|error|bug)\b",
            "music": r"\b(music|song|spotify|play|listen|piano|guitar)\b",
            "games": r"\b(game|gaming|play|steam|xbox|nintendo)\b",
            "weather": r"\b(weather|rain|sun|temperature|forecast)\b",
            "school": r"\b(school|homework|study|exam|university|college)\b",
            "work": r"\b(work|job|meeting|deadline|project)\b",
            "little fish": r"\b(fish|little fish|you|yourself)\b",
            "bugs": r"\b(bug|fix|broken|crash|issue|problem)\b",
        }

        found = []
        for topic, pattern in topic_patterns.items():
            if re.search(pattern, text):
                found.append(topic)
        return found[:5]
