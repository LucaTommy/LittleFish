"""
Command parser for Little Fish.
Regex pattern matching FIRST, Groq LLM fallback ONLY when patterns miss.
Returns a CommandResult that the widget can act on.
"""

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
# Pattern definitions
# ---------------------------------------------------------------------------

PATTERNS = [
    # "open youtube [query]"
    (r"(?:open|play|search)\s+youtube\s+(.+)",
     lambda m: _open_youtube(m.group(1))),

    # "go to [url]"
    (r"(?:go\s+to|open|navigate\s+to)\s+(https?://\S+)",
     lambda m: _open_url(m.group(1))),

    # "open [website]" — common sites
    (r"(?:open|go\s+to)\s+(youtube|google|github|reddit|twitter|twitch|spotify|netflix|discord)(?:\.com)?",
     lambda m: _open_url(f"https://{m.group(1)}.com")),

    # "open [file] from [folder]" / "open attention from downloads"
    (r"open\s+(?:the\s+)?(.+?)\s+(?:from|in)\s+(downloads?|desktop|documents?|pictures?|music|videos?)",
     lambda m: _open_file_from_folder(m.group(1).strip(), m.group(2).strip())),

    # --- Window management (must be before generic "open/close [app]") ---
    # "snap left / right"
    (r"(?:snap|put)\s+(?:(?:the\s+)?window\s+)?(?:to\s+(?:the\s+)?)?(left|right)",
     lambda m: _snap_window(m.group(1))),

    # "maximize window"
    (r"(?:maximize|maximise|full\s*screen)\s*(?:(?:the\s+)?window)?",
     lambda m: _snap_window("up")),

    # "minimize window" / "minimize this window"  (NOT bare "minimize" – that hides the fish)
    (r"minimize\s+(?:the\s+)?(?:this\s+|current\s+)?window",
     lambda m: _snap_window("down")),

    # "close window" / "close this window" / "close current window"
    (r"close\s+(?:the\s+)?(?:this\s+|current\s+)?window$",
     lambda m: _close_current_window()),

    # "always on top" / "pin window" / "unpin window"
    (r"\b(?:pin|unpin|toggle\s+pin|always\s+on\s+top)\b(?:\s+(?:the\s+)?(?:this\s+|current\s+)?window)?",
     lambda m: _pin_window_on_top()),

    # "open my setup" / "work mode" / "launch my setup"
    (r"(?:(?:open|launch|start)\s+(?:my\s+)?(?:setup|work\s*(?:mode|station)?)|work\s*mode)",
     lambda m: _run_quick_launch("setup")),

    # "open [app]"
    (r"open\s+(?:the\s+)?(.+)",
     lambda m: _open_app(m.group(1).strip())),

    # "close [app]"
    (r"close\s+(?:the\s+)?(.+)",
     lambda m: _close_app(m.group(1).strip())),

    # "play [game name]" / "let's play" / "play a game"
    (r"(?:play|let'?s\s+play)\s+(?:a\s+)?(?:game\s+)?(?:of\s+)?(.+)",
     lambda m: CommandResult("play_game", m.group(1).strip(),
                              f"Let's play {m.group(1).strip()}!")),

    (r"(?:play\s+a\s+game|let'?s\s+play)",
     lambda m: CommandResult("game_picker", "", "What should we play?")),

    # "hobbies" / "show hobbies" / "do a hobby" / "do something fun"
    (r"(?:show\s+)?hobbies|do\s+(?:a\s+)?hobb(?:y|ies)|do\s+something\s+fun",
     lambda m: CommandResult("hobby_picker", "", "Let me show you what I can do!")),

    # "volume up/down"
    (r"(?:turn\s+)?volume\s+(up|down)",
     lambda m: _volume(m.group(1))),

    # "take a break" / "pause" / "rest"
    (r"(?:take\s+a\s+break|\bpause\b|\brest\b|\bchill\b)",
     lambda m: CommandResult("rest_mode", "", "I'll be quiet for a bit. Poke me when you need me.")),

    # "come here"
    (r"come\s+here",
     lambda m: CommandResult("come_to_cursor", "", "Coming!")),

    # "go away" / "hide"
    (r"(?:go\s+away|\bhide\b|\bdisappear\b|\bminimize\b)",
     lambda m: CommandResult("hide", "", "I'll be in the tray if you need me.")),

    # Greetings
    (r"good\s+morning",
     lambda m: CommandResult("greeting", "morning", "Good morning! Ready for today?")),

    (r"good\s+night",
     lambda m: CommandResult("greeting", "night", "Good night! Sleep well.")),

    (r"(?:hello|hey|hi)\b",
     lambda m: CommandResult("greeting", "hello", "Hey there!")),

    # "what time is it"
    (r"what(?:'s|\s+is)\s+the\s+time",
     lambda m: _get_time()),

    # "how are you"
    (r"how\s+are\s+you",
     lambda m: CommandResult("status", "", "")),  # fish_widget fills response from emotion

    # "take a screenshot" / "screenshot"
    (r"(?:take\s+a\s+)?screenshot",
     lambda m: _take_screenshot()),

    # "search for..." / "google..."
    (r"(?:search\s+(?:for\s+)?|google\s+)(.+)",
     lambda m: _google_search(m.group(1).strip())),

    # "open file explorer" / "open explorer" / "open files"
    (r"open\s+(?:file\s+)?explorer|open\s+files",
     lambda m: _open_file_explorer()),

    # "set a timer for X minutes/seconds"
    (r"(?:set\s+(?:a\s+)?timer\s+(?:for\s+)?)(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)",
     lambda m: _set_timer(int(m.group(1)), m.group(2))),

    # "set [name] timer for X minutes" / "start pasta timer 10 minutes"
    (r"(?:set|start)\s+(?:a\s+)?(.+?)\s+timer\s+(?:for\s+)?(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)",
     lambda m: _set_named_timer(m.group(1).strip(), int(m.group(2)), m.group(3))),

    # "remind me in X minutes to..."
    (r"remind\s+me\s+in\s+(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)\s+(?:to\s+)?(.+)",
     lambda m: _set_reminder(int(m.group(1)), m.group(2), m.group(3).strip())),

    # "remind me to [task] in X minutes"
    (r"remind\s+me\s+to\s+(.+?)\s+in\s+(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour(?:s)?)",
     lambda m: _set_reminder(int(m.group(2)), m.group(3), m.group(1).strip())),

    # "alarm at [time]" / "wake me up at [time]" / "set alarm for 7:30"
    (r"(?:set\s+(?:an?\s+)?)?(?:alarm|wake\s+(?:me\s+)?up)\s+(?:at|for)\s+(.+)",
     lambda m: CommandResult("set_alarm", m.group(1).strip(), "")),

    # "lock screen" / "lock"
    (r"lock\s+(?:the\s+)?(?:screen|computer|pc)",
     lambda m: _lock_screen()),

    # "shutdown" / "shut down" / "restart" / "reboot"
    (r"(shut\s*down|restart|reboot)(?:\s+(?:the\s+)?(?:computer|pc))?",
     lambda m: CommandResult("confirm_power", m.group(1).replace(" ", ""),
                              f"Are you sure you want to {m.group(1)}? Say 'yes' to confirm.")),

    # "yes" confirmation for shutdown/restart (handled in widget)
    (r"^yes$",
     lambda m: CommandResult("confirm_yes", "", "Okay!")),

    # "mute" / "unmute"
    (r"\b(mute|unmute)\b",
     lambda m: _toggle_mute(m.group(1))),

    # --- Todo list commands ---
    (r"(?:add\s+(?:a\s+)?todo|add\s+to\s+(?:my\s+)?(?:to-?do|list))\s+(.+)",
     lambda m: CommandResult("todo_add", m.group(1).strip(), "")),

    (r"(?:show|list|what(?:'s| are))\s+(?:my\s+)?(?:to-?do(?:s|'?s)?|tasks?|list)",
     lambda m: CommandResult("todo_list", "", "")),

    (r"(?:done\s+with|finish(?:ed)?|complete(?:d)?|check\s+off)\s+(.+)",
     lambda m: CommandResult("todo_complete", m.group(1).strip(), "")),

    (r"(?:remove|delete)\s+(?:todo\s+)?(.+)",
     lambda m: CommandResult("todo_remove", m.group(1).strip(), "")),

    # --- Companion mode ---
    (r"(?:follow\s+me|companion\s+mode|come\s+with\s+me)",
     lambda m: CommandResult("companion_on", "", "I'll follow you around!")),

    (r"(?:stop\s+following|stay\s+(?:there|put))",
     lambda m: CommandResult("companion_off", "", "Okay, I'll stay put.")),

    # --- Briefing ---
    (r"(?:morning\s+)?(?:\bbrief(?:ing)?\b|\bsummary\b|\breport\b)",
     lambda m: CommandResult("briefing", "", "")),

    # --- Tell me a joke / fact ---
    (r"(?:tell\s+me\s+a\s+)?(?:\bjoke\b|fun\s+fact|\bfact\b)(?:\s+please)?",
     lambda m: CommandResult("joke", "", "")),

    # ===================================================================
    # Phase 1: System Control (new commands)
    # ===================================================================

    # "set volume to 50%" / "volume 30 percent"
    (r"(?:set\s+)?volume\s+(?:to\s+)?(\d+)\s*%?",
     lambda m: _set_volume_pct(int(m.group(1)))),

    # "brightness up/down"
    (r"(?:turn\s+)?brightness\s+(up|down)",
     lambda m: _brightness(m.group(1))),

    # "empty recycle bin" / "empty trash"
    (r"(?:empty|clear)\s+(?:the\s+)?(?:recycle\s+bin|trash|bin)",
     lambda m: _empty_recycle_bin()),

    # "show desktop" / "minimize all" / "minimize everything"
    (r"(?:show\s+(?:the\s+)?desktop|minimize\s+(?:all|everything))",
     lambda m: _show_desktop()),

    # "sleep" / "hibernate" (power action) - distinct from "rest/chill"
    (r"(?:put\s+(?:the\s+)?(?:computer|pc)\s+to\s+)?sleep\s+(?:the\s+)?(?:computer|pc|mode)|hibernate",
     lambda m: _sleep_pc()),

    # "switch window" / "alt tab"
    (r"(?:switch\s+window|alt\s+tab|next\s+window)",
     lambda m: _switch_window()),

    # "open task manager"
    (r"open\s+task\s+manager",
     lambda m: _open_specific_app("taskmgr", "Task Manager")),

    # "kill [process]" / "force close [process]"
    (r"(?:kill|force\s+close)\s+(.+)",
     lambda m: _kill_process(m.group(1).strip())),

    # "check disk space" / "how much space"
    (r"(?:check\s+)?(?:disk|drive|storage)\s+space|how\s+much\s+(?:disk\s+)?space",
     lambda m: _check_disk_space()),

    # "toggle wifi" / "wifi on/off"
    (r"(?:toggle\s+)?wi-?fi\s*(on|off)?",
     lambda m: _toggle_wifi(m.group(1))),

    # "toggle bluetooth" / "bluetooth on/off"
    (r"(?:toggle\s+)?bluetooth\s*(on|off)?",
     lambda m: _toggle_bluetooth(m.group(1))),

    # "open settings" / "open settings [page]"
    (r"open\s+(?:windows\s+)?settings(?:\s+(?:to\s+)?(.+))?",
     lambda m: _open_settings_page(m.group(1))),

    # "dark mode" / "light mode" / "toggle dark mode"
    (r"(?:toggle\s+|switch\s+to\s+)?(?:(dark|light)\s+mode)",
     lambda m: _toggle_theme(m.group(1))),

    # "check speed" / "speed test" / "internet speed"
    (r"(?:check\s+)?(?:internet\s+|download\s+|network\s+)?speed(?:\s+test)?",
     lambda m: CommandResult("speed_test", "", "")),

    # ===================================================================
    # Phase 2: Files & Clipboard
    # ===================================================================

    # "open downloads" / "open desktop" / "open documents"
    (r"open\s+(downloads?|desktop|documents?|pictures?|music|videos?)\s*(?:folder)?",
     lambda m: _open_user_folder(m.group(1).strip())),

    # "find file [name]" / "search for file [name]"
    (r"(?:find|search\s+for)\s+(?:a\s+)?file\s+(?:called\s+|named\s+)?(.+)",
     lambda m: CommandResult("find_file", m.group(1).strip(), f"Searching for {m.group(1).strip()}...")),

    # "read clipboard" / "what's on clipboard" / "what did I copy"
    (r"(?:read\s+(?:my\s+)?clipboard|what(?:'s| is| did I)\s+(?:on\s+(?:my\s+)?clipboard|copy))",
     lambda m: CommandResult("read_clipboard", "", "")),

    # "clear clipboard"
    (r"clear\s+(?:my\s+)?clipboard",
     lambda m: _clear_clipboard()),

    # "save clipboard" / "save what I copied"
    (r"save\s+(?:my\s+)?(?:clipboard|what\s+I\s+copied)",
     lambda m: CommandResult("save_clipboard", "", "")),

    # "create file [name]" / "new file [name]"
    (r"(?:create|new)\s+(?:a\s+)?(?:text\s+)?file(?:\s+(?:called|named)\s+(.+))?",
     lambda m: _create_text_file(m.group(1))),

    # "open recent [folder]" / "open last modified file in [folder]"
    (r"(?:open\s+(?:the\s+)?)?(?:most\s+)?\brecent\s+(?:file|download|desktop|document|picture|music|video)s?(?:\s+(?:in|from)\s+)?(downloads?|desktop|documents?|pictures?|music|videos?)?",
     lambda m: _open_recent_file(m.group(1))),

    # "rename file [old] to [new]" / "rename [old] to [new]"
    (r"rename\s+(?:file\s+)?(.+?)\s+to\s+(.+)",
     lambda m: _rename_file(m.group(1).strip(), m.group(2).strip())),

    # "move file [name] to [folder]" / "move [name] to downloads"
    (r"move\s+(?:(?:the\s+)?file\s+)?(.+?)\s+to\s+(?:the\s+)?(downloads?|desktop|documents?|pictures?|music|videos?)(?:\s+folder)?",
     lambda m: _move_file(m.group(1).strip(), m.group(2).strip())),

    # "zip [folder]" / "zip folder [name]" / "compress [folder]"
    (r"(?:zip|compress)\s+(?:folder\s+|the\s+)?(.+)",
     lambda m: _zip_folder(m.group(1).strip())),

    # ===================================================================
    # Phase 3: Browser & Web (free APIs)
    # ===================================================================

    # "weather" / "what's the weather" / "weather in [city]"
    (r"(?:what(?:'s| is)\s+the\s+)?weather(?:\s+(?:in|for)\s+(.+))?",
     lambda m: CommandResult("weather", m.group(1) or "", "")),

    # "forecast" / "tomorrow's weather"
    (r"(?:weather\s+)?forecast(?:\s+(?:for\s+)?(?:tomorrow|(.+)))?|tomorrow'?s?\s+weather",
     lambda m: CommandResult("forecast", m.group(1) or "", "")),

    # Screen review — must be before Wikipedia "look up" to avoid hijacking
    # "look at my screen" / "look up my screen" / "what do you see" / "what's on my screen"
    (r"(?:look\s+(?:at|up)\s+(?:my|the|this)\s+screen|what(?:'s| is| do you see)\s+(?:on\s+)?(?:my|the)?\s*screen|what\s+do\s+you\s+see|tell\s+me\s+what\s+you\s+see|analyze\s+(?:my\s+)?screen|check\s+(?:my\s+)?screen)",
     lambda m: CommandResult("screen_review", "", "")),

    # "wikipedia [topic]" / "look up [topic]" / "what is [topic]"
    (r"(?:wikipedia|wiki|look\s+up)\s+(.+)",
     lambda m: CommandResult("wikipedia", m.group(1).strip(), "")),

    # "news" / "headlines" / "what's the news"
    (r"(?:what(?:'s| is| are)\s+the\s+)?(?:news|headlines|top\s+stories)",
     lambda m: CommandResult("news", "", "")),

    # "translate [text] to [lang]"
    (r"translate\s+(.+?)\s+(?:to|into)\s+(\w+)",
     lambda m: CommandResult("translate", f"{m.group(2).strip()}|{m.group(1).strip()}", "")),

    # "define [word]" / "what does [word] mean"
    (r"(?:define|definition\s+of)\s+(.+)|what\s+does\s+(\S+)\s+mean",
     lambda m: CommandResult("define", (m.group(1) or m.group(2)).strip(), "")),

    # "exchange rate" / "convert [amount] [from] to [to]"
    (r"(?:exchange\s+rate|convert)\s+(?:(\d+)\s+)?(\w+)\s+to\s+(\w+)",
     lambda m: CommandResult("exchange_rate",
                              f"{m.group(2).upper()}|{m.group(3).upper()}|{m.group(1) or '1'}", "")),

    # "is it a holiday" / "any holidays today"
    (r"(?:is\s+(?:it|today)\s+a\s+)?(?:public\s+)?holiday|any\s+holidays?\s+today",
     lambda m: CommandResult("holiday_check", "", "")),

    # "sunrise" / "sunset" / "sunrise and sunset"
    (r"(?:what(?:'s| is| time is)\s+)?(?:the\s+)?(?:sunrise|sunset)(?:\s+(?:and|&)\s+(?:sunrise|sunset))?",
     lambda m: CommandResult("sun_times", "", "")),

    # ===================================================================
    # Phase 4: Time & Productivity (new)
    # ===================================================================

    # "what day is [date]" / "what day of the week is March 25"
    (r"what\s+day\s+(?:is|of\s+the\s+week\s+is)\s+(.+)",
     lambda m: _day_of_week(m.group(1).strip())),

    # "pomodoro" / "start pomodoro"
    (r"(?:start\s+(?:a\s+)?)?pomodoro",
     lambda m: CommandResult("pomodoro", "", "Starting a 25-minute focus session!")),

    # "uptime" / "how long has my pc been on"
    (r"(?:pc\s+)?uptime|how\s+long\s+(?:has\s+(?:my\s+)?(?:pc|computer)\s+been\s+(?:on|running))",
     lambda m: _pc_uptime()),

    # "countdown to [date]" / "how many days until [date]"
    (r"(?:how\s+many\s+days?\s+(?:until|till|to)|countdown\s+to)\s+(.+)",
     lambda m: _countdown_to(m.group(1).strip())),

    # "what date is it" / "today's date"
    (r"what(?:'s|\s+is)\s+(?:the\s+|today'?s?\s+)?date|today'?s?\s+date",
     lambda m: _get_date()),

    # "time between [date] and [date]" / "how long between [date] and [date]"
    (r"(?:time|how\s+(?:long|many\s+days?))\s+between\s+(.+?)\s+and\s+(.+)",
     lambda m: _time_between_dates(m.group(1).strip(), m.group(2).strip())),

    # "list timers" / "show timers" / "active timers"
    (r"(?:list|show|active|my)\s+timers?|what\s+timers",
     lambda m: CommandResult("list_timers", "", "")),

    # "cancel timer" / "stop timer" / "cancel [name] timer"
    (r"(?:cancel|stop|clear)\s+(?:(?:the\s+)?(.+?)\s+)?timer",
     lambda m: CommandResult("cancel_timer", (m.group(1) or "").strip(), "")),

    # ===================================================================
    # Phase 5: Conversation (Groq-driven)
    # ===================================================================

    # "roast me"
    (r"roast\s+me",
     lambda m: CommandResult("groq_prompt", "roast",
                              "")),  # handled in widget

    # "motivate me" / "give me motivation"
    (r"(?:motivate\s+me|give\s+me\s+(?:a\s+)?motivation(?:al\s+(?:line|quote))?)",
     lambda m: CommandResult("groq_prompt", "motivate", "")),

    # "proofread [text]"
    (r"proofread\s+(.+)",
     lambda m: CommandResult("groq_prompt", f"proofread|{m.group(1).strip()}", "")),

    # "help me name [thing]"
    (r"(?:help\s+me\s+)?name\s+(?:a\s+|my\s+)?(.+)",
     lambda m: CommandResult("groq_prompt", f"name|{m.group(1).strip()}", "")),

    # "suggest something to watch/eat"
    (r"(?:suggest|recommend)\s+(?:something\s+to\s+)?(watch|eat)",
     lambda m: CommandResult("groq_prompt", f"suggest_{m.group(1)}", "")),

    # "quiz me on [topic]"
    (r"quiz\s+me\s+(?:on|about)\s+(.+)",
     lambda m: CommandResult("groq_prompt", f"quiz|{m.group(1).strip()}", "")),

    # "draft email about [topic]" / "write email about..."
    (r"(?:draft|write)\s+(?:an?\s+)?email\s+(?:about\s+)?(.+)",
     lambda m: CommandResult("groq_prompt", f"email|{m.group(1).strip()}", "")),

    # "explain [concept] simply"
    (r"explain\s+(.+?)(?:\s+simply|\s+like\s+I'?m\s+\d+)?",
     lambda m: CommandResult("groq_prompt", f"explain|{m.group(1).strip()}", "")),

    # "summarize [text]"
    (r"summarize\s+(.+)",
     lambda m: CommandResult("groq_prompt", f"summarize|{m.group(1).strip()}", "")),

    # "brainstorm [topic]"
    (r"brainstorm\s+(.+)",
     lambda m: CommandResult("groq_prompt", f"brainstorm|{m.group(1).strip()}", "")),

    # ===================================================================
    # Phase 6: Media Control
    # ===================================================================

    # "play" / "pause" / "play/pause"
    (r"^(?:play|pause|play\s*/?\s*pause)$",
     lambda m: _media_key("play_pause")),

    # "next track" / "next song" / "skip"
    (r"(?:next\s+(?:track|song)|skip(?:\s+(?:track|song))?)",
     lambda m: _media_key("next")),

    # "previous track" / "previous song" / "go back"
    (r"(?:prev(?:ious)?\s+(?:track|song)|go\s+back\s+(?:a\s+)?(?:track|song))",
     lambda m: _media_key("prev")),

    # "what's playing" / "what song is this"
    (r"what(?:'s|\s+is)\s+(?:playing|this\s+song)|current\s+(?:track|song)",
     lambda m: CommandResult("whats_playing", "", "")),

    # "mute mic" / "unmute mic"
    (r"(mute|unmute)\s+(?:my\s+)?(?:mic|microphone)",
     lambda m: CommandResult("toggle_mic", m.group(1), "")),

    # ===================================================================
    # Phase 7: Smart Awareness (queryable)
    # ===================================================================

    # "system status" / "cpu usage" / "ram usage" / "battery level"
    (r"(?:system\s+status|cpu\s+usage|ram\s+usage|battery\s+(?:level|status))",
     lambda m: CommandResult("system_status", "", "")),

    # "top processes" / "what's using cpu"
    (r"(?:top\s+(?:processes|apps)|what(?:'s|\s+is)\s+(?:using|eating)\s+(?:my\s+)?(?:cpu|ram|memory))",
     lambda m: CommandResult("top_processes", "", "")),

    # "how long have I been on" / "session time"
    (r"(?:how\s+long\s+(?:have\s+I\s+)?been\s+on|session\s+time|time\s+on\s+(?:pc|computer))",
     lambda m: CommandResult("session_time", "", "")),

    # "how long in vs code" / "vs code time"
    (r"(?:how\s+long\s+(?:have\s+I\s+)?been\s+in\s+(?:vs\s*code|visual\s+studio)|vs\s*code\s+time|vs\s*code\s+screen\s*time)",
     lambda m: CommandResult("vscode_time", "", "")),

    # "posture check" / "how long sitting" / "am I sitting too long"
    (r"(?:posture\s+(?:check|reminder)|how\s+long\s+(?:have\s+I\s+)?(?:been\s+)?sitting|sitting\s+too\s+long)",
     lambda m: CommandResult("posture_check", "", "")),

    # "last break" / "when was my last break"
    (r"(?:(?:when\s+(?:was|did)\s+)?(?:my\s+)?last\s+break|break\s+history)",
     lambda m: CommandResult("last_break", "", "")),

    # "how many commands" / "command count"
    (r"(?:how\s+many\s+commands|command\s+count|commands?\s+today|commands?\s+used)",
     lambda m: CommandResult("command_count", "", "")),

    # "your mood" / "how are you feeling" / "what's your mood"
    (r"(?:(?:what(?:'s|\s+is)\s+)?your\s+mood|how\s+(?:are\s+)?you\s+feeling|how\s+do\s+you\s+feel)",
     lambda m: CommandResult("fish_mood", "", "")),

    # "daily summary" / "day summary" / "end of day report"
    (r"(?:daily\s+summary|day\s+summary|end\s+of\s+day(?:\s+report)?|today(?:'s)?\s+summary|summarize\s+(?:my\s+)?day)",
     lambda m: CommandResult("daily_summary", "", "")),

    # "app open too long" / "what app has been open the longest"
    (r"(?:(?:which|what)\s+app\s+(?:has\s+been\s+)?(?:open(?:ed)?\s+)?(?:the\s+)?(?:longest|too\s+long)|app\s+(?:too\s+long|open\s+longest))",
     lambda m: CommandResult("app_too_long", "", "")),

    # "media sleep timer" / "pause music after X minutes" / "sleep timer X minutes"
    (r"(?:(?:media|music)\s+sleep\s+timer|(?:pause|stop)\s+(?:music|media)\s+(?:after|in)\s+(\d+)\s*(?:min(?:ute)?s?)|sleep\s+timer\s+(?:for\s+)?(\d+)\s*(?:min(?:ute)?s?))",
     lambda m: CommandResult("media_sleep_timer", m.group(1) or m.group(2) or "30", "")),

    # ===================================================================
    # Screen Review
    # ===================================================================

    # "review this design" / "review this code" / "review the copy" / "review this data"
    (r"review\s+(?:this\s+|the\s+)?(design|code|copy|data)",
     lambda m: CommandResult("screen_review", m.group(1), "")),

    # "review this" / "review my screen" / "what do you think" / "be honest" / "critique this"
    (r"(?:review\s+(?:this|my\s+screen)|what\s+do\s+you\s+think|be\s+honest|critique\s+this|roast\s+my\s+screen)",
     lambda m: CommandResult("screen_review", "", "")),

    # "where?" / "where is that?" / "show me" / "point at it" — fish moves to the thing it was talking about
    (r"(?:where(?:\s+(?:is\s+(?:that|it)|do\s+you\s+see\s+(?:it|that)))?[?\s]*$|show\s+me(?:\s+where)?|point\s+(?:at|to)\s+it)",
     lambda m: CommandResult("point_at_screen", "", "")),

    # ===================================================================
    # Phase 9: Windows & Desktop (continued)
    # ===================================================================

    # "next desktop" / "switch desktop" / "next virtual desktop"
    (r"(?:next|switch(?:\s+to\s+next)?)\s+(?:virtual\s+)?desktop",
     lambda m: _switch_virtual_desktop("next")),

    # "previous desktop" / "last desktop"
    (r"(?:prev(?:ious)?|last|back)\s+(?:virtual\s+)?desktop",
     lambda m: _switch_virtual_desktop("prev")),

    # "task view" / "show all windows" / "show open windows"
    (r"(?:task\s+view|show\s+(?:all\s+)?(?:open\s+)?windows|overview)",
     lambda m: _task_view()),

    # "move window to other monitor" / "move to next monitor"
    (r"(?:move|send)\s+(?:(?:the\s+)?window\s+)?(?:to\s+)?(?:(?:the\s+)?(?:other|next|right)\s+monitor|monitor\s+(?:right|two|2))",
     lambda m: _move_window_to_monitor("right")),

    # "move window to left monitor"
    (r"(?:move|send)\s+(?:(?:the\s+)?window\s+)?(?:to\s+)?(?:(?:the\s+)?(?:left|prev(?:ious)?)\s+monitor|monitor\s+(?:left|one|1))",
     lambda m: _move_window_to_monitor("left")),

    # ===================================================================
    # Phase 10: Quick Launchers & Shortcuts (continued)
    # ===================================================================

    # "morning routine" / "start my day" / "good morning routine"
    (r"(?:(?:start\s+)?(?:my\s+)?morning(?:\s+routine)?|start\s+my\s+day|good\s+morning\s+routine)",
     lambda m: _morning_routine()),

    # "launch [name] shortcut" / "run shortcut [name]"
    (r"(?:launch|run|open|start)\s+(?:(?:the\s+)?shortcut\s+)?[\"']?(.+?)[\"']?\s+shortcut",
     lambda m: _run_quick_launch(m.group(1))),

    # "run [name]" — must be after more specific patterns
    (r"(?:launch|run)\s+(?:shortcut\s+)?[\"']?(.+?)[\"']?$",
     lambda m: _run_quick_launch(m.group(1))),

    # "add shortcut [name] [target]"
    (r"(?:add|save|create)\s+(?:a\s+)?shortcut\s+[\"']?(.+?)[\"']?\s+(?:for|to|as)\s+(.+)",
     lambda m: _add_quick_launch(m.group(1), m.group(2))),

    # "remove shortcut [name]"
    (r"(?:remove|delete)\s+(?:the\s+)?shortcut\s+[\"']?(.+?)[\"']?$",
     lambda m: _remove_quick_launch(m.group(1))),

    # "list shortcuts" / "show shortcuts" / "my shortcuts"
    (r"(?:(?:list|show)\s+(?:my\s+)?(?:shortcuts|launchers)|my\s+shortcuts)",
     lambda m: _list_quick_launches()),

    # ===================================================================
    # Phase 8: Games & Fun (extras)
    # ===================================================================

    # "flip a coin" / "heads or tails"
    (r"(?:flip\s+a\s+coin|heads\s+or\s+tails|coin\s+flip)",
     lambda m: _flip_coin()),

    # "roll a dice" / "roll [N] dice" / "roll d20"
    (r"roll\s+(?:a\s+)?(?:(\d+)\s+)?(?:d(?:ice|(\d+))|dice)",
     lambda m: _roll_dice(m.group(1), m.group(2))),

    # "random number" / "random number between X and Y" / "pick a number"
    (r"(?:random\s+number|pick\s+a\s+number)(?:\s+(?:between\s+)?(\d+)\s+(?:and|to)\s+(\d+))?",
     lambda m: _random_number(m.group(1), m.group(2))),

    # "high scores" / "my scores"
    (r"(?:show\s+)?(?:my\s+)?(?:high\s+)?scores",
     lambda m: CommandResult("high_scores", "", "")),
]


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------

class CommandParser:
    def __init__(self, groq_keys: list[str] = None, fish_name: str = ""):
        self._groq_keys = groq_keys or []
        self._groq_key_index = 0
        self._extra_patterns = []
        if fish_name and fish_name.lower().strip() not in ("little fish", ""):
            escaped = re.escape(fish_name.strip())
            self._extra_patterns.append(
                (rf"(?:hey|hi|hello)?\s*{escaped}\b",
                 lambda m, fn=fish_name.strip(): CommandResult(
                     "greeting", "hello", f"Hey! You called me {fn}?"))
            )

    def parse(self, text: str, from_chat: bool = False) -> Optional[CommandResult]:
        """Parse a transcribed voice command. Returns None if nothing matched.
        
        When from_chat=True, longer conversational sentences skip ambiguous
        regex matches and the Groq command classifier is disabled (the chat
        window routes unmatched text to AI conversation instead).
        """
        clean = text.lower().strip()
        word_count = len(clean.split())

        # Try custom name patterns first
        for pattern, handler in self._extra_patterns:
            m = re.search(pattern, clean, re.IGNORECASE)
            if m:
                return handler(m)

        # Try regex patterns
        # Actions that are too ambiguous to match inside longer chat sentences
        _AMBIGUOUS_ACTIONS = {
            "greeting", "rest_mode", "hide", "status", "confirm_yes",
            "briefing", "joke",
        }
        # Actions with side effects that should NEVER fire from a conversational sentence
        _DANGEROUS_IN_CHAT = {
            "file", "confirm_power",
        }
        for pattern, handler in PATTERNS:
            m = re.search(pattern, clean)
            if m:
                # In chat context with conversational sentences, skip
                # dangerous side-effect patterns BEFORE executing the handler
                if from_chat and word_count > 3:
                    # Peek at the handler to see what it would return.
                    # For safe (no-side-effect) handlers, run normally.
                    # For dangerous ones, we need to check first.
                    result = handler(m)
                    if result.action in _DANGEROUS_IN_CHAT:
                        continue
                    if result.action in _AMBIGUOUS_ACTIONS:
                        continue
                    return result
                result = handler(m)
                return result

        # Groq LLM fallback — skip in chat context (chat routes to AI directly)
        if self._groq_keys and not from_chat:
            return self._groq_fallback(clean)

        return None

    def _groq_fallback(self, text: str) -> Optional[CommandResult]:
        """Use Groq Llama to classify the intent."""
        try:
            import groq as groq_module
        except ImportError:
            return None

        prompt = (
            "You are a command classifier for a desktop pet app. "
            "The user said the following to their desktop companion. "
            "Classify the intent into one of these categories and extract the target:\n"
            "- open_url: user wants to open a website (target = URL)\n"
            "- open_app: user wants to open an application (target = app name)\n"
            "- close_app: user wants to close an app (target = app name)\n"
            "- play_game: user wants to play a game (target = game name)\n"
            "- greeting: user is greeting (target = morning/night/hello)\n"
            "- rest_mode: user wants the pet to be quiet\n"
            "- hide: user wants the pet to hide\n"
            "- come_to_cursor: user wants the pet to come to them\n"
            "- unknown: doesn't match any category\n\n"
            f"User said: \"{text}\"\n\n"
            "Respond in EXACTLY this format (no extra text):\n"
            "ACTION: <action>\n"
            "TARGET: <target>\n"
            "RESPONSE: <short friendly response from the pet>"
        )

        last_error = None
        for _ in range(len(self._groq_keys)):
            key = self._groq_keys[self._groq_key_index]
            try:
                client = groq_module.Groq(api_key=key)
                completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=100,
                )
                return self._parse_groq_response(completion.choices[0].message.content)
            except Exception as e:
                last_error = e
                self._groq_key_index = (self._groq_key_index + 1) % len(self._groq_keys)

        return None

    @staticmethod
    def _parse_groq_response(text: str) -> Optional[CommandResult]:
        """Parse the structured response from Groq."""
        action = target = response = ""
        for line in text.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("ACTION:"):
                action = line.split(":", 1)[1].strip().lower()
            elif line.upper().startswith("TARGET:"):
                target = line.split(":", 1)[1].strip()
            elif line.upper().startswith("RESPONSE:"):
                response = line.split(":", 1)[1].strip()

        if action and action != "unknown":
            return CommandResult(action=action, target=target, response=response)
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
    """Set system volume to exact percentage using pycaw or nircmd fallback."""
    pct = max(0, min(100, pct))
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(pct / 100.0, None)
        return CommandResult("volume", str(pct), f"Volume set to {pct}%.")
    except Exception:
        # Fallback: simulate key presses to approximate
        return CommandResult("volume", str(pct), f"Couldn't set exact volume. Try 'volume up/down'.", success=False)


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
    try:
        import ctypes
        ctypes.windll.user32.OpenClipboard(0)
        ctypes.windll.user32.EmptyClipboard()
        ctypes.windll.user32.CloseClipboard()
        return CommandResult("clipboard", "clear", "Clipboard cleared.")
    except Exception:
        return CommandResult("clipboard", "clear", "Couldn't clear clipboard.", success=False)


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
