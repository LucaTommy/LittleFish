"""
AI chat for Little Fish.
Uses Groq LLM to generate conversational responses when command parser doesn't match.
Keeps a short conversation history so the fish remembers context.

v2: Dynamic system prompt built from character layer, relationship, profile, and emotion.
"""

import random
import queue
import threading
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal


MAX_HISTORY = 30  # keep last N messages for context

# Unprompted prompt templates — keyed by relationship stage for depth gating
UNPROMPTED_PROMPTS = {
    "stranger": [
        "Make a casual observation about what the user is doing right now or the time of day. Be specific, not generic. 1-2 sentences.",
        "Say something dry and slightly funny about desktop life. Reference something concrete. No emotes.",
        "Comment on how long they've been at the computer or what app they're using. Be direct.",
    ],
    "acquaintance": [
        "Make an observation about what they're doing right now. Be specific and a little nosy. 1-2 sentences.",
        "Ask the user a casual question about what they're working on or their day. Something you'd actually want to know.",
        "Share a random thought or mini-opinion about something. Be concrete and a little weird.",
        "Comment on the time or their computer session. Be direct and conversational.",
    ],
    "friend": [
        "Ask the user something genuine about their day, their work, or what they're up to. Like a friend checking in.",
        "Share a thought or observation that references what they're doing or the time. Be natural.",
        "Make a dry but warm comment. You know this person. Reference something specific.",
        "Say something slightly personal — a thought you had, something you noticed. Keep it real.",
        "Ask their opinion on something random. Be conversational so they want to respond.",
    ],
    "close_friend": [
        "Check in on them genuinely. Reference what they're doing or how late it is. Be real, not performative.",
        "Share something honest — a thought, a feeling, an observation. You trust this person.",
        "Ask them something you'd only ask someone you know well. Make it natural.",
        "Say something that shows you pay attention to their habits. Be warm but dry.",
        "Start a casual conversation about something specific — their work, the time, what you've noticed.",
    ],
    "best_friend": [
        "Say something real. Reference your shared history or what they're doing right now. No performance.",
        "Check in the way only a best friend can — casual, genuine, specific.",
        "Share a thought that shows depth and trust. Keep it natural.",
        "Ask them something meaningful but understated. You don't need to try hard with this person.",
        "Say something about the moment — what they're doing, how long they've been at it, how you feel about it.",
    ],
}


class FishChat(QObject):
    """Conversational AI backend using Groq."""

    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, groq_keys: list[str], emotion_getter=None,
                 user_profile=None, relationship=None):
        super().__init__()
        self._groq_keys = groq_keys or []
        self._key_index = 0
        self._emotion_getter = emotion_getter   # callable -> str
        self._user_profile = user_profile       # UserProfile or None
        self._relationship = relationship       # Relationship or None
        self._context_getter = None             # callable -> dict (live context)

        # Load persistent chat history
        from core.intelligence import load_chat_history
        self._history: list[dict] = load_chat_history()
        self._history_lock = threading.Lock()

        # Single worker thread for all chat requests (C3+C4 fix)
        self._chat_queue: queue.Queue = queue.Queue()
        self._chat_thread = threading.Thread(
            target=self._chat_worker, daemon=True
        )
        self._chat_thread.start()

    def set_context_getter(self, getter):
        """Set a callable that returns live context dict with keys:
           active_app, session_hours, session_mins, hour, energy, dominant, compound"""
        self._context_getter = getter

    def _build_system_prompt(self) -> str:
        """Build full system prompt from character layer + emotion + relationship + profile + live context."""
        from core.personality import build_character_prompt
        import datetime

        # Gather context from all systems
        emo = "content"
        if self._emotion_getter:
            try:
                emo = self._emotion_getter()
            except Exception:
                pass

        age_group = "adult"
        fish_name = "Little Fish"
        energy = 1.0

        if self._user_profile:
            age_group = self._user_profile.age_group
            fish_name = self._user_profile.fish_name or "Little Fish"

        # Get energy from emotion engine if available
        try:
            if hasattr(self._emotion_getter, '__self__'):
                engine = self._emotion_getter.__self__
                if hasattr(engine, '_energy'):
                    energy = engine._energy
        except Exception:
            pass

        rel_stage = "stranger"
        if self._relationship:
            rel_stage = self._relationship.stage

        # Character prompt = base identity + mood vocabulary + humor style
        system = build_character_prompt(emo, age_group, rel_stage, fish_name, energy)

        # ── Live situational context ──
        ctx = {}
        if self._context_getter:
            try:
                ctx = self._context_getter()
            except Exception:
                pass

        now = datetime.datetime.now()
        hour = ctx.get("hour", now.hour)
        active_app = ctx.get("active_app", "")
        session_h = ctx.get("session_hours", 0)
        session_m = ctx.get("session_mins", 0)

        situation_parts = []
        situation_parts.append(f"It is currently {now.strftime('%I:%M %p')} on {now.strftime('%A')}.")
        if session_h > 0:
            situation_parts.append(f"The user has been on the computer for {session_h}h {session_m}m this session.")
        elif session_m > 5:
            situation_parts.append(f"The user has been on the computer for {session_m} minutes.")
        if active_app:
            situation_parts.append(f"The user is currently in: {active_app}.")
            window_title = ctx.get("window_title", "")
            if window_title:
                situation_parts.append(f"Window title: {window_title}. React to this context naturally when relevant.")
            # Inject fish's opinion on the active app if one exists
            from core.personality import get_opinion
            op = get_opinion(active_app)
            if op:
                system += f"\nYour private opinion on what they're currently using: {op['line']} Let this color your tone naturally without announcing it."
        if energy < 0.3:
            situation_parts.append("You are running low on energy — you feel drained.")
        elif energy > 0.8:
            situation_parts.append("You feel energetic and alert.")
        system += "\n" + " ".join(situation_parts)

        # Rich emotion context (compound emotions, frustration, vulnerability)
        try:
            if hasattr(self._emotion_getter, '__self__'):
                engine = self._emotion_getter.__self__
                if hasattr(engine, 'get_emotion_context_for_chat'):
                    emo_ctx = engine.get_emotion_context_for_chat()
                    if emo_ctx:
                        system += f"\n{emo_ctx}"
        except Exception:
            system += f"\nYou are currently feeling {emo}."

        # Relationship context
        if self._relationship:
            rel_ctx = self._relationship.get_chat_context()
            if rel_ctx:
                system += f"\n{rel_ctx}"

        # Profile context (user preferences affect conversation style)
        if self._user_profile:
            prof_ctx = self._user_profile.get_chat_personality_context()
            if prof_ctx:
                system += f"\n{prof_ctx}"

        # ── Memory context ──
        try:
            from core.fish_memory import FishMemory
            memories = FishMemory.load().get_chat_context()
            if memories:
                system += f"\n{memories}"
        except Exception:
            pass

        # ── Core behavioral directive ──
        system += (
            "\nNever give generic philosophical responses. Always respond specifically "
            "to exactly what was just said. Be direct and a little odd but never vague. "
            "Reference the current situation (time, what they're doing, how you feel) naturally. "
            "Respond in at least 1-2 complete sentences — don't be overly brief or cryptic."
        )

        return system

    def send(self, user_text: str):
        """Send user message to AI. Non-blocking — emits response_ready when done."""
        if not self._groq_keys:
            self.response_ready.emit("I can't chat without API keys!")
            return
        self._chat_queue.put(("user", user_text))

    def _chat_worker(self):
        """Single daemon loop — serialises all chat requests.

        When multiple user messages arrive in quick succession (common during
        voice conversations), batch them into one AI call so the user gets a
        single coherent response instead of waiting for N sequential calls.
        """
        import time as _time
        while True:
            kind, text = self._chat_queue.get()
            try:
                if kind == "user":
                    # Batch: wait briefly to collect any rapid follow-ups
                    _time.sleep(0.15)
                    texts = [text]
                    while not self._chat_queue.empty():
                        try:
                            k2, t2 = self._chat_queue.get_nowait()
                            if k2 == "user":
                                texts.append(t2)
                            else:
                                # Put non-user items back
                                self._chat_queue.put((k2, t2))
                                break
                        except Exception:
                            break
                    combined = " ".join(texts) if len(texts) > 1 else texts[0]
                    if len(texts) > 1:
                        print(f"[CHAT] Batched {len(texts)} rapid messages into one")
                    self._generate(combined)
                elif kind == "unprompted":
                    self._generate_unprompted(text)
            except Exception:
                pass

    def _generate(self, user_text: str):
        try:
            import groq as groq_module
        except ImportError:
            self.error_occurred.emit("groq module not installed")
            return

        # Build messages
        with self._history_lock:
            self._history.append({"role": "user", "content": user_text})
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]
            history_snapshot = list(self._history)

        system = self._build_system_prompt()
        messages = [{"role": "system", "content": system}] + history_snapshot

        last_error = None
        for _ in range(len(self._groq_keys)):
            key = self._groq_keys[self._key_index]
            try:
                client = groq_module.Groq(api_key=key)
                completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    temperature=0.7,
                    max_tokens=200,
                )
                reply = completion.choices[0].message.content.strip()
                from core.personality import apply_verbal_tic
                reply = apply_verbal_tic(reply)
                with self._history_lock:
                    self._history.append({"role": "assistant", "content": reply})
                    history_to_save = list(self._history)
                # Persist chat history
                from core.intelligence import save_chat_history
                save_chat_history(history_to_save)
                self.response_ready.emit(reply)
                return
            except Exception as e:
                last_error = e
                self._key_index = (self._key_index + 1) % len(self._groq_keys)

        self.error_occurred.emit(f"Chat failed: {last_error}")

    # ------------------------------------------------------------------
    # Unprompted speech — fish talks on its own
    # ------------------------------------------------------------------

    def send_unprompted(self):
        """Generate a spontaneous thought without user input."""
        if not self._groq_keys:
            return
        # Pick prompt based on relationship stage
        rel_stage = "stranger"
        if self._relationship:
            rel_stage = self._relationship.stage
        prompts = UNPROMPTED_PROMPTS.get(rel_stage, UNPROMPTED_PROMPTS["stranger"])
        prompt = random.choice(prompts)

        self._chat_queue.put(("unprompted", prompt))

    def _generate_unprompted(self, internal_prompt: str):
        try:
            import groq as groq_module
        except ImportError:
            return

        system = self._build_system_prompt() + "\n" + internal_prompt
        # Include recent chat history so unprompted speech is contextual
        with self._history_lock:
            history_tail = list(self._history[-4:]) if self._history else []
        messages = [{"role": "system", "content": system}]
        if history_tail:
            messages.extend(history_tail)

        for _ in range(len(self._groq_keys)):
            key = self._groq_keys[self._key_index]
            try:
                client = groq_module.Groq(api_key=key)
                completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    temperature=0.9,
                    max_tokens=120,
                )
                reply = completion.choices[0].message.content.strip()
                from core.personality import apply_verbal_tic
                reply = apply_verbal_tic(reply)
                with self._history_lock:
                    self._history.append({"role": "assistant", "content": reply})
                    history_to_save = list(self._history)
                from core.intelligence import save_chat_history
                save_chat_history(history_to_save)
                self.response_ready.emit(reply)
                return
            except Exception:
                self._key_index = (self._key_index + 1) % len(self._groq_keys)
