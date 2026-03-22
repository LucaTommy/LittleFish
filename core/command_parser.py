"""
Command parser for Little Fish.
Two-stage system: fast regex for unambiguous commands, Groq AI intent
classification for everything else.  Returns a CommandResult that the
widget can act on.
"""

import json
import re
import webbrowser
import subprocess
import platform
import datetime
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import psutil


# ---------------------------------------------------------------------------
# Command result
# ---------------------------------------------------------------------------

@dataclass
class CommandResult:
    action: str          # e.g. "open_url", "open_app", "close_app", "play_game", etc.
    target: str = ""     # URL, app name, game name, etc.
    response: str = ""   # What Fish should say back
    success: bool = True


# ---------------------------------------------------------------------------
# Stage 1: Fast regex patterns (unambiguous, time-sensitive commands only)
# ---------------------------------------------------------------------------

_FAST_PATTERNS = [
    # Timer with explicit numbers
    (r"(?:set\s+(?:a\s+)?timer\s+(?:for\s+)?)(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)",
     lambda m: _set_timer(int(m.group(1)), m.group(2))),

    (r"(?:set|start)\s+(?:a\s+)?(.+?)\s+timer\s+(?:for\s+)?(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)",
     lambda m: _set_named_timer(m.group(1).strip(), int(m.group(2)), m.group(3))),

    (r"remind\s+me\s+in\s+(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)\s+(?:to\s+)?(.+)",
     lambda m: _set_reminder(int(m.group(1)), m.group(2), m.group(3).strip())),

    (r"remind\s+me\s+to\s+(.+?)\s+in\s+(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)",
     lambda m: _set_reminder(int(m.group(2)), m.group(3), m.group(1).strip())),

    (r"(?:set\s+(?:an?\s+)?)?(?:alarm|wake\s+(?:me\s+)?up)\s+(?:at|for)\s+(.+)",
     lambda m: CommandResult("set_alarm", m.group(1).strip(), "")),

    # Volume with explicit number
    (r"(?:set\s+)?(?:volume|vol)\s+(?:to\s+)?(\d+)(?:\s+percent)?\s*%?",
     lambda m: _set_volume_pct(int(m.group(1)))),
    (r"(?:alza|abbassa|metti)\s+(?:il\s+)?(?:volume|vol)\s+(?:a\s+)?(\d+)",
     lambda m: _set_volume_pct(int(m.group(1)))),

    # Media keys (bare words, speed-critical)
    (r"^(?:play|pause|play\s*/?\s*pause)$",
     lambda m: _media_key("play_pause")),
    (r"\b(?:pausa|stop\s+music|pause\s+music)\b",
     lambda m: _media_key("play_pause")),
    (r"\b(?:resume|riprendi|play\s+music)\b",
     lambda m: _media_key("play_pause")),
    (r"(?:next(?:\s+(?:track|song))?|skip(?:\s+(?:track|song))?|canzone\s+successiva|avanti)",
     lambda m: _media_key("next")),
    (r"(?:prev(?:ious)?(?:\s+(?:track|song))?|go\s+back(?:\s+(?:a\s+)?(?:track|song))?|canzone\s+precedente|indietro)",
     lambda m: _media_key("prev")),

    # "yes" confirmation for pending actions
    (r"^yes$",
     lambda m: CommandResult("confirm_yes", "", "Okay!")),

    # List/cancel timers (references internal widget state)
    (r"(?:list|show|active|my)\s+timers?|what\s+timers",
     lambda m: CommandResult("list_timers", "", "")),
    (r"(?:cancel|stop|clear)\s+(?:(?:the\s+)?(.+?)\s+)?timer",
     lambda m: CommandResult("cancel_timer", (m.group(1) or "").strip(), "")),
]


# ---------------------------------------------------------------------------
# Stage 2: AI intent classification system prompt
# ---------------------------------------------------------------------------

_INTENT_SYSTEM_PROMPT = """\
You are a command classifier for a desktop companion called Little Fish.
Given user speech, extract the intent and parameters.

Available intents:

Music & Media:
- youtube_search: search/play on YouTube. params: {"query": "..."}
- spotify_search: search/play on Spotify. params: {"query": "..."}
- media_play_pause: toggle play/pause. params: {}
- media_next: next track. params: {}
- media_prev: previous track. params: {}
- whats_playing: what song is playing. params: {}
- media_sleep_timer: stop media after N minutes. params: {"minutes": 30}

Web & Search:
- search_google: search Google. params: {"query": "..."}
- open_website: open a website by name. params: {"site": "google|reddit|github|youtube|twitter|instagram|wikipedia|stackoverflow|twitch|spotify|netflix|discord"}
- open_url: open a specific URL. params: {"url": "https://..."}

Apps & Files:
- open_app: launch an application. params: {"app": "..."}
- close_app: close an application. params: {"app": "..."}
- switch_app: switch to a running app. params: {"app": "..."}
- kill_process: force close a process. params: {"name": "..."}
- open_folder: open a folder. params: {"folder": "downloads|desktop|documents|pictures|music|videos"}
- open_file_explorer: open file explorer. params: {}
- open_file: open a file from a folder. params: {"file": "...", "folder": "downloads|desktop|documents"}
- create_file: create a text file. params: {"name": "..."}
- find_file: search for a file. params: {"name": "..."}

System Control:
- set_volume: set exact volume percentage. params: {"level": 0-100}
- volume_change: volume up or down. params: {"direction": "up|down"}
- mute: mute audio. params: {}
- unmute: unmute audio. params: {}
- lock_screen: lock the computer. params: {}
- show_desktop: minimize all windows. params: {}
- take_screenshot: take a screenshot. params: {}
- brightness: change brightness. params: {"direction": "up|down"}
- power: shutdown/restart/sleep. params: {"action": "shutdown|restart|sleep"}
- disk_space: check disk space. params: {}
- wifi_toggle: toggle wi-fi. params: {"state": "on|off"}
- open_settings: open Windows settings. params: {"page": "display|sound|wifi|bluetooth|apps|update"}
- theme: switch dark/light mode. params: {"mode": "dark|light"}
- system_status: check CPU/RAM/battery. params: {}
- top_processes: top resource-using processes. params: {}
- empty_recycle_bin: empty recycle bin. params: {}
- open_calculator: open calculator app. params: {}
- open_task_manager: open task manager. params: {}
- restart_wifi: restart the network adapter. params: {}
- whats_my_ip: show current IP address. params: {}

Window Management:
- window_snap: snap window left or right. params: {"direction": "left|right"}
- window_maximize: maximize window. params: {}
- window_minimize: minimize current window. params: {}
- close_window: close current window (Alt+F4). params: {}
- pin_window: toggle always-on-top. params: {}
- switch_window: alt-tab to next window. params: {}
- switch_desktop: next/prev virtual desktop. params: {"direction": "next|prev"}
- task_view: show task view / all windows. params: {}
- move_to_monitor: move window to other monitor. params: {"direction": "left|right"}

Time & Productivity:
- tell_time: current time. params: {}
- tell_date: current date. params: {}
- set_timer: set a timer. params: {"amount": 5, "unit": "minutes", "label": ""}
- set_reminder: set a reminder. params: {"amount": 5, "unit": "minutes", "message": "..."}
- remind_me: set a reminder with total seconds and message. params: {"seconds": 0, "message": "..."}
- pomodoro: start 25-min focus session. params: {}
- start_pomodoro: alias for pomodoro. params: {}
- how_long_working: how long the current work session has been. params: {}
- uptime: PC uptime. params: {}
- countdown: days until a date. params: {"date": "..."}
- day_of_week: what day of the week is a date. params: {"date": "..."}
- session_time: how long user has been on. params: {}
- posture_check: sitting time / posture reminder. params: {}
- daily_summary: end-of-day summary. params: {}
- command_count: how many commands used. params: {}
- last_break: when was the last break. params: {}

Todos:
- todo_add: add a todo item. params: {"task": "..."}
- todo_list: list/show todos. params: {}
- todo_complete: mark todo as done. params: {"task": "..."}
- todo_remove: remove a todo. params: {"task": "..."}

Fish Companion:
- greeting: user says hi/hello/good morning/good night. params: {"type": "hello|morning|night"}
- how_are_you: asking how the fish is doing. params: {}
- fish_mood: asking fish's mood. params: {}
- rest_mode: fish should be quiet / take a break. params: {}
- come_here: fish should come to cursor. params: {}
- hide_fish: fish should hide / go away / disappear. params: {}
- companion_on: fish should follow the user around. params: {}
- companion_off: fish should stop following. params: {}
- play_game: play a specific game. params: {"game": "snake|pong|flappy|breakout|minesweeper|memory|trivia|whack|reaction|typing|catch"}
- game_picker: browse / open games menu. params: {}
- play_hobby: do a hobby activity. params: {"hobby": "painting|gaming|gardening|journaling|piano|random"}
- screen_review: look at / review the screen. params: {"focus": "design|code|copy|data"}
- point_at_screen: point at something on screen. params: {}
- high_scores: show game scores. params: {}
- surprise_me: trigger random hobby or animation. params: {}
- how_are_you_feeling: ask fish his current emotional state. params: {}
- tell_joke_italian: tell a joke in Italian. params: {}
- try_to_sing: fish attempts to sing dramatically. params: {}
- go_away: fish moves to far corner. params: {}
- opinion_on_app: fish gives opinion on a specific app. params: {"app": "..."}
- what_learned_about_me: fish shares what he's learned about the user. params: {}
- rate_my_screen: fish reviews/rates the current screen. params: {}
- dance: fish dances. params: {}
- go_to_sleep: put fish to sleep. params: {}
- wake_up: wake fish up. params: {}
- give_compliment: fish gives user a compliment. params: {}
- tell_fact: fish tells an interesting fact. params: {}

Info & Knowledge:
- weather: check weather. params: {"city": "..."}
- forecast: weather forecast. params: {"city": "..."}
- wikipedia: look up a topic. params: {"topic": "..."}
- news: news headlines. params: {}
- translate: translate text. params: {"text": "...", "to": "italian|english|..."}
- define: define a word. params: {"word": "..."}
- exchange_rate: currency conversion. params: {"from": "USD", "to": "EUR", "amount": "1"}
- holiday_check: is today a holiday. params: {}
- sun_times: sunrise/sunset times. params: {}
- briefing: morning briefing / summary. params: {}
- joke: tell a joke or fun fact. params: {}

Clipboard:
- read_clipboard: read what's on clipboard. params: {}
- clipboard_clear: clear clipboard. params: {}
- clipboard_save: save clipboard to file. params: {}

Creative & AI:
- groq_prompt: AI-powered creative request. params: {"type": "roast|motivate|quiz|explain|summarize|brainstorm|email|proofread|name|suggest_watch|suggest_eat", "topic": "..."}

Fun:
- flip_coin: flip a coin. params: {}
- roll_dice: roll dice. params: {"count": 1, "sides": 6}
- random_number: random number in range. params: {"low": 1, "high": 100}

Other:
- open_last_project: open the most recent VSCode workspace. params: {}
- mic_toggle: mute/unmute microphone. params: {"action": "mute|unmute"}
- quick_launch: run a saved shortcut. params: {"name": "..."}
- speed_test: internet speed test. params: {}
- app_too_long: which app has been open longest. params: {}
- vscode_time: time spent in VS Code. params: {}
- chat: NOT a command, just conversation. params: {}

Rules:
- If the user is clearly having a conversation or being casual, return "chat"
- If unsure between a command and chat, return "chat"
- Extract parameters even if phrasing is unusual, casual, or in Italian
- For open_app: any application name works, not just the listed ones
- For play_hobby with no specific hobby mentioned, use "random"

Examples:
- "boot up youtube and put jazz" -> youtube_search, query="jazz"
- "apri youtube e metti musica jazz" -> youtube_search, query="musica jazz"
- "play with your hobby" -> play_hobby, hobby="random"
- "metti un po di jazz" -> spotify_search, query="jazz"
- "quanto e' tardi" -> tell_time
- "che giorno e' oggi" -> tell_date
- "fammi sentire qualcosa di rilassante" -> spotify_search, query="relaxing music"
- "come stai" -> how_are_you
- "blocca lo schermo" -> lock_screen
- "mostra il desktop" -> show_desktop
- "apri chrome" -> open_app, app="chrome"
- "passa a discord" -> switch_app, app="discord"
- "apri documenti" -> open_folder, folder="documents"
- "raccontami una barzelletta" -> joke
- "dimmi le notizie" -> news
- "che tempo fa a Roma" -> weather, city="Roma"
- "quanti giorni mancano a Natale" -> countdown, date="December 25"
- "I love swimming while listening to music" -> chat
- "do you like playing around outside" -> chat
- "ricordami di chiamare la mamma tra 30 minuti" -> remind_me, seconds=1800, message="chiamare la mamma"
- "aggiungi comprare il latte alla lista" -> todo_add, item="comprare il latte"
- "cosa ho da fare" -> todo_list
- "inizia un pomodoro" -> start_pomodoro
- "da quanto sto lavorando" -> how_long_working
- "apri l'ultimo progetto" -> open_last_project
- "traduci ciao in inglese" -> translate, text="ciao", to="english"
- "svuota il cestino" -> empty_recycle_bin
- "apri la calcolatrice" -> open_calculator
- "apri il task manager" -> open_task_manager
- "chiudi questa finestra" -> close_window
- "qual e' il mio IP" -> whats_my_ip
- "riavvia il wifi" -> restart_wifi
- "fai qualcosa di divertente" -> surprise_me
- "come ti senti" -> how_are_you_feeling
- "raccontami una barzelletta in italiano" -> tell_joke_italian
- "prova a cantare qualcosa" -> try_to_sing
- "vieni qui" -> come_here
- "vattene" -> go_away
- "cosa pensi di discord" -> opinion_on_app, app="discord"
- "cosa hai imparato su di me" -> what_learned_about_me
- "guarda lo schermo" -> rate_my_screen
- "balla" -> dance
- "vai a dormire" -> go_to_sleep
- "svegliati" -> wake_up
- "dimmi qualcosa di interessante" -> tell_fact
- "fai un complimento" -> give_compliment

Return ONLY valid JSON, nothing else:
{"intent": "intent_name", "params": {...}, "confidence": 0.0-1.0}

CRITICAL: Your response must be ONLY a JSON object. No explanation. No preamble. No "I'll help you". Just the raw JSON starting with { and ending with }. If you output anything other than pure JSON, the system breaks. Start your response with { immediately.
"""


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------

class CommandParser:
    def __init__(self, groq_keys: list[str] = None, fish_name: str = ""):
        self._groq_keys = groq_keys or []
        self._groq_key_index = 0
        self._groq_client = None
        self._groq_module = None
        self._extra_patterns = []
        self._classify_lock = __import__('threading').Lock()  # serialize Groq calls
        if fish_name and fish_name.lower().strip() not in ("little fish", ""):
            escaped = re.escape(fish_name.strip())
            self._extra_patterns.append(
                (rf"(?:hey|hi|hello)?\s*{escaped}\b",
                 lambda m, fn=fish_name.strip(): CommandResult(
                     "greeting", "hello", f"Hey! You called me {fn}?"))
            )
        # Initialize Groq client for intent classification
        if self._groq_keys:
            try:
                import groq as _groq_mod
                self._groq_module = _groq_mod
                self._groq_client = _groq_mod.Groq(
                    api_key=self._groq_keys[self._groq_key_index])
            except ImportError:
                pass

    # ---------------------------------------------------------------
    # Stage 1: Fast regex parse
    # ---------------------------------------------------------------

    def _fast_parse(self, text: str) -> Optional[CommandResult]:
        """Try fast regex patterns for unambiguous, time-sensitive commands."""
        for pattern, handler in _FAST_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return handler(m)
        return None

    # ---------------------------------------------------------------
    # Stage 2: AI intent classification via Groq
    # ---------------------------------------------------------------

    def classify_intent(self, text: str) -> dict:
        """Call Groq LLM to classify user speech into an intent."""
        with self._classify_lock:
            try:
                return self._classify_intent_inner(text)
            except Exception as e:
                import traceback
                print(f"[INTENT CRASH] {e}")
                print(traceback.format_exc())
                return {"intent": "chat", "params": {}, "confidence": 0.0}

    def _classify_intent_inner(self, text: str) -> dict:
        if not self._groq_client:
            return {"intent": "chat", "params": {}, "confidence": 0.0}

        last_error = None
        for _ in range(len(self._groq_keys)):
            try:
                response = self._groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=150,
                    temperature=0.0,
                )
                raw = response.choices[0].message.content.strip()
                # Strip markdown fences if the model wraps in ```json
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                # Extract JSON even if LLM added preamble
                start = raw.find('{')
                end = raw.rfind('}') + 1
                if start >= 0 and end > start:
                    raw = raw[start:end]
                parsed = json.loads(raw)
                print(f"[INTENT] {parsed.get('intent')} conf={parsed.get('confidence')} params={parsed.get('params')}")
                return parsed
            except json.JSONDecodeError:
                print(f"[INTENT] Bad JSON from LLM: {raw!r}")
                return {"intent": "chat", "params": {}, "confidence": 0.0}
            except Exception as e:
                last_error = e
                # Rotate API key and rebuild client
                self._groq_key_index = (
                    (self._groq_key_index + 1) % len(self._groq_keys))
                try:
                    self._groq_client = self._groq_module.Groq(
                        api_key=self._groq_keys[self._groq_key_index])
                except Exception:
                    pass

        print(f"[INTENT] Classification failed after key rotation: {last_error}")
        return {"intent": "chat", "params": {}, "confidence": 0.0}

    # ---------------------------------------------------------------
    # Build CommandResult from classified intent
    # ---------------------------------------------------------------

    def _build_result(self, intent: str, params: dict) -> Optional[CommandResult]:
        """Map a classified intent + params to a CommandResult."""

        # --- Music & Media ---
        if intent == "youtube_search":
            return _youtube_search(params.get("query", ""))
        elif intent == "spotify_search":
            return _spotify_search(params.get("query", ""))
        elif intent == "media_play_pause":
            return _media_key("play_pause")
        elif intent == "media_next":
            return _media_key("next")
        elif intent == "media_prev":
            return _media_key("prev")
        elif intent == "whats_playing":
            return CommandResult("whats_playing", "", "")
        elif intent == "media_sleep_timer":
            return CommandResult("media_sleep_timer",
                                 str(params.get("minutes", 30)), "")

        # --- Web & Search ---
        elif intent == "search_google":
            return _google_search(params.get("query", ""))
        elif intent == "open_website":
            return _open_website(params.get("site", ""))
        elif intent == "open_url":
            return _open_url(params.get("url", ""))

        # --- Apps & Files ---
        elif intent == "open_app":
            return _open_app(params.get("app", ""))
        elif intent == "close_app":
            return _close_app(params.get("app", ""))
        elif intent == "switch_app":
            return _switch_to_app(params.get("app", ""))
        elif intent == "kill_process":
            return _kill_process(params.get("name", ""))
        elif intent == "open_folder":
            return _open_folder(params.get("folder", ""))
        elif intent == "open_file_explorer":
            return _open_file_explorer()
        elif intent == "open_file":
            return _open_file_from_folder(
                params.get("file", ""), params.get("folder", "downloads"))
        elif intent == "create_file":
            return _create_text_file(params.get("name"))
        elif intent == "find_file":
            name = params.get("name", "")
            return CommandResult("find_file", name,
                                 f"Searching for {name}...")

        # --- System Control ---
        elif intent == "set_volume":
            return _set_volume_pct(int(params.get("level", 50)))
        elif intent == "volume_change":
            return _volume(params.get("direction", "up"))
        elif intent == "mute":
            return _toggle_mute("mute")
        elif intent == "unmute":
            return _toggle_mute("unmute")
        elif intent == "lock_screen":
            return _lock_screen()
        elif intent == "show_desktop":
            return _show_desktop()
        elif intent == "take_screenshot":
            return _take_screenshot()
        elif intent == "brightness":
            return _brightness(params.get("direction", "up"))
        elif intent == "power":
            action = params.get("action", "shutdown")
            if action == "sleep":
                return _sleep_pc()
            return CommandResult(
                "confirm_power", action,
                f"Are you sure you want to {action}? Say 'yes' to confirm.")
        elif intent == "disk_space":
            return _check_disk_space()
        elif intent == "wifi_toggle":
            return _toggle_wifi(params.get("state"))
        elif intent == "open_settings":
            return _open_settings_page(params.get("page"))
        elif intent == "theme":
            return _toggle_theme(params.get("mode", "dark"))
        elif intent == "system_status":
            return CommandResult("system_status", "", "")
        elif intent == "top_processes":
            return CommandResult("top_processes", "", "")
        elif intent in ("empty_trash", "empty_recycle_bin"):
            return CommandResult("empty_recycle_bin", "", "")

        # --- Window Management ---
        elif intent == "window_snap":
            return _snap_window(params.get("direction", "left"))
        elif intent == "window_maximize":
            return _snap_window("up")
        elif intent == "window_minimize":
            return _snap_window("down")
        elif intent == "close_window":
            return CommandResult("close_window", "", "")
        elif intent == "pin_window":
            return _pin_window_on_top()
        elif intent == "switch_window":
            return _switch_window()
        elif intent == "switch_desktop":
            return _switch_virtual_desktop(params.get("direction", "next"))
        elif intent == "task_view":
            return _task_view()
        elif intent == "move_to_monitor":
            return _move_window_to_monitor(params.get("direction", "right"))

        # --- Time & Productivity ---
        elif intent == "tell_time":
            return _get_time()
        elif intent == "tell_date":
            return _get_date()
        elif intent == "set_timer":
            amount = int(params.get("amount", 0))
            unit = params.get("unit", "minutes")
            label = params.get("label", "")
            if label:
                return _set_named_timer(label, amount, unit)
            return _set_timer(amount, unit)
        elif intent == "set_reminder":
            return _set_reminder(
                int(params.get("amount", 0)),
                params.get("unit", "minutes"),
                params.get("message", "Time's up!"))
        elif intent == "remind_me":
            secs = int(params.get("seconds", 0))
            msg = params.get("message", "Time's up!")
            label = f"{secs // 60} minutes" if secs >= 60 else f"{secs} seconds"
            return CommandResult("set_reminder", f"{secs}|{msg}",
                                 f"I'll remind you in {label}: {msg}")
        elif intent in ("pomodoro", "start_pomodoro"):
            return CommandResult("pomodoro", "",
                                 "Starting a 25-minute focus session!")
        elif intent == "uptime":
            return _pc_uptime()
        elif intent == "countdown":
            return _countdown_to(params.get("date", ""))
        elif intent == "day_of_week":
            return _day_of_week(params.get("date", ""))
        elif intent in ("session_time", "how_long_working"):
            return CommandResult("session_time", "", "")
        elif intent == "posture_check":
            return CommandResult("posture_check", "", "")
        elif intent == "daily_summary":
            return CommandResult("daily_summary", "", "")
        elif intent == "command_count":
            return CommandResult("command_count", "", "")
        elif intent == "last_break":
            return CommandResult("last_break", "", "")

        # --- Todos ---
        elif intent == "todo_add":
            return CommandResult("todo_add", params.get("item", "") or params.get("task", ""), "")
        elif intent == "todo_list":
            return CommandResult("todo_list", "", "")
        elif intent == "todo_complete":
            return CommandResult("todo_complete", params.get("task", ""), "")
        elif intent == "todo_remove":
            return CommandResult("todo_remove", params.get("task", ""), "")

        # --- Fish Companion ---
        elif intent == "greeting":
            gtype = params.get("type", "hello")
            responses = {
                "hello": "Hey there!",
                "morning": "Good morning! Ready for today?",
                "night": "Good night! Sleep well.",
            }
            return CommandResult("greeting", gtype,
                                 responses.get(gtype, "Hey there!"))
        elif intent == "how_are_you":
            return CommandResult("status", "", "")
        elif intent == "fish_mood":
            return CommandResult("fish_mood", "", "")
        elif intent == "rest_mode":
            return CommandResult("rest_mode", "",
                                 "I'll be quiet for a bit. Poke me when you need me.")
        elif intent == "come_here":
            return CommandResult("come_to_cursor", "", "Coming!")
        elif intent == "hide_fish":
            return CommandResult("hide", "",
                                 "I'll be in the tray if you need me.")
        elif intent == "companion_on":
            return CommandResult("companion_on", "",
                                 "I'll follow you around!")
        elif intent == "companion_off":
            return CommandResult("companion_off", "",
                                 "Okay, I'll stay put.")
        elif intent == "play_game":
            game = params.get("game", "")
            if game:
                return CommandResult("play_game", game,
                                     f"Let's play {game}!")
            return CommandResult("game_picker", "",
                                 "What should we play?")
        elif intent == "game_picker":
            return CommandResult("game_picker", "",
                                 "What should we play?")
        elif intent == "play_hobby":
            hobby = params.get("hobby", "random")
            return CommandResult("play_hobby", hobby, "")
        elif intent == "screen_review":
            return CommandResult("screen_review",
                                 params.get("focus", "") or "", "")
        elif intent == "point_at_screen":
            return CommandResult("point_at_screen", "", "")
        elif intent == "high_scores":
            return CommandResult("high_scores", "", "")

        # --- Info & Knowledge ---
        elif intent == "weather":
            return CommandResult("weather", params.get("city", ""), "")
        elif intent == "forecast":
            return CommandResult("forecast", params.get("city", ""), "")
        elif intent == "wikipedia":
            return CommandResult("wikipedia", params.get("topic", ""), "")
        elif intent == "news":
            return CommandResult("news", "", "")
        elif intent == "translate":
            text = params.get("text", "")
            lang = params.get("to", "") or params.get("language", "")
            return CommandResult("translate", f"{text}|{lang}", "")
        elif intent == "define":
            return CommandResult("define", params.get("word", ""), "")
        elif intent == "exchange_rate":
            fr = params.get("from", "USD")
            to = params.get("to", "EUR")
            amt = params.get("amount", "1")
            return CommandResult("exchange_rate", f"{fr}|{to}|{amt}", "")
        elif intent == "holiday_check":
            return CommandResult("holiday_check", "", "")
        elif intent == "sun_times":
            return CommandResult("sun_times", "", "")
        elif intent == "briefing":
            return CommandResult("briefing", "", "")
        elif intent == "joke":
            return CommandResult("joke", "", "")

        # --- Clipboard ---
        elif intent in ("clipboard_read", "read_clipboard"):
            return CommandResult("read_clipboard", "", "")
        elif intent == "clipboard_clear":
            return _clear_clipboard()
        elif intent == "clipboard_save":
            return CommandResult("save_clipboard", "", "")

        # --- Creative & AI ---
        elif intent == "groq_prompt":
            ptype = params.get("type", "")
            topic = params.get("topic", "")
            target = f"{ptype}|{topic}" if topic else ptype
            return CommandResult("groq_prompt", target, "")

        # --- Fun ---
        elif intent == "flip_coin":
            return _flip_coin()
        elif intent == "roll_dice":
            count = str(params.get("count", "")) if params.get("count") else None
            sides = str(params.get("sides", "")) if params.get("sides") else None
            return _roll_dice(count, sides)
        elif intent == "random_number":
            low = str(params.get("low", "")) if params.get("low") else None
            high = str(params.get("high", "")) if params.get("high") else None
            return _random_number(low, high)

        # --- Other ---
        elif intent == "mic_toggle":
            return CommandResult("toggle_mic",
                                 params.get("action", "mute"), "")
        elif intent == "quick_launch":
            return _run_quick_launch(params.get("name", ""))
        elif intent == "speed_test":
            return CommandResult("speed_test", "", "")
        elif intent == "app_too_long":
            return CommandResult("app_too_long", "", "")
        elif intent == "vscode_time":
            return CommandResult("vscode_time", "", "")
        elif intent == "open_last_project":
            return CommandResult("open_last_project", "", "")
        elif intent == "whats_my_ip":
            return CommandResult("whats_my_ip", "", "")
        elif intent == "restart_wifi":
            return CommandResult("restart_wifi", "", "")
        elif intent == "open_calculator":
            return CommandResult("open_calculator", "", "")
        elif intent == "open_task_manager":
            return CommandResult("open_task_manager", "", "")

        # --- New personality / fun intents ---
        elif intent == "surprise_me":
            return CommandResult("surprise_me", "", "")
        elif intent == "how_are_you_feeling":
            return CommandResult("how_are_you_feeling", "", "")
        elif intent == "tell_joke_italian":
            return CommandResult("tell_joke_italian", "", "")
        elif intent == "try_to_sing":
            return CommandResult("try_to_sing", "", "")
        elif intent == "go_away":
            return CommandResult("go_away", "", "")
        elif intent == "opinion_on_app":
            return CommandResult("opinion_on_app",
                                 params.get("app", ""), "")
        elif intent == "what_learned_about_me":
            return CommandResult("what_learned_about_me", "", "")
        elif intent == "rate_my_screen":
            return CommandResult("rate_my_screen", "", "")
        elif intent == "dance":
            return CommandResult("dance", "", "")
        elif intent == "go_to_sleep":
            return CommandResult("go_to_sleep", "", "")
        elif intent == "wake_up":
            return CommandResult("wake_up", "", "")
        elif intent == "give_compliment":
            return CommandResult("give_compliment", "", "")
        elif intent == "tell_fact":
            return CommandResult("tell_fact", "", "")

        return None

    # ---------------------------------------------------------------
    # Main parse entry point
    # ---------------------------------------------------------------

    def parse(self, text: str, from_chat: bool = False) -> Optional[CommandResult]:
        """Parse user speech into a command.

        Two-stage system:
          1. Fast regex for unambiguous, time-sensitive commands
          2. Groq AI intent classification for everything else

        Returns None if the text is conversational (not a command).
        """
        clean = text.strip().lower()

        # Try custom name patterns first (wake word)
        for pattern, handler in self._extra_patterns:
            m = re.search(pattern, clean, re.IGNORECASE)
            if m:
                return handler(m)

        # Stage 1: fast regex for time-sensitive commands
        fast_result = self._fast_parse(clean)
        if fast_result:
            return fast_result

        # Stage 2: AI intent classification
        if self._groq_keys:
            classified = self.classify_intent(clean)
            intent = classified.get("intent", "chat")
            confidence = classified.get("confidence", 0.0)

            if intent != "chat" and confidence >= 0.7:
                result = self._build_result(
                    intent, classified.get("params", {}))
                if result:
                    return result

        return None




# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------

def _open_youtube(query: str) -> CommandResult:
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    webbrowser.open(url)
    return CommandResult("open_url", url, f"Searching YouTube for {query}!")


def _open_url(url: str) -> CommandResult:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return CommandResult("open_url", url, "Opening it now!")


APP_ALIASES = {
    "chrome": "chrome",
    "firefox": "firefox",
    "brave": "brave",
    "edge": "msedge",
    "notepad": "notepad",
    "calculator": "calc",
    "spotify": "spotify",
    "discord": "discord",
    "steam": "steam",
    "terminal": "wt" if platform.system() == "Windows" else "gnome-terminal",
    "file manager": "explorer" if platform.system() == "Windows" else "nautilus",
    "explorer": "explorer",
    "files": "explorer" if platform.system() == "Windows" else "nautilus",
    "task manager": "taskmgr",
    "cmd": "cmd",
    "powershell": "powershell",
    "paint": "mspaint",
    "snipping tool": "snippingtool",
    "word": "winword",
    "excel": "excel",
    "outlook": "outlook",
}


def _open_file_from_folder(file_name: str, folder_name: str) -> CommandResult:
    """Open a specific file by name from a user folder."""
    import os
    folder = _get_user_folder(folder_name)
    if not folder or not os.path.isdir(folder):
        return CommandResult("file", "open", f"Couldn't find the {folder_name} folder.", success=False)
    # Exact match first
    exact = os.path.join(folder, file_name)
    if os.path.exists(exact):
        os.startfile(exact)
        return CommandResult("file", "open", f"Opening {file_name}.")
    # Fuzzy search — case-insensitive, partial match
    target = file_name.lower()
    matches = []
    try:
        for f in os.listdir(folder):
            if os.path.isfile(os.path.join(folder, f)):
                if target in f.lower():
                    matches.append(f)
    except OSError:
        return CommandResult("file", "open", f"Couldn't read {folder_name} folder.", success=False)
    if len(matches) == 1:
        os.startfile(os.path.join(folder, matches[0]))
        return CommandResult("file", "open", f"Opening {matches[0]}.")
    elif len(matches) > 1:
        # Pick the best match (shortest name that contains the query)
        best = min(matches, key=len)
        os.startfile(os.path.join(folder, best))
        return CommandResult("file", "open", f"Opening {best}.")
    return CommandResult("file", "open", f"Couldn't find {file_name} in {folder_name}.", success=False)


def _open_app(name: str) -> CommandResult:
    # Check if it's a known URL-like thing
    if "." in name and " " not in name:
        return _open_url(name)

    cmd = APP_ALIASES.get(name.lower(), name)
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["start", cmd], shell=True)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", cmd])
        else:
            subprocess.Popen([cmd])
        return CommandResult("open_app", cmd, f"Opening {name}!")
    except Exception as e:
        return CommandResult("open_app", cmd, f"Couldn't open {name}.", success=False)


def _close_app(name: str) -> CommandResult:
    target = name.lower()
    killed = False
    for proc in psutil.process_iter(["name"]):
        try:
            pname = proc.info["name"].lower()
            if target in pname:
                proc.terminate()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if killed:
        return CommandResult("close_app", target, f"Closed {name}.")
    return CommandResult("close_app", target, f"Couldn't find {name} running.", success=False)


def _volume(direction: str) -> CommandResult:
    try:
        if platform.system() == "Windows":
            import ctypes
            # Use SendInput to simulate volume keys
            VK_VOLUME_UP = 0xAF
            VK_VOLUME_DOWN = 0xAE
            vk = VK_VOLUME_UP if direction == "up" else VK_VOLUME_DOWN
            # keybd_event is simpler for volume
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # key up
            return CommandResult("volume", direction, f"Volume {direction}!")
        else:
            # Linux/Mac — use pactl or osascript
            if platform.system() == "Darwin":
                delta = "10+" if direction == "up" else "10-"
                subprocess.run(["osascript", "-e", f"set volume output volume (output volume of (get volume settings) {delta[:-1]} {delta[-1]} 10)"],
                              capture_output=True, timeout=3)
            else:
                sign = "+" if direction == "up" else "-"
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}5%"],
                              capture_output=True, timeout=3)
            return CommandResult("volume", direction, f"Volume {direction}!")
    except Exception:
        return CommandResult("volume", direction, "Couldn't change volume.", success=False)


def _get_time() -> CommandResult:
    now = datetime.datetime.now()
    time_str = now.strftime("%I:%M %p")
    return CommandResult("info", "time", f"It's {time_str}.")


def _take_screenshot() -> CommandResult:
    """Take a screenshot using Windows API."""
    try:
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.keybd_event(0x2C, 0, 0, 0)  # VK_SNAPSHOT
            ctypes.windll.user32.keybd_event(0x2C, 0, 2, 0)
            return CommandResult("screenshot", "", "Say cheese! Screenshot taken.")
        else:
            subprocess.run(["gnome-screenshot"], capture_output=True, timeout=5)
            return CommandResult("screenshot", "", "Screenshot taken!")
    except Exception:
        return CommandResult("screenshot", "", "Couldn't take a screenshot.", success=False)


def _google_search(query: str) -> CommandResult:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    webbrowser.open(url)
    return CommandResult("open_url", url, f"Searching Google for {query}!")


def _open_file_explorer() -> CommandResult:
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer"])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "."])
        else:
            subprocess.Popen(["xdg-open", "."])
        return CommandResult("open_app", "explorer", "Opening file explorer!")
    except Exception:
        return CommandResult("open_app", "explorer", "Couldn't open explorer.", success=False)


def _set_timer(amount: int, unit: str) -> CommandResult:
    """Set a timer — the widget handles the countdown via QTimer."""
    unit = unit.lower().rstrip("s")
    if "hour" in unit:
        seconds = amount * 3600
        label = f"{amount} hour{'s' if amount != 1 else ''}"
    elif "min" in unit:
        seconds = amount * 60
        label = f"{amount} minute{'s' if amount != 1 else ''}"
    else:
        seconds = amount
        label = f"{amount} second{'s' if amount != 1 else ''}"
    return CommandResult("set_timer", str(seconds), f"Timer set for {label}!")


def _set_reminder(amount: int, unit: str, message: str) -> CommandResult:
    """Set a reminder — the widget handles the countdown."""
    unit = unit.lower().rstrip("s")
    if "hour" in unit:
        seconds = amount * 3600
        label = f"{amount} hour{'s' if amount != 1 else ''}"
    elif "min" in unit:
        seconds = amount * 60
        label = f"{amount} minute{'s' if amount != 1 else ''}"
    else:
        seconds = amount
        label = f"{amount} second{'s' if amount != 1 else ''}"
    return CommandResult("set_reminder", f"{seconds}|{message}",
                          f"I'll remind you in {label}: {message}")


def _set_named_timer(name: str, amount: int, unit: str) -> CommandResult:
    """Set a named timer — e.g. 'pasta timer 10 minutes'."""
    unit = unit.lower().rstrip("s")
    if "hour" in unit:
        seconds = amount * 3600
        label = f"{amount} hour{'s' if amount != 1 else ''}"
    elif "min" in unit:
        seconds = amount * 60
        label = f"{amount} minute{'s' if amount != 1 else ''}"
    else:
        seconds = amount
        label = f"{amount} second{'s' if amount != 1 else ''}"
    return CommandResult("set_named_timer", f"{seconds}|{name}",
                          f"{name.capitalize()} timer set for {label}!")


def _parse_alarm_time(time_str: str):
    """Parse a time string like '7:30 am', '14:00', '7 pm' into seconds from now."""
    import re as _re
    time_str = time_str.strip().lower()
    now = datetime.datetime.now()

    # Try "HH:MM am/pm"
    m = _re.match(r'(\d{1,2}):(\d{2})\s*(am|pm)?', time_str)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return int((target - now).total_seconds()), target.strftime("%I:%M %p")

    # Try "H am/pm"
    m = _re.match(r'(\d{1,2})\s*(am|pm)', time_str)
    if m:
        hour = int(m.group(1))
        ampm = m.group(2)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return int((target - now).total_seconds()), target.strftime("%I:%M %p")

    return None, None


def _time_between_dates(date1_str: str, date2_str: str) -> CommandResult:
    """Calculate time between two dates."""
    try:
        for fmt in ("%B %d %Y", "%B %d, %Y", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%B %d"):
            try:
                d1 = datetime.datetime.strptime(date1_str.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return CommandResult("info", "time_between", "Couldn't parse the first date.", success=False)
        for fmt in ("%B %d %Y", "%B %d, %Y", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%B %d"):
            try:
                d2 = datetime.datetime.strptime(date2_str.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return CommandResult("info", "time_between", "Couldn't parse the second date.", success=False)
        # Fix year if missing
        now_year = datetime.datetime.now().year
        if d1.year == 1900:
            d1 = d1.replace(year=now_year)
        if d2.year == 1900:
            d2 = d2.replace(year=now_year)
        delta = abs((d2 - d1).days)
        return CommandResult("info", "time_between",
                             f"There are {delta} days between {d1.strftime('%B %d, %Y')} and {d2.strftime('%B %d, %Y')}.")
    except Exception:
        return CommandResult("info", "time_between", "Couldn't calculate that.", success=False)


def _lock_screen() -> CommandResult:
    try:
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return CommandResult("lock", "", "Locking the screen. See you later!")
        else:
            subprocess.run(["loginctl", "lock-session"], capture_output=True, timeout=5)
            return CommandResult("lock", "", "Screen locked!")
    except Exception:
        return CommandResult("lock", "", "Couldn't lock the screen.", success=False)


def _toggle_mute(action: str) -> CommandResult:
    try:
        if platform.system() == "Windows":
            import ctypes
            VK_VOLUME_MUTE = 0xAD
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
            return CommandResult("volume", action, f"Volume {action}d!")
    except Exception:
        pass
    return CommandResult("volume", action, f"Couldn't {action}.", success=False)


# ---------------------------------------------------------------------------
# Phase 1: System Control helpers
# ---------------------------------------------------------------------------

def _set_volume_pct(pct: int) -> CommandResult:
    """Return a deferred result — actual pycaw COM runs on the main thread."""
    pct = max(0, min(100, pct))
    return CommandResult("set_volume", str(pct), f"Volume set to {pct}%.")


def _brightness(direction: str) -> CommandResult:
    try:
        import screen_brightness_control as sbc
        current = sbc.get_brightness()[0]
        new_val = min(100, current + 10) if direction == "up" else max(0, current - 10)
        sbc.set_brightness(new_val)
        return CommandResult("brightness", direction, f"Brightness {direction} to {new_val}%.")
    except Exception:
        return CommandResult("brightness", direction, "Couldn't change brightness.", success=False)


def _empty_recycle_bin() -> CommandResult:
    try:
        import ctypes
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x07)
        return CommandResult("system", "recycle_bin", "Recycle bin emptied.")
    except Exception:
        return CommandResult("system", "recycle_bin", "Couldn't empty recycle bin.", success=False)


def _show_desktop() -> CommandResult:
    try:
        import ctypes
        # Simulate Win+D
        VK_LWIN = 0x5B
        VK_D = 0x44
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_D, 0, 0, 0)
        user32.keybd_event(VK_D, 0, 2, 0)
        user32.keybd_event(VK_LWIN, 0, 2, 0)
        return CommandResult("system", "show_desktop", "Showing desktop.")
    except Exception:
        return CommandResult("system", "show_desktop", "Couldn't minimize all.", success=False)


def _sleep_pc() -> CommandResult:
    try:
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
            creationflags=subprocess.CREATE_NO_WINDOW)
        return CommandResult("system", "sleep", "Going to sleep...")
    except Exception:
        return CommandResult("system", "sleep", "Couldn't put PC to sleep.", success=False)


def _switch_window() -> CommandResult:
    try:
        import ctypes
        VK_MENU = 0x12  # Alt
        VK_TAB = 0x09
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_TAB, 0, 0, 0)
        user32.keybd_event(VK_TAB, 0, 2, 0)
        user32.keybd_event(VK_MENU, 0, 2, 0)
        return CommandResult("system", "switch_window", "Switched window.")
    except Exception:
        return CommandResult("system", "switch_window", "Couldn't switch.", success=False)


def _open_specific_app(exe: str, display_name: str) -> CommandResult:
    try:
        subprocess.Popen(exe, creationflags=subprocess.CREATE_NO_WINDOW)
        return CommandResult("open_app", exe, f"Opening {display_name}.")
    except Exception:
        return CommandResult("open_app", exe, f"Couldn't open {display_name}.", success=False)


def _kill_process(name: str) -> CommandResult:
    target = name.lower()
    killed = False
    for proc in psutil.process_iter(["name"]):
        try:
            if target in proc.info["name"].lower():
                proc.kill()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if killed:
        return CommandResult("close_app", target, f"Force killed {name}.")
    return CommandResult("close_app", target, f"Couldn't find {name} running.", success=False)


def _check_disk_space() -> CommandResult:
    try:
        usage = psutil.disk_usage("/")
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        pct = usage.percent
        return CommandResult("info", "disk",
                             f"{free_gb:.1f} GB free of {total_gb:.0f} GB ({pct}% used).")
    except Exception:
        return CommandResult("info", "disk", "Couldn't check disk space.", success=False)


def _toggle_wifi(state: Optional[str]) -> CommandResult:
    action = "disable" if state == "off" else ("enable" if state == "on" else "disable")
    try:
        # Try to find Wi-Fi interface name first
        result = subprocess.run(
            ["netsh", "interface", "show", "interface"],
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        iface = "Wi-Fi"
        for line in result.stdout.splitlines():
            if "wireless" in line.lower() or "wi-fi" in line.lower():
                parts = line.split()
                if len(parts) >= 4:
                    iface = parts[-1]
                    break
        if state is None:
            # Toggle: check current state
            action = "disable" if "Connected" in result.stdout else "enable"
        subprocess.run(
            ["netsh", "interface", "set", "interface", iface, action],
            capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        return CommandResult("system", "wifi", f"Wi-Fi {action}d.")
    except Exception:
        return CommandResult("system", "wifi", "Couldn't toggle Wi-Fi.", success=False)


def _toggle_bluetooth(state: Optional[str]) -> CommandResult:
    # Bluetooth toggle on Windows requires radio manager API which is complex
    return CommandResult("system", "bluetooth",
                         "Bluetooth toggle isn't available. Use Settings.", success=False)


def _open_settings_page(page: Optional[str]) -> CommandResult:
    page_map = {
        None: "ms-settings:",
        "display": "ms-settings:display",
        "sound": "ms-settings:sound",
        "bluetooth": "ms-settings:bluetooth",
        "wifi": "ms-settings:network-wifi",
        "network": "ms-settings:network",
        "battery": "ms-settings:batterysaver",
        "storage": "ms-settings:storagesense",
        "apps": "ms-settings:appsfeatures",
        "notifications": "ms-settings:notifications",
        "privacy": "ms-settings:privacy",
        "update": "ms-settings:windowsupdate",
        "personalization": "ms-settings:personalization",
        "mouse": "ms-settings:mousetouchpad",
        "keyboard": "ms-settings:keyboard",
    }
    if page:
        key = page.strip().lower()
        uri = page_map.get(key, f"ms-settings:{key}")
    else:
        uri = "ms-settings:"
    try:
        import os
        os.startfile(uri)
        return CommandResult("system", "settings", f"Opening Settings.")
    except Exception:
        return CommandResult("system", "settings", "Couldn't open Settings.", success=False)


def _toggle_theme(mode: str) -> CommandResult:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0, winreg.KEY_SET_VALUE)
        value = 0 if mode == "dark" else 1
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)
        winreg.CloseKey(key)
        return CommandResult("system", "theme", f"Switched to {mode} mode.")
    except Exception:
        return CommandResult("system", "theme", f"Couldn't switch to {mode} mode.", success=False)


# ---------------------------------------------------------------------------
# Phase 2: Files & Clipboard helpers
# ---------------------------------------------------------------------------

def _open_user_folder(name: str) -> CommandResult:
    import os
    name = name.lower().rstrip("s")  # "downloads" -> "download"
    folder_map = {
        "download": os.path.join(os.path.expanduser("~"), "Downloads"),
        "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
        "document": os.path.join(os.path.expanduser("~"), "Documents"),
        "picture": os.path.join(os.path.expanduser("~"), "Pictures"),
        "music": os.path.join(os.path.expanduser("~"), "Music"),
        "video": os.path.join(os.path.expanduser("~"), "Videos"),
    }
    path = folder_map.get(name)
    if path and os.path.isdir(path):
        os.startfile(path)
        return CommandResult("open_app", path, f"Opening {name} folder.")
    return CommandResult("open_app", name, f"Couldn't find {name} folder.", success=False)


def _clear_clipboard() -> CommandResult:
    """Return a deferred result — actual clipboard clear runs on the main thread."""
    return CommandResult("clear_clipboard", "", "Clipboard cleared.")


def _create_text_file(name: Optional[str]) -> CommandResult:
    import os
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not name:
        name = f"note_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    elif not name.endswith(".txt"):
        name += ".txt"
    path = os.path.join(desktop, name)
    try:
        with open(path, "w") as f:
            f.write("")
        return CommandResult("file", "create", f"Created {name} on your desktop.")
    except Exception:
        return CommandResult("file", "create", f"Couldn't create file.", success=False)


def _get_user_folder(name: str) -> Optional[str]:
    """Resolve a folder keyword to an absolute path."""
    import os
    key = name.lower().rstrip("s")
    folder_map = {
        "download": os.path.join(os.path.expanduser("~"), "Downloads"),
        "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
        "document": os.path.join(os.path.expanduser("~"), "Documents"),
        "picture": os.path.join(os.path.expanduser("~"), "Pictures"),
        "music": os.path.join(os.path.expanduser("~"), "Music"),
        "video": os.path.join(os.path.expanduser("~"), "Videos"),
    }
    return folder_map.get(key)


def _open_recent_file(folder_name: Optional[str]) -> CommandResult:
    """Open the most recently modified file in the given folder (default: Downloads)."""
    import os
    if not folder_name:
        folder_name = "downloads"
    folder = _get_user_folder(folder_name)
    if not folder or not os.path.isdir(folder):
        return CommandResult("file", "recent", f"Couldn't find the {folder_name} folder.", success=False)
    try:
        files = [os.path.join(folder, f) for f in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, f))]
        if not files:
            return CommandResult("file", "recent", f"No files in {folder_name}.", success=False)
        newest = max(files, key=os.path.getmtime)
        os.startfile(newest)
        return CommandResult("file", "recent", f"Opening {os.path.basename(newest)}.")
    except Exception:
        return CommandResult("file", "recent", "Couldn't open the recent file.", success=False)


def _rename_file(old_name: str, new_name: str) -> CommandResult:
    """Rename a file on Desktop or Downloads by name."""
    import os
    search_dirs = [
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "Downloads"),
        os.path.join(os.path.expanduser("~"), "Documents"),
    ]
    for d in search_dirs:
        old_path = os.path.join(d, old_name)
        if os.path.exists(old_path):
            new_path = os.path.join(d, new_name)
            try:
                os.rename(old_path, new_path)
                return CommandResult("file", "rename", f"Renamed to {new_name}.")
            except OSError as e:
                return CommandResult("file", "rename", f"Couldn't rename: {e}", success=False)
    # Try fuzzy match across search dirs
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if old_name.lower() in f.lower():
                old_path = os.path.join(d, f)
                new_path = os.path.join(d, new_name)
                try:
                    os.rename(old_path, new_path)
                    return CommandResult("file", "rename", f"Renamed {f} to {new_name}.")
                except OSError as e:
                    return CommandResult("file", "rename", f"Couldn't rename: {e}", success=False)
    return CommandResult("file", "rename", f"Couldn't find {old_name}.", success=False)


def _move_file(file_name: str, dest_folder: str) -> CommandResult:
    """Move a file to a user folder (Desktop, Downloads, Documents, etc.)."""
    import os
    import shutil
    dest = _get_user_folder(dest_folder)
    if not dest:
        # Treat as absolute/relative path
        dest = os.path.expanduser(dest_folder)
    if not os.path.isdir(dest):
        return CommandResult("file", "move", f"Folder {dest_folder} not found.", success=False)
    # Search common folders for the file
    search_dirs = [
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "Downloads"),
        os.path.join(os.path.expanduser("~"), "Documents"),
    ]
    for d in search_dirs:
        src = os.path.join(d, file_name)
        if os.path.exists(src):
            try:
                shutil.move(src, os.path.join(dest, os.path.basename(src)))
                return CommandResult("file", "move", f"Moved {file_name} to {dest_folder}.")
            except OSError as e:
                return CommandResult("file", "move", f"Couldn't move: {e}", success=False)
    # Fuzzy match
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if file_name.lower() in f.lower():
                src = os.path.join(d, f)
                try:
                    shutil.move(src, os.path.join(dest, f))
                    return CommandResult("file", "move", f"Moved {f} to {dest_folder}.")
                except OSError as e:
                    return CommandResult("file", "move", f"Couldn't move: {e}", success=False)
    return CommandResult("file", "move", f"Couldn't find {file_name}.", success=False)


def _zip_folder(folder_name: str) -> CommandResult:
    """Zip a folder by name — searches Desktop, Downloads, Documents."""
    import os
    import shutil
    # Check if it's a known user folder
    known = _get_user_folder(folder_name)
    if known and os.path.isdir(known):
        folder_path = known
    else:
        # Search common folders
        search_dirs = [
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "Downloads"),
            os.path.join(os.path.expanduser("~"), "Documents"),
        ]
        folder_path = None
        for d in search_dirs:
            candidate = os.path.join(d, folder_name)
            if os.path.isdir(candidate):
                folder_path = candidate
                break
        if not folder_path:
            # Fuzzy
            for d in search_dirs:
                if not os.path.isdir(d):
                    continue
                for f in os.listdir(d):
                    if folder_name.lower() in f.lower() and os.path.isdir(os.path.join(d, f)):
                        folder_path = os.path.join(d, f)
                        break
                if folder_path:
                    break
    if not folder_path:
        return CommandResult("file", "zip", f"Couldn't find folder {folder_name}.", success=False)
    zip_name = os.path.basename(folder_path)
    zip_path = folder_path + ".zip"
    try:
        shutil.make_archive(folder_path, 'zip', os.path.dirname(folder_path), zip_name)
        return CommandResult("file", "zip", f"Zipped {zip_name} → {zip_name}.zip")
    except Exception as e:
        return CommandResult("file", "zip", f"Couldn't zip: {e}", success=False)


# ---------------------------------------------------------------------------
# Phase 4: Time & Productivity helpers
# ---------------------------------------------------------------------------

def _day_of_week(date_str: str) -> CommandResult:
    """Tell the user what day of the week a date falls on."""
    import dateutil.parser as dp
    try:
        dt = dp.parse(date_str)
        day_name = dt.strftime("%A")
        date_fmt = dt.strftime("%B %d, %Y")
        return CommandResult("info", "day_of_week",
                             f"{date_fmt} is a {day_name}.")
    except Exception:
        # Fallback: try simpler parsing
        try:
            for fmt in ("%B %d", "%B %d %Y", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
                try:
                    dt = datetime.datetime.strptime(date_str, fmt)
                    if dt.year < 2000:
                        dt = dt.replace(year=datetime.datetime.now().year)
                    return CommandResult("info", "day_of_week",
                                         f"{dt.strftime('%B %d, %Y')} is a {dt.strftime('%A')}.")
                except ValueError:
                    continue
        except Exception:
            pass
        return CommandResult("info", "day_of_week",
                             f"Couldn't figure out what day that is.", success=False)


def _pc_uptime() -> CommandResult:
    try:
        import time
        boot = psutil.boot_time()
        uptime = time.time() - boot
        hours = int(uptime // 3600)
        mins = int((uptime % 3600) // 60)
        if hours > 0:
            return CommandResult("info", "uptime", f"Your PC has been on for {hours}h {mins}m.")
        return CommandResult("info", "uptime", f"Your PC has been on for {mins} minutes.")
    except Exception:
        return CommandResult("info", "uptime", "Couldn't check uptime.", success=False)


def _countdown_to(date_str: str) -> CommandResult:
    try:
        import dateutil.parser as dp
        target = dp.parse(date_str)
    except Exception:
        for fmt in ("%B %d", "%B %d %Y", "%m/%d/%Y", "%m/%d"):
            try:
                target = datetime.datetime.strptime(date_str, fmt)
                if target.year < 2000:
                    target = target.replace(year=datetime.datetime.now().year)
                if target < datetime.datetime.now():
                    target = target.replace(year=target.year + 1)
                break
            except ValueError:
                continue
        else:
            return CommandResult("info", "countdown",
                                 "Couldn't parse that date.", success=False)
    delta = (target.date() - datetime.date.today()).days
    if delta == 0:
        return CommandResult("info", "countdown", "That's today.")
    elif delta == 1:
        return CommandResult("info", "countdown", "That's tomorrow.")
    elif delta < 0:
        return CommandResult("info", "countdown",
                             f"That was {abs(delta)} days ago.")
    return CommandResult("info", "countdown",
                         f"{delta} days until {target.strftime('%B %d')}.")


def _get_date() -> CommandResult:
    now = datetime.datetime.now()
    return CommandResult("info", "date",
                         f"It's {now.strftime('%A, %B %d, %Y')}.")


# ---------------------------------------------------------------------------
# Phase 6: Media Control helpers
# ---------------------------------------------------------------------------

def _media_key(action: str) -> CommandResult:
    try:
        import ctypes
        key_map = {
            "play_pause": 0xB3,  # VK_MEDIA_PLAY_PAUSE
            "next": 0xB0,        # VK_MEDIA_NEXT_TRACK
            "prev": 0xB1,        # VK_MEDIA_PREV_TRACK
            "stop": 0xB2,        # VK_MEDIA_STOP
        }
        vk = key_map.get(action)
        if vk:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        labels = {"play_pause": "Toggled play/pause.", "next": "Next track.",
                  "prev": "Previous track.", "stop": "Stopped."}
        return CommandResult("media", action, labels.get(action, "Done."))
    except Exception:
        return CommandResult("media", action, "Couldn't control media.", success=False)


# ---------------------------------------------------------------------------
# Phase 9: Windows & Desktop helpers
# ---------------------------------------------------------------------------

def _snap_window(direction: str) -> CommandResult:
    """Snap current window left / right / maximize / minimize."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_LWIN = 0x5B
        arrows = {"left": 0x25, "right": 0x27, "up": 0x26, "down": 0x28}
        vk = arrows.get(direction, 0x25)
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        user32.keybd_event(VK_LWIN, 0, 2, 0)
        labels = {"left": "Snapped left", "right": "Snapped right",
                  "up": "Maximized", "down": "Minimized"}
        return CommandResult("window", direction, f"{labels.get(direction, 'Done')}.")
    except Exception:
        return CommandResult("window", direction, "Couldn't snap window.", success=False)


def _close_current_window() -> CommandResult:
    """Send Alt+F4 to close the foreground window."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_MENU = 0x12
        VK_F4 = 0x73
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_F4, 0, 0, 0)
        user32.keybd_event(VK_F4, 0, 2, 0)
        user32.keybd_event(VK_MENU, 0, 2, 0)
        return CommandResult("window", "close", "Closed the current window.")
    except Exception:
        return CommandResult("window", "close", "Couldn't close the window.", success=False)


def _switch_virtual_desktop(direction: str) -> CommandResult:
    """Ctrl+Win+Left/Right to move between virtual desktops."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_LWIN = 0x5B
        VK_CONTROL = 0x11
        vk = 0x27 if direction == "next" else 0x25  # Right : Left
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        user32.keybd_event(VK_LWIN, 0, 2, 0)
        user32.keybd_event(VK_CONTROL, 0, 2, 0)
        label = "next" if direction == "next" else "previous"
        return CommandResult("window", "desktop", f"Switched to {label} desktop.")
    except Exception:
        return CommandResult("window", "desktop", "Couldn't switch desktop.", success=False)


def _task_view() -> CommandResult:
    """Win+Tab to open Task View."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_LWIN = 0x5B
        VK_TAB = 0x09
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_TAB, 0, 0, 0)
        user32.keybd_event(VK_TAB, 0, 2, 0)
        user32.keybd_event(VK_LWIN, 0, 2, 0)
        return CommandResult("window", "task_view", "Opening Task View.")
    except Exception:
        return CommandResult("window", "task_view", "Couldn't open Task View.", success=False)


def _move_window_to_monitor(direction: str) -> CommandResult:
    """Win+Shift+Arrow to move window to another monitor."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_LWIN = 0x5B
        VK_SHIFT = 0x10
        vk = 0x27 if direction == "right" else 0x25  # Right : Left
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        user32.keybd_event(VK_SHIFT, 0, 2, 0)
        user32.keybd_event(VK_LWIN, 0, 2, 0)
        return CommandResult("window", "move_monitor", f"Moved window {direction}.")
    except Exception:
        return CommandResult("window", "move_monitor", "Couldn't move window.", success=False)


def _pin_window_on_top() -> CommandResult:
    """Toggle always-on-top for the foreground window."""
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        # Check current state via GetWindowLong
        GWL_EXSTYLE = -20
        WS_EX_TOPMOST = 0x00000008
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        is_topmost = bool(ex_style & WS_EX_TOPMOST)
        new = HWND_NOTOPMOST if is_topmost else HWND_TOPMOST
        user32.SetWindowPos(hwnd, new, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        state = "unpinned" if is_topmost else "pinned on top"
        return CommandResult("window", "pin", f"Window {state}.")
    except Exception:
        return CommandResult("window", "pin", "Couldn't pin window.", success=False)


# ---------------------------------------------------------------------------
# Phase 10: Quick Launchers & Shortcuts helpers
# ---------------------------------------------------------------------------

def _load_quick_launches() -> dict:
    """Load saved quick-launch shortcuts from settings."""
    import json
    from config import CONFIG_PATH
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("quick_launches", {})
    except Exception:
        return {}


def _save_quick_launches(launches: dict) -> None:
    """Persist quick-launch shortcuts to settings."""
    import json
    from config import CONFIG_PATH
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["quick_launches"] = launches
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _run_quick_launch(name: str) -> CommandResult:
    """Execute a saved quick-launch shortcut by name."""
    launches = _load_quick_launches()
    key = name.strip().lower()
    if key not in launches:
        available = ", ".join(launches.keys()) if launches else "none"
        return CommandResult("launcher", name,
                             f"No shortcut called '{name}'. Saved: {available}.", success=False)
    entry = launches[key]
    apps = entry if isinstance(entry, list) else [entry]
    opened = []
    for item in apps:
        try:
            if isinstance(item, dict):
                exe = item.get("exe", "")
                args = item.get("args", [])
                if isinstance(args, str):
                    args = [args]
                subprocess.Popen([exe] + args, creationflags=subprocess.CREATE_NO_WINDOW)
            elif item.startswith("http"):
                webbrowser.open(item)
            else:
                subprocess.Popen(["start", item], shell=True)
            opened.append(str(item) if isinstance(item, str) else item.get("exe", ""))
        except Exception:
            pass
    if opened:
        return CommandResult("launcher", name, f"Launched: {', '.join(opened)}.")
    return CommandResult("launcher", name, f"Couldn't launch '{name}'.", success=False)


def _add_quick_launch(name: str, target: str) -> CommandResult:
    """Add a simple app/URL shortcut."""
    launches = _load_quick_launches()
    launches[name.strip().lower()] = [target.strip()]
    _save_quick_launches(launches)
    return CommandResult("launcher", "add", f"Saved shortcut '{name}'.")


def _remove_quick_launch(name: str) -> CommandResult:
    launches = _load_quick_launches()
    key = name.strip().lower()
    if key in launches:
        del launches[key]
        _save_quick_launches(launches)
        return CommandResult("launcher", "remove", f"Removed shortcut '{name}'.")
    return CommandResult("launcher", "remove", f"No shortcut called '{name}'.", success=False)


def _list_quick_launches() -> CommandResult:
    launches = _load_quick_launches()
    if not launches:
        return CommandResult("launcher", "list", "No shortcuts saved yet.")
    lines = [f"- {k}" for k in sorted(launches.keys())]
    return CommandResult("launcher", "list", "Shortcuts:\n" + "\n".join(lines))


def _morning_routine() -> CommandResult:
    """Run the 'morning' quick launch, or tell user to set one up."""
    launches = _load_quick_launches()
    if "morning" in launches:
        return _run_quick_launch("morning")
    if "routine" in launches:
        return _run_quick_launch("routine")
    return CommandResult("launcher", "morning",
                         "No morning routine set. Say 'add shortcut morning' to create one.",
                         success=False)


# ---------------------------------------------------------------------------
# Phase 8: Games & Fun helpers
# ---------------------------------------------------------------------------

def _flip_coin() -> CommandResult:
    import random
    result = random.choice(["Heads", "Tails"])
    return CommandResult("fun", "coin", f"{result}.")


def _roll_dice(count_str: Optional[str], sides_str: Optional[str]) -> CommandResult:
    import random
    count = int(count_str) if count_str else 1
    sides = int(sides_str) if sides_str else 6
    count = min(count, 20)  # cap at 20 dice
    sides = max(2, min(sides, 100))
    rolls = [random.randint(1, sides) for _ in range(count)]
    if count == 1:
        return CommandResult("fun", "dice", f"Rolled a {rolls[0]}.")
    total = sum(rolls)
    return CommandResult("fun", "dice",
                         f"Rolled {count}d{sides}: {rolls} = {total}.")


def _random_number(low_str: Optional[str], high_str: Optional[str]) -> CommandResult:
    import random
    low = int(low_str) if low_str else 1
    high = int(high_str) if high_str else 100
    result = random.randint(min(low, high), max(low, high))
    return CommandResult("fun", "random", f"{result}.")


# ---------------------------------------------------------------------------
# YouTube / Spotify search helpers
# ---------------------------------------------------------------------------

def _youtube_search(query: str) -> CommandResult:
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    webbrowser.open(url)
    return CommandResult("youtube_search", query, f"Searching YouTube for {query}!")


def _spotify_search(query: str) -> CommandResult:
    webbrowser.open(f"spotify:search:{query}")
    return CommandResult("spotify_search", query, f"Searching Spotify for {query}!")


# ---------------------------------------------------------------------------
# Open website / folder / switch app helpers
# ---------------------------------------------------------------------------

_SITES = {
    "google": "https://google.com",
    "reddit": "https://reddit.com",
    "github": "https://github.com",
    "youtube": "https://youtube.com",
    "twitter": "https://twitter.com",
    "instagram": "https://instagram.com",
    "wikipedia": "https://wikipedia.org",
    "stackoverflow": "https://stackoverflow.com",
    "twitch": "https://twitch.tv",
    "spotify": "https://open.spotify.com",
    "netflix": "https://netflix.com",
    "discord": "https://discord.com",
}


def _open_website(site: str) -> CommandResult:
    url = _SITES.get(site.lower(), f"https://{site}.com")
    webbrowser.open(url)
    return CommandResult("open_url", url, f"Opening {site}!")


def _open_folder(name: str) -> CommandResult:
    """Open a user folder by name, supporting Italian names."""
    import os
    _FOLDERS = {
        "downloads": os.path.expanduser("~/Downloads"),
        "download": os.path.expanduser("~/Downloads"),
        "desktop": os.path.expanduser("~/Desktop"),
        "documents": os.path.expanduser("~/Documents"),
        "document": os.path.expanduser("~/Documents"),
        "documenti": os.path.expanduser("~/Documents"),
        "scrivania": os.path.expanduser("~/Desktop"),
    }
    path = _FOLDERS.get(name.lower(), os.path.expanduser("~"))
    if os.path.isdir(path):
        subprocess.Popen(f'explorer "{path}"')
        return CommandResult("open_app", path, f"Opening {name}!")
    return CommandResult("open_app", name, f"Couldn't find {name} folder.", success=False)


_APP_PROCESS_NAMES = {
    "vscode": "Code.exe",
    "visual studio": "Code.exe",
    "chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "telegram": "Telegram.exe",
    "whatsapp": "WhatsApp.exe",
}


def _switch_to_app(app_name: str) -> CommandResult:
    """Bring an app's window to the foreground."""
    process_name = _APP_PROCESS_NAMES.get(app_name.lower())
    if not process_name:
        return CommandResult("switch_app", app_name,
                             f"Don't know how to switch to {app_name}.", success=False)
    try:
        import win32gui
        target_pid = None
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"] and proc.info["name"].lower() == process_name.lower():
                target_pid = proc.info["pid"]
                break
        if not target_pid:
            return CommandResult("switch_app", app_name,
                                 f"{app_name} doesn't seem to be open.", success=False)

        found_hwnd = [None]

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                _, pid = win32gui.GetWindowThreadProcessId(hwnd)
                if pid == target_pid:
                    found_hwnd[0] = hwnd

        win32gui.EnumWindows(callback, None)
        if found_hwnd[0]:
            win32gui.SetForegroundWindow(found_hwnd[0])
            return CommandResult("switch_app", app_name, f"Switching to {app_name}!")
        return CommandResult("switch_app", app_name,
                             f"Found {app_name} but no visible window.", success=False)
    except Exception as e:
        return CommandResult("switch_app", app_name,
                             f"Couldn't switch to {app_name}.", success=False)
