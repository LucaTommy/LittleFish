"""
Text chat window for Little Fish.
Dark-themed message UI for typing messages to the fish.
Persistent conversation, command execution, and memory.
"""

import time, datetime
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QWidget, QLabel,
)


CHAT_STYLE = """
    QDialog {
        background-color: #1A1A2E;
        color: #ECF0F1;
    }
    QLineEdit {
        background-color: #2C3E50;
        color: #ECF0F1;
        border: 1px solid #5BA8C8;
        border-radius: 12px;
        padding: 10px 14px;
        font-family: 'Segoe UI', Consolas, monospace;
        font-size: 13px;
    }
    QLineEdit:focus {
        border: 2px solid #7EC8E3;
    }
    QPushButton {
        background-color: #5BA8C8;
        color: #0F172A;
        border: none;
        border-radius: 10px;
        padding: 10px 18px;
        font-family: 'Segoe UI', Consolas, monospace;
        font-size: 13px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #7EC8E3;
    }
    QPushButton:pressed {
        background-color: #4A9BB8;
    }
    QPushButton#clear {
        background-color: #2C3E50;
        color: #94A3B8;
        font-size: 11px;
        padding: 4px 10px;
        border-radius: 8px;
    }
    QPushButton#clear:hover {
        background-color: #EF4444;
        color: #FFFFFF;
    }
    QPushButton#quick_action {
        background-color: #16213E;
        color: #7EC8E3;
        border: 1px solid #2C3E50;
        border-radius: 14px;
        padding: 4px 12px;
        font-size: 11px;
        font-weight: normal;
    }
    QPushButton#quick_action:hover {
        background-color: #2C3E50;
        border-color: #5BA8C8;
    }
    QScrollArea {
        border: none;
        background-color: transparent;
    }
"""

EMOTION_ICONS = {
    "happy": "\U0001F60A", "bored": "\U0001F611", "curious": "\U0001F914",
    "sleepy": "\U0001F634", "excited": "\U0001F929", "worried": "\U0001F630",
    "focused": "\U0001F9D0", "frustrated": "\U0001F624", "content": "\U0001F60C",
}


class MessageBubble(QWidget):
    """A single message bubble in the chat with timestamp."""

    def __init__(self, text: str, is_user: bool, fish_name: str = "Fish", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        # Message label
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setFont(QFont("Segoe UI", 11))
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if is_user:
            self._label.setText(text)
            self._label.setStyleSheet("""
                QLabel {
                    background-color: #5BA8C8;
                    color: #0F172A;
                    border-radius: 14px;
                    padding: 10px 14px;
                    margin: 2px 4px 0px 60px;
                }
            """)
        else:
            self._label.setText(f"\U0001F41F  {text}")
            self._label.setStyleSheet("""
                QLabel {
                    background-color: #2C3E50;
                    color: #ECF0F1;
                    border-radius: 14px;
                    padding: 10px 14px;
                    margin: 2px 60px 0px 4px;
                }
            """)

        layout.addWidget(self._label)

        # Timestamp
        now = datetime.datetime.now().strftime("%H:%M")
        ts = QLabel(now)
        ts.setFont(QFont("Segoe UI", 8))
        align = Qt.AlignmentFlag.AlignRight if is_user else Qt.AlignmentFlag.AlignLeft
        ts.setAlignment(align)
        margin = "margin: 0px 8px 2px 0px;" if is_user else "margin: 0px 0px 2px 8px;"
        ts.setStyleSheet(f"QLabel {{ color: #475569; {margin} background: transparent; padding: 0; }}")
        layout.addWidget(ts)


class TypingIndicator(QLabel):
    """Animated thinking indicator with bubble dots."""

    _FRAMES = [
        "\U0001F41F  \U0001F4AD \u2022",
        "\U0001F41F  \U0001F4AD \u2022\u2022",
        "\U0001F41F  \U0001F4AD \u2022\u2022\u2022",
        "\U0001F41F  \U0001F4AD \u2022\u2022",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Segoe UI", 11))
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self.setStyleSheet("""
            QLabel {
                background-color: #2C3E50;
                color: #7EC8E3;
                border-radius: 14px;
                padding: 10px 14px;
                margin: 2px 60px 2px 4px;
            }
        """)
        self.setText(self._FRAMES[0])
        self.hide()

    def start(self):
        self._frame = 0
        self.setText(self._FRAMES[0])
        self.show()
        self._timer.start(350)

    def stop(self):
        self._timer.stop()
        self.hide()

    def _animate(self):
        self._frame = (self._frame + 1) % len(self._FRAMES)
        self.setText(self._FRAMES[self._frame])


class SystemBubble(QLabel):
    """A small system/action message in the chat (e.g. 'Opened Chrome!')."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setFont(QFont("Segoe UI", 10))
        self.setText(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                color: #7EC8E3;
                font-style: italic;
                padding: 4px 12px;
                margin: 2px 40px;
            }
        """)


class ChatWindow(QDialog):
    """Text-based chat window for messaging Little Fish."""

    def __init__(self, chat_backend, fish_widget, parent=None):
        super().__init__(parent)
        self._chat = chat_backend
        self._fish = fish_widget
        self._waiting_for_reply = False

        # Get fish name from profile
        self._fish_name = "Little Fish"
        if hasattr(fish_widget, '_user_profile') and fish_widget._user_profile:
            self._fish_name = fish_widget._user_profile.fish_name or "Little Fish"

        self.setWindowTitle(f"Chat with {self._fish_name}")
        self.setMinimumSize(380, 480)
        self.resize(420, 600)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog
        )
        self.setStyleSheet(CHAT_STYLE)

        self._build_ui()
        self._chat.response_ready.connect(self._on_response)

        # Periodic header mood update
        self._mood_timer = QTimer(self)
        self._mood_timer.timeout.connect(self._update_mood_label)
        self._mood_timer.start(3000)

        # Load previous conversation into UI
        QTimer.singleShot(100, self._load_history)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(10, 10, 10, 10)

        # ── Header: name + mood + clear button ──
        header_row = QHBoxLayout()
        header = QLabel(f"\U0001F41F {self._fish_name}")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        header.setStyleSheet("color: #7EC8E3; padding: 4px;")
        header_row.addWidget(header)

        self._mood_label = QLabel("")
        self._mood_label.setFont(QFont("Segoe UI", 11))
        self._mood_label.setStyleSheet("color: #94A3B8; padding: 4px;")
        header_row.addWidget(self._mood_label)
        self._update_mood_label()

        header_row.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("clear")
        clear_btn.setFixedWidth(50)
        clear_btn.clicked.connect(self._clear_history)
        header_row.addWidget(clear_btn)
        layout.addLayout(header_row)

        # ── Message area (scrollable) ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet("""
            QScrollArea { background-color: #16213E; border-radius: 10px; }
            QScrollBar:vertical {
                background: #16213E; width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #5BA8C8; border-radius: 4px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setSpacing(4)
        self._msg_layout.setContentsMargins(8, 8, 8, 8)
        self._msg_layout.addStretch()

        # Typing indicator (hidden by default)
        self._typing = TypingIndicator()
        self._msg_layout.addWidget(self._typing)

        self._scroll.setWidget(self._msg_container)
        layout.addWidget(self._scroll, 1)

        # ── Quick action buttons ──
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        for label, cmd in [
            ("\U0001F3AE Games", "play a game"),
            ("\U0001F321\uFE0F Weather", "weather"),
            ("\U0001F4F0 News", "news"),
            ("\U0001F440 Screen", "review my screen"),
            ("\U0001F4CB Cmds", "/commands"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("quick_action")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, c=cmd: self._quick_send(c))
            quick_row.addWidget(btn)
        layout.addLayout(quick_row)

        # ── Input row ──
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message or command...")
        self._input.returnPressed.connect(self._send_message)
        input_row.addWidget(self._input, 1)

        send_btn = QPushButton("\u27A4")
        send_btn.setToolTip("Send")
        send_btn.clicked.connect(self._send_message)
        send_btn.setFixedWidth(44)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #5BA8C8; color: #0F172A;
                border: none; border-radius: 12px; padding: 10px;
                font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #7EC8E3; }
            QPushButton:pressed { background-color: #4A9BB8; }
        """)
        input_row.addWidget(send_btn)

        layout.addLayout(input_row)

    def _update_mood_label(self):
        """Update the mood indicator in the header."""
        if hasattr(self._fish, 'emotions'):
            mood = self._fish.emotions.dominant_emotion()
            icon = EMOTION_ICONS.get(mood, "")
            self._mood_label.setText(f"{icon} {mood}")

    def _quick_send(self, text: str):
        """Send a quick action command directly."""
        self._input.clear()
        self._input.setText(text)
        # Small delay to ensure setText takes effect before reading
        QTimer.singleShot(10, self._send_message)

    def _load_history(self):
        """Load persisted chat history into the UI."""
        history = self._chat._history
        if not history:
            mood = "happy"
            if hasattr(self._fish, 'emotions'):
                mood = self._fish.emotions.dominant_emotion()
            greetings = {
                "happy": "Hey! \U0001F44B I'm in a good mood. What's up?",
                "bored": "Oh, hi! Finally someone to talk to. What's going on?",
                "curious": "Hey! I was just thinking about stuff. Ask me anything!",
                "sleepy": "Oh... hey! *yawns* I'm here, what do you need?",
                "excited": "HI!! \U0001F389 So glad you opened chat! What's happening?",
                "worried": "Hey... I was a bit anxious. Good to see you!",
                "focused": "Oh, chat! Sure, I can multitask. What's up?",
                "frustrated": "Ugh, hey. Maybe chatting will help. What's on your mind?",
                "content": "Hey there \U0001F60A What can I do for you?",
            }
            self._add_fish_message(greetings.get(mood, greetings["happy"]))
            return

        # Show last 20 messages from history
        recent = history[-20:]
        for msg in recent:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                self._add_user_message(content)
            elif role == "assistant":
                self._add_fish_message(content)
        self._scroll_to_bottom()

    def _clear_history(self):
        """Clear chat history and reset the UI."""
        self._chat._history.clear()
        from core.intelligence import save_chat_history
        save_chat_history([])
        # Remove all message bubbles but keep stretch and typing indicator
        while self._msg_layout.count() > 2:  # keep stretch + typing indicator
            item = self._msg_layout.takeAt(0)
            w = item.widget()
            if w and w is not self._typing:
                w.deleteLater()
            elif w is self._typing:
                # Put it back
                self._msg_layout.addWidget(self._typing)
                break
        self._add_fish_message("Fresh start! What's up?")

    def _send_message(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()

        # Built-in slash commands
        if text.lower() == "/commands":
            self._add_user_message(text)
            self._show_commands_list()
            return
        if text.lower() == "/features":
            self._add_user_message(text)
            self._show_features_list()
            return
        if text.lower() == "/help":
            self._add_user_message(text)
            self._add_fish_message(
                "Type /commands to see all commands.\n"
                "Type /features to see all features.\n"
                "Or just talk to me!"
            )
            return

        self._add_user_message(text)

        from widget.animator import ReactionType

        # Wake up fish if sleepy (even if not dominant — could be visually sleeping)
        sleepy_val = self._fish.emotions.values.get("sleepy", 0)
        if sleepy_val > 0.4 or self._fish.emotions.dominant_emotion() == "sleepy":
            self._fish.emotions.wake_up()
            self._fish.animator.queue_reaction(ReactionType.BOUNCE)
            if sleepy_val > 0.5:
                self._add_system_bubble("* wakes up *")

        # Try fast regex commands only (no AI classifier — the chat
        # backend handles everything else, avoids a redundant Groq call).
        import re as _re
        _CHAT_PASSTHROUGH = {"greeting", "status", "confirm_yes", "pin"}
        clean = text.strip().lower()
        result = None
        # Check custom name patterns (wake words etc.)
        for pattern, handler in self._fish._cmd_parser._extra_patterns:
            m = _re.search(pattern, clean, _re.IGNORECASE)
            if m:
                result = handler(m)
                break
        if result is None:
            result = self._fish._cmd_parser._fast_parse(clean)
        if result is not None and result.action not in _CHAT_PASSTHROUGH:
            self._persist_to_history("user", text)
            self._fish._execute_command(result)
            return

        # No command matched — send to AI chat
        self._chat.send(text)
        self._waiting_for_reply = True
        self._typing.start()
        self._scroll_to_bottom()

        # Update fish emotions — conversation keeps fish awake and engaged
        self._fish.emotions.spike("curious", 0.15)
        self._fish.emotions.on_conversation()
        self._fish.animator.queue_reaction(ReactionType.NOD)
        self._fish._last_interaction_time = time.monotonic()
        self._fish._behavior_engine.record_interaction()

    def _on_response(self, text: str):
        """Called when chat backend generates a response."""
        self._typing.stop()
        self._waiting_for_reply = False
        # Message is already synced by FishWidget._on_chat_response -> _say -> _sync_to_chat

    def _persist_to_history(self, role: str, text: str):
        """Add a message to AI chat history so follow-ups have context."""
        from core.intelligence import save_chat_history
        hist = self._chat._history
        if not hist or hist[-1].get("content") != text:
            hist.append({"role": role, "content": text})
        # Trim to keep history manageable
        if len(hist) > 20:
            self._chat._history = hist[-20:]
            hist = self._chat._history
        save_chat_history(hist)

    def _add_user_message(self, text: str):
        bubble = MessageBubble(text, is_user=True, fish_name=self._fish_name)
        # Insert before the typing indicator (which is always last before the stretch)
        idx = self._msg_layout.indexOf(self._typing)
        self._msg_layout.insertWidget(idx, bubble)
        self._scroll_to_bottom()

    def _add_fish_message(self, text: str):
        bubble = MessageBubble(text, is_user=False, fish_name=self._fish_name)
        idx = self._msg_layout.indexOf(self._typing)
        self._msg_layout.insertWidget(idx, bubble)
        self._scroll_to_bottom()

    def _add_system_bubble(self, text: str):
        bubble = SystemBubble(text)
        idx = self._msg_layout.indexOf(self._typing)
        self._msg_layout.insertWidget(idx, bubble)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Prevent QDialog from closing on Enter — let QLineEdit handle it
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # /commands and /features
    # ------------------------------------------------------------------

    def _show_commands_list(self):
        commands_text = (
            "All commands (chat & voice):\n\n"
            "Apps & Browser:\n"
            "  open [app/website]\n"
            "  close [app]\n"
            "  search [query]\n"
            "  go to [url]\n\n"
            "System:\n"
            "  volume up/down\n"
            "  set volume to [n]%\n"
            "  brightness up/down\n"
            "  mute / unmute\n"
            "  lock screen\n"
            "  show desktop\n"
            "  open task manager\n"
            "  kill [process]\n"
            "  check disk space\n"
            "  toggle wifi/bluetooth\n"
            "  system status\n"
            "  top processes\n"
            "  session time\n"
            "  shutdown / restart\n\n"
            "Productivity:\n"
            "  set timer for [n] min/sec\n"
            "  remind me in [n] min to [msg]\n"
            "  pomodoro\n"
            "  add todo [task]\n"
            "  show todos\n"
            "  done with [task]\n"
            "  remove [task]\n"
            "  briefing / summary\n\n"
            "Fish:\n"
            "  come here\n"
            "  go away / hide\n"
            "  take a break / rest\n"
            "  follow me / stop following\n"
            "  how are you\n\n"
            "Info & Web:\n"
            "  weather [city]\n"
            "  forecast [city]\n"
            "  news / headlines\n"
            "  wikipedia [topic]\n"
            "  define [word]\n"
            "  translate [text] to [lang]\n"
            "  exchange rate [from] to [to]\n"
            "  sunrise / sunset\n"
            "  is it a holiday\n\n"
            "Fun:\n"
            "  tell me a joke\n"
            "  flip a coin\n"
            "  roll a dice\n"
            "  random number\n"
            "  roast me\n"
            "  motivate me\n"
            "  play a game\n"
            "  high scores\n\n"
            "AI:\n"
            "  explain [concept]\n"
            "  summarize [text]\n"
            "  brainstorm [topic]\n"
            "  proofread [text]\n"
            "  draft email about [topic]\n"
            "  quiz me on [topic]\n\n"
            "Media:\n"
            "  play / pause\n"
            "  next track / previous track\n"
            "  what's playing\n"
            "  mute/unmute mic\n\n"
            "Files:\n"
            "  read clipboard\n"
            "  save clipboard\n"
            "  clear clipboard\n"
            "  find file [name]\n"
            "  open downloads/desktop/documents\n\n"
            "Chat:\n"
            "  /commands — this list\n"
            "  /features — all features\n"
            "  /help — quick help"
        )
        self._add_fish_message(commands_text)

    def _show_features_list(self):
        features_text = (
            "Little Fish Features:\n\n"
            "Desktop Companion:\n"
            "  • Pixel-art fish that lives on your desktop\n"
            "  • Drag, flick, pet, and interact with physics\n"
            "  • Smooth walk-to movement\n"
            "  • Emotional reactions (happy, curious, sleepy...)\n"
            "  • Breathing, blinking, idle animations\n"
            "  • Particle effects (hearts, sparkles, zzz...)\n\n"
            "Customization:\n"
            "  • Body color picker + skin presets\n"
            "  • Eye & mouth styles\n"
            "  • 12 hats (top hat, crown, wizard...)\n"
            "  • Tail styles (fan, spike, ribbon)\n"
            "  • Size, opacity, dark border, glow, shadow\n"
            "  • Custom name\n\n"
            "AI Chat:\n"
            "  • Groq-powered AI conversations\n"
            "  • 100+ voice/text commands\n"
            "  • Proofreading, summarizing, brainstorming\n"
            "  • Voice recognition (push-to-talk or VAD)\n"
            "  • Text-to-speech responses\n\n"
            "Smart Features:\n"
            "  • Companion mode (follows cursor)\n"
            "  • App awareness (reacts to programs)\n"
            "  • Clipboard reactions\n"
            "  • Morning briefing\n"
            "  • Todo list\n"
            "  • Timers & reminders\n"
            "  • Jokes & fun facts\n\n"
            "Games:\n"
            "  • Catch & Snack, Whack-a-Bubble, Flappy Swim\n\n"
            "System Control:\n"
            "  • Volume, brightness, screenshots\n"
            "  • Open/close apps, lock screen\n"
            "  • Process management\n"
            "  • Disk space, wifi, bluetooth\n\n"
            "Web APIs:\n"
            "  • Weather & forecasts\n"
            "  • News headlines\n"
            "  • Wikipedia lookups\n"
            "  • Dictionary, translations\n"
            "  • Exchange rates, holidays\n\n"
            "Personality:\n"
            "  • Autonomous idle behaviors\n"
            "  • Mood system (9 emotions)\n"
            "  • Keyboard awareness (Ctrl+Z, Ctrl+S)\n"
            "  • File drop reactions\n"
            "  • Seasonal costumes & events\n"
            "  • Unprompted thoughts & comments"
        )
        self._add_fish_message(features_text)
