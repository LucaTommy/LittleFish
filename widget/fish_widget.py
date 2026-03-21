"""
Main Little Fish widget — frameless, transparent, always-on-top.
Handles dragging, edge resistance, pixel-art scaling, context menu, settings.
"""

import json
import math
import time
import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QPoint, QUrl
from PyQt6.QtGui import (
    QPainter, QIcon, QPixmap, QColor, QPen, QBrush, QPainterPath, QCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QApplication, QMenu, QSystemTrayIcon,
)

from widget.animator import Animator, ReactionType
from widget.renderer import FishRenderer, PIXEL_CANVAS, PIXEL_BODY
from core.emotion_engine import EmotionEngine
from core.system_monitor import SystemMonitor
from core.personality import load_personality
from core.voice import VoiceRecorder
from core.command_parser import CommandParser
from core.tts import TTS
from core.chat import FishChat
from core.screen_review import ScreenReviewer
from widget.chat_bubble import ChatBubble
from games import GAME_LIST
from games.game_manager import _load_scores
from core.shared_state import SharedState
from core.intelligence import (
    ScheduleTracker, TodoList, analyze_clipboard,
    generate_morning_briefing, get_random_joke_or_fact,
)
from core.app_reactions import AppReactions
from core.behavior_engine import BehaviorEngine
from core.user_profile import UserProfile
from core.relationship import Relationship
from core.movement_engine import MovementEngine, MovementState


FRAME_INTERVAL_MS = 16             # ~60fps
EDGE_RESISTANCE_MARGIN = 40
EDGE_RESISTANCE_STRENGTH = 0.55

from config import CONFIG_PATH, get_groq_keys

UNPROMPTED_PHRASES = [
    "I wonder what's for lunch...",
    "Hey, you doing okay?",
    "I like just hanging out here.",
    "*yawns*",
    "Did you know fish can recognize faces?",
    "What are we working on?",
    "You've been at it for a while — maybe a stretch?",
    "Bloop bloop!",
    "Sometimes I dream about the ocean...",
    "You're doing great, just so you know.",
    "I think I saw a bug... no wait, that's a pixel.",
    "Wonder what the weather's like outside...",
    "*hums quietly*",
    "This is nice. Just us.",
    "I bet you didn't know I could wink. Watch!",
]


class FishWidget(QWidget):
    def __init__(self):
        super().__init__()

        # --- Load config ---
        self._config = self._load_config()
        self._settings_dialog = None

        # --- Display sizing ---
        appearance = self._config.get("appearance", {})
        self._display_size = appearance.get("size", 80)
        self._display_scale = self._display_size / PIXEL_BODY

        # --- Window flags ---
        self._apply_window_flags()
        self._apply_widget_size()

        # --- Position (with on-screen validation) ---
        pos = appearance.get("position", [100, 100])
        self.move(int(pos[0]), int(pos[1]))
        self._ensure_on_screen()

        # --- Opacity ---
        self.setWindowOpacity(appearance.get("opacity", 1.0))

        # --- Core objects ---
        self.animator = Animator()
        self.renderer = FishRenderer()

        # --- User profile & Relationship ---
        self._user_profile = UserProfile()
        self._relationship = Relationship()

        # --- Emotion engine ---
        personality = load_personality(self._config)
        self.emotions = EmotionEngine(personality, user_profile=self._user_profile)

        # --- System monitor (background thread) ---
        self._monitor = SystemMonitor()
        self._connect_monitor_signals()
        if self._config.get("permissions", {}).get("system_monitor", True):
            self._monitor.start()

        # --- Voice / Commands / TTS ---
        groq_keys = get_groq_keys()
        self._voice = VoiceRecorder(self._config, fish_name=self._user_profile.fish_name)
        self._voice.transcription_ready.connect(self._on_transcription)
        self._voice.listening_started.connect(self._on_listening_started)
        self._voice.listening_stopped.connect(self._on_listening_stopped)
        self._voice.error_occurred.connect(self._on_voice_error)
        self._voice.compliment_detected.connect(self._on_compliment)
        self._voice.insult_detected.connect(self._on_insult)
        self._voice.name_called.connect(self._on_name_called)
        self._voice.whisper_detected.connect(self._on_whisper)
        self._voice.singing_detected.connect(self._on_singing)
        self._voice.mic_spike.connect(self._on_mic_spike)

        self._cmd_parser = CommandParser(groq_keys=groq_keys, fish_name=self._user_profile.fish_name)
        self._tts = TTS(self._config)

        self._chat = FishChat(
            groq_keys,
            emotion_getter=lambda: self.emotions.dominant_emotion(),
            user_profile=self._user_profile,
            relationship=self._relationship,
        )
        self._chat.set_context_getter(self._get_chat_context)
        self._chat.response_ready.connect(self._on_chat_response)
        self._chat.error_occurred.connect(lambda e: self._say("I can't think right now..."))

        self._reviewer = ScreenReviewer(groq_keys)
        self._reviewer.review_ready.connect(self._on_review_ready)
        self._reviewer.peek_ready.connect(self._on_peek_ready)
        self._reviewer.error_occurred.connect(lambda e: self._say(str(e)))
        self._review_focus: str | None = None

        self._bubble = ChatBubble()

        # Start VAD if enabled
        if self._config.get("voice", {}).get("always_listening", False):
            self._voice.start_vad()

        self._voice_enabled = self._config.get("permissions", {}).get("microphone", True)

        # --- Timer / Reminder / Power ---
        self._active_timers: list = []
        self._pending_power: str | None = None
        self._custom_name: str = ""

        # --- Interaction tracking ---
        self._last_interaction_time = time.monotonic()
        self._session_start = time.monotonic()
        self._command_count: int = 0
        self._last_break_time: float = time.monotonic()
        self._gaze_x: float = 0.0
        self._gaze_y: float = 0.0
        self._last_click_time: float = 0.0
        self._click_count: int = 0
        self._quiet_mode: bool = False
        self._quiet_mode_until: float = 0.0

        # --- Phase 4: Talking mouth timer ---
        self._talk_timer = QTimer(self)
        self._talk_timer.setInterval(150)  # mouth open/close toggle rate
        self._talk_timer.timeout.connect(self._on_talk_tick)

        # --- Phase 4: Particle spawn timer ---
        self._particle_timer = QTimer(self)
        self._particle_timer.setInterval(1500)  # check every 1.5s
        self._particle_timer.timeout.connect(self._maybe_spawn_particle)
        self._particle_timer.start()

        # --- Phase 4: Idle behavior timer ---
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(6000)  # every 6 seconds
        self._idle_timer.timeout.connect(self._idle_behavior)
        self._idle_timer.start()

        # --- Unprompted speech timer (profile-aware interval) ---
        import random as _rng
        self._unprompted_timer = QTimer(self)
        self._unprompted_timer.setInterval(self._calc_unprompted_interval())
        self._unprompted_timer.timeout.connect(self._unprompted_thought)
        self._unprompted_timer.start()

        # --- Shared state (for launcher) ---
        self._shared_state = SharedState()
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(10000)  # write state every 10s
        self._state_timer.timeout.connect(self._write_shared_state)
        self._state_timer.start()

        self._mood_log_timer = QTimer(self)
        self._mood_log_timer.setInterval(3600000)  # mood log every hour
        self._mood_log_timer.timeout.connect(self._log_mood)
        self._mood_log_timer.start()

        # --- Posture reminder (every 2 hours) ---
        self._posture_timer = QTimer(self)
        self._posture_timer.setInterval(7200000)  # 2 hours
        self._posture_timer.timeout.connect(self._posture_reminder)
        self._posture_timer.start()

        # --- Clipboard monitoring (main thread, safe on Windows) ---
        self._last_clip_text: str = ""
        self._clip_timer = QTimer(self)
        self._clip_timer.setInterval(3000)  # every 3s
        self._clip_timer.timeout.connect(self._poll_clipboard)
        self._clip_timer.start()

        # --- Intelligence ---
        self._schedule_tracker = ScheduleTracker()
        self._todo_list = TodoList()
        self._companion_mode = False
        self._clipboard_reactions = False
        self._app_awareness = False
        self._todo_enabled = False
        self._briefing_enabled = False
        self._jokes_enabled = False
        self._briefing_given_today = False
        self._last_app_reaction = ""
        self._app_reactor = AppReactions()
        self._music_playing = False
        self._chat_window = None
        # Eagerly create chat window (hidden) so all messages route there
        from widget.chat_window import ChatWindow
        self._chat_window = ChatWindow(self._chat, self)

        # Jokes/fact timer (every 30-60 min)
        self._joke_timer = QTimer(self)
        self._joke_timer.setInterval(_rng.randint(1800000, 3600000))
        self._joke_timer.timeout.connect(self._maybe_tell_joke)
        self._joke_timer.start()

        # App awareness timer (every 5 seconds)
        self._app_awareness_timer = QTimer(self)
        self._app_awareness_timer.setInterval(5000)
        self._app_awareness_timer.timeout.connect(self._check_app_awareness)
        self._app_awareness_timer.start()

        # --- Behavior engine ---
        self._behavior_engine = BehaviorEngine(
            emotion_getter=lambda: self.emotions.dominant_emotion(),
            monitor=self._monitor,
            user_profile=self._user_profile,
            relationship=self._relationship,
            emotion_engine=self.emotions,
        )
        self._behavior_engine.behavior_triggered.connect(self._on_behavior)
        self._monitor.active_app_changed.connect(self._behavior_engine.set_active_app)
        if self._config.get("intelligence", {}).get("autonomous_behavior", True):
            self._behavior_engine.start()

        # --- Drag state ---
        self._drag_offset = QPoint()
        self._is_dragging = False
        self._was_dragged = False

        # --- Flick momentum ---
        self._drag_positions: list[tuple[float, int, int]] = []  # (time, x, y)
        self._momentum_vx: float = 0.0
        self._momentum_vy: float = 0.0
        self._momentum_timer = QTimer(self)
        self._momentum_timer.setInterval(16)  # ~60fps
        self._momentum_timer.timeout.connect(self._tick_momentum)

        # --- Long press detection ---
        self._press_start_time: float = 0.0
        self._press_start_pos = QPoint()
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(2000)
        self._long_press_timer.timeout.connect(self._on_long_press)
        self._long_press_triggered = False

        # --- Pet detection (slow mouse movement) ---
        self._pet_positions: list[tuple[float, int, int]] = []

        # --- Shake detection (rapid direction changes during drag) ---
        self._drag_directions: list[tuple[float, int]] = []  # (time, x_direction +1/-1)

        # --- Walk-to animation (smooth movement instead of teleporting) ---
        self._walk_target_x: float | None = None
        self._walk_target_y: float | None = None
        self._walk_speed: float = 600.0  # pixels per second
        self._walk_timer = QTimer(self)
        self._walk_timer.setInterval(16)  # ~60fps
        self._walk_timer.timeout.connect(self._tick_walk)

        # --- Movement engine (emotion-driven autonomous movement) ---
        self._movement = MovementEngine(self, self.emotions)

        # --- Timing ---
        self._last_frame_time = time.monotonic()

        # --- Render loop ---
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(FRAME_INTERVAL_MS)

        # --- Context menu ---
        self._build_context_menu()

        # --- Tray icon ---
        self._build_tray_icon()

        # --- Apply saved config to renderer + intelligence flags ---
        self.apply_config()

        # --- Accept file drops ---
        self.setAcceptDrops(True)

        # --- Global keyboard shortcut monitor ---
        self._kb_timer = QTimer(self)
        self._kb_timer.setInterval(200)
        self._kb_timer.timeout.connect(self._poll_keyboard)
        self._kb_timer.start()
        self._prev_key_states: dict[int, bool] = {}
        self._review_shortcut_keys = (0x11, 0x10, 0x46)  # Ctrl, Shift, F

        # --- Periodic visibility check (prevent disappearing) ---
        self._visibility_timer = QTimer(self)
        self._visibility_timer.setInterval(30000)  # every 30 seconds
        self._visibility_timer.timeout.connect(self._check_visibility)
        self._visibility_timer.start()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"appearance": {"size": 80, "opacity": 1.0,
                                   "position": [100, 100], "always_on_top": True}}

    def _save_config(self):
        """Persist settings to settings.json, preserving user-edited values."""
        pos = self.pos()
        self._config.setdefault("appearance", {})["position"] = [pos.x(), pos.y()]
        try:
            # Read existing file to preserve user-edited keys
            existing = {}
            if CONFIG_PATH.exists():
                try:
                    existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass

            # Deep merge: app-managed keys win, but preserve disk values
            # the app never touches
            merged = dict(existing)
            for k, v in self._config.items():
                if isinstance(v, dict) and isinstance(existing.get(k), dict):
                    merged[k] = dict(existing[k])
                    merged[k].update(v)
                    continue
                merged[k] = v

            CONFIG_PATH.write_text(
                json.dumps(merged, indent=2),
                encoding="utf-8",
            )
            # Keep in-memory config in sync (update in-place to
            # preserve the shared reference held by SettingsDialog)
            self._config.clear()
            self._config.update(merged)
        except OSError:
            pass

    def apply_config(self):
        """Re-read config dict and update widget properties live."""
        appearance = self._config.get("appearance", {})
        self._display_size = appearance.get("size", 80)
        self._display_scale = self._display_size / PIXEL_BODY
        self._apply_widget_size()
        self.setWindowOpacity(appearance.get("opacity", 1.0))

        on_top = appearance.get("always_on_top", True)
        current_on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if on_top != current_on_top:
            self._apply_window_flags()
            self.show()

        # Skin preset (applies body color from preset)
        skin = appearance.get("skin_preset", "")
        if skin and skin in self.renderer.SKIN_PRESETS:
            self.renderer.apply_skin_preset(skin)
        else:
            body_color = appearance.get("body_color", "")
            if body_color:
                self.renderer.set_body_color(body_color)

        # Appearance → renderer
        self.renderer._eye_style = appearance.get("eye_style", "default")
        self.renderer._mouth_style = appearance.get("mouth_style", "default")
        self.renderer._dark_border = appearance.get("dark_border", False)
        self.renderer._glow_enabled = appearance.get("glow_enabled", False)
        self.renderer._sparkle_eyes = appearance.get("sparkle_eyes", False)
        self.renderer._shadow_enabled = appearance.get("shadow", False)
        self.renderer._hat = appearance.get("hat", "")
        self.renderer._tail_style = appearance.get("tail_style", "")
        self.renderer._skin_preset = appearance.get("skin_preset", "")

        # Custom name
        self._custom_name = appearance.get("custom_name", "")
        self.renderer._custom_name = self._custom_name
        self.renderer._show_name = bool(self._custom_name)

        # Intelligence settings
        intelligence = self._config.get("intelligence", {})
        self._companion_mode = intelligence.get("companion_mode", False)
        self._clipboard_reactions = intelligence.get("clipboard_reactions", False)
        self._app_awareness = intelligence.get("app_awareness", False)
        self._todo_enabled = intelligence.get("todo_list", False)
        self._briefing_enabled = intelligence.get("morning_briefing", False)
        self._jokes_enabled = intelligence.get("jokes", False)

        # Behavior engine
        auto_beh = intelligence.get("autonomous_behavior", True)
        self._behavior_engine.set_enabled(auto_beh)

    def _apply_window_flags(self):
        on_top = self._config.get("appearance", {}).get("always_on_top", True)
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _apply_widget_size(self):
        # Scale factor: display_size maps to PIXEL_BODY (24px internal).
        # Add 30% headroom for costume hats and particles that overflow.
        side = max(int(self._display_size * 1.3), 16)
        self.setFixedSize(side, side)

    # ------------------------------------------------------------------
    # Render loop
    # ------------------------------------------------------------------

    def _on_tick(self):
        now = time.monotonic()
        dt = now - self._last_frame_time
        self._last_frame_time = now

        # Emotion tick
        self.emotions.update(dt)
        face = self.emotions.dominant_emotion()
        self.animator.set_face(face)

        # Eye tracking — smooth analog cursor tracking
        cursor_pos = QCursor.pos()
        fish_center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        dx = cursor_pos.x() - fish_center.x()
        dy = cursor_pos.y() - fish_center.y()
        max_dist = 300.0
        target_gx = max(-1.0, min(1.0, dx / max_dist))
        target_gy = max(-1.0, min(1.0, dy / max_dist))
        # Smooth interpolation for natural feel
        self._gaze_x += (target_gx - self._gaze_x) * 0.12
        self._gaze_y += (target_gy - self._gaze_y) * 0.12
        # Combine cursor gaze with idle look-around from animator
        final_gx = max(-1.0, min(1.0, self._gaze_x + self.animator.idle_gaze_x))
        final_gy = max(-1.0, min(1.0, self._gaze_y + self.animator.idle_gaze_y))
        self.renderer.set_gaze(final_gx, final_gy)

        # VS Code quiet mode timeout
        if self._quiet_mode and time.monotonic() > self._quiet_mode_until:
            self._quiet_mode = False

        # Talking mouth sync
        self.renderer.set_talking(self._tts.is_speaking)
        if self._tts.is_speaking and not self._talk_timer.isActive():
            self._talk_timer.start()
        elif not self._tts.is_speaking and self._talk_timer.isActive():
            self._talk_timer.stop()

        # Emotion-driven movement (skip during drag, momentum, forced walk)
        if (not self._is_dragging
                and not self._momentum_timer.isActive()
                and not self._walk_timer.isActive()):
            prev_ms = self._movement.state
            self._movement.update(dt)
            new_ms = self._movement.state
            if new_ms != prev_ms:
                self._on_movement_state_changed(prev_ms, new_ms)

        self.animator.update(dt)
        self.update()  # schedules paintEvent

        # Keep chat bubble anchored to the fish
        if self._bubble._showing:
            anchor = self.mapToGlobal(QPoint(self.width() // 2, 0))
            self._bubble.update_anchor(anchor)

        # Companion mode: drift toward cursor (disabled when movement engine active)
        if not self._movement.is_moving:
            self._companion_follow_cursor()

    def _on_talk_tick(self):
        """Toggle mouth frame for talking animation."""
        self.renderer.advance_talk_frame()

    def paintEvent(self, event):
        painter = QPainter(self)

        # Clear previous frame — fixes ghosting/duplication on drag
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Get pixel-art pixmap at internal resolution
        seasonal = self.emotions.get_seasonal_event()
        pixmap = self.renderer.render_pixmap(self.animator, seasonal_event=seasonal)

        # Nearest-neighbor scaling — crisp pixel art
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # Apply transforms: breathing, reactions, then scale to display
        center = self.width() / 2.0
        painter.translate(center + self.animator.offset_x,
                          center + self.animator.offset_y)
        painter.rotate(self.animator.rotation)
        scale = self.animator.scale * self._display_scale
        painter.scale(scale, scale)
        painter.translate(-PIXEL_CANVAS / 2.0, -PIXEL_CANVAS / 2.0)

        painter.drawPixmap(0, 0, pixmap)
        painter.end()

    # ------------------------------------------------------------------
    # Mouse / drag
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            now = time.monotonic()
            # Double-click / rapid-click detection
            if now - self._last_click_time < 0.4:
                self._click_count += 1
                if self._click_count == 2:
                    self._start_screen_review()
                    self.animator.trigger_double_blink()
                    self.emotions.spike("excited", 0.4)
                    self.animator.spawn_particle("exclamation")
                elif self._click_count >= 4:
                    # Dizzy from rapid clicking
                    self.emotions.spike("worried", 0.3)
                    self.animator.queue_reaction(ReactionType.DIZZY)
                    self.animator.spawn_particle("spiral")
                    self._click_count = 0
            else:
                self._click_count = 1
            self._last_click_time = now
            self._last_interaction_time = now

            self._drag_offset = event.position().toPoint()
            self._is_dragging = True
            self._was_dragged = False
            self._stop_walk()  # Cancel any walk animation on drag
            self._movement.pause(999.0)  # Pause movement engine during drag
            self.animator.is_dragging = True
            self.animator.queue_reaction(ReactionType.FLINCH)
            self.emotions.on_fish_clicked()
            self._monitor.notify_input()
            self._shared_state.record_interaction()

            # Flick tracking reset
            gpos = event.globalPosition().toPoint()
            self._drag_positions = [(now, gpos.x(), gpos.y())]
            self._momentum_timer.stop()
            self._momentum_vx = 0.0
            self._momentum_vy = 0.0

            # Long press start
            self._press_start_time = now
            self._press_start_pos = gpos
            self._long_press_triggered = False
            self._long_press_timer.start()

            # Shake detection reset
            self._drag_directions = []

    def mouseMoveEvent(self, event):
        if self._is_dragging:
            raw_pos = event.globalPosition().toPoint() - self._drag_offset
            softened = self._apply_edge_resistance(raw_pos)
            self.move(softened)
            if not self._was_dragged:
                self._was_dragged = True
                self.animator.queue_reaction(ReactionType.WIGGLE)
                # Cancel long press if moved significantly
                self._long_press_timer.stop()

            # Track positions for flick velocity
            now = time.monotonic()
            gpos = event.globalPosition().toPoint()
            self._drag_positions.append((now, gpos.x(), gpos.y()))
            # Keep only last 100ms of positions
            self._drag_positions = [(t, x, y) for t, x, y in self._drag_positions
                                     if now - t < 0.10]

            # Shake detection: track direction changes
            if len(self._drag_positions) >= 2:
                dx = gpos.x() - self._drag_positions[-2][1]
                if dx != 0:
                    direction = 1 if dx > 0 else -1
                    if not self._drag_directions or self._drag_directions[-1][1] != direction:
                        self._drag_directions.append((now, direction))
                    # Keep only last 1s of direction changes
                    self._drag_directions = [(t, d) for t, d in self._drag_directions
                                              if now - t < 1.0]
                    # 5+ direction changes in 1s = shake
                    if len(self._drag_directions) >= 5:
                        self._on_shake_detected()
                        self._drag_directions = []

        else:
            # Pet detection: slow mouse movement over the fish (not dragging)
            now = time.monotonic()
            gpos = event.globalPosition().toPoint()
            self._pet_positions.append((now, gpos.x(), gpos.y()))
            # Keep last 0.8s
            self._pet_positions = [(t, x, y) for t, x, y in self._pet_positions
                                    if now - t < 0.8]
            if len(self._pet_positions) >= 4:
                total_dist = 0.0
                for i in range(1, len(self._pet_positions)):
                    dx = self._pet_positions[i][1] - self._pet_positions[i - 1][1]
                    dy = self._pet_positions[i][2] - self._pet_positions[i - 1][2]
                    total_dist += math.sqrt(dx * dx + dy * dy)
                elapsed = self._pet_positions[-1][0] - self._pet_positions[0][0]
                if elapsed > 0.3:
                    speed = total_dist / elapsed
                    # Slow enough to be a pet, but actually moving
                    if 15 < speed < 200:
                        self._on_pet_detected()
                        self._pet_positions = []

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            self.animator.is_dragging = False
            self._long_press_timer.stop()

            if self._was_dragged and not self._long_press_triggered:
                # Calculate flick velocity from position history
                now = time.monotonic()
                recent = [(t, x, y) for t, x, y in self._drag_positions if now - t < 0.08]
                if len(recent) >= 2:
                    dt = recent[-1][0] - recent[0][0]
                    if dt > 0.005:
                        vx = (recent[-1][1] - recent[0][1]) / dt
                        vy = (recent[-1][2] - recent[0][2]) / dt
                        speed = math.sqrt(vx * vx + vy * vy)
                        if speed > 600:
                            # Fast flick — apply momentum (engine stays paused)
                            self._momentum_vx = vx * 0.6
                            self._momentum_vy = vy * 0.6
                            self._momentum_timer.start()
                            self.emotions.spike("worried", 0.2)
                        else:
                            self.animator.queue_reaction(ReactionType.BOUNCE)
                            self._movement.resume()
                else:
                    self.animator.queue_reaction(ReactionType.BOUNCE)
                    self._movement.resume()
            else:
                self._movement.resume()
            self._save_config()

    # ------------------------------------------------------------------
    # On-screen validation
    # ------------------------------------------------------------------

    def _ensure_on_screen(self):
        """Make sure the fish is within visible screen bounds."""
        from PyQt6.QtWidgets import QApplication
        p = self.pos()
        w, h = self.width(), self.height()
        for scr in QApplication.screens():
            geom = scr.availableGeometry()
            # Fish is on-screen if at least half of it overlaps any screen
            if (p.x() + w // 2 > geom.left() and p.x() + w // 2 < geom.right()
                    and p.y() + h // 2 > geom.top() and p.y() + h // 2 < geom.bottom()):
                return  # visible — nothing to do
        # Not visible on any screen — move to primary screen center
        primary = QApplication.primaryScreen()
        if primary:
            geom = primary.availableGeometry()
            self.move(geom.center().x() - w // 2, geom.center().y() - h // 2)
            self._save_config()

    def _check_visibility(self):
        """Periodic check — if the fish is hidden or off-screen, bring it back."""
        if not self.isVisible():
            self.show()
            self.raise_()
        self._ensure_on_screen()

    # ------------------------------------------------------------------
    # Soft edge resistance
    # ------------------------------------------------------------------

    def _apply_edge_resistance(self, pos: QPoint) -> QPoint:
        screen = self.screen()
        if screen is None:
            return pos

        geom = screen.availableGeometry()
        w = self.width()
        h = self.height()
        x = self._soften_axis(pos.x(), geom.left() - w + EDGE_RESISTANCE_MARGIN,
                              geom.right() - EDGE_RESISTANCE_MARGIN)
        y = self._soften_axis(pos.y(), geom.top() - h + EDGE_RESISTANCE_MARGIN,
                              geom.bottom() - EDGE_RESISTANCE_MARGIN)
        return QPoint(int(x), int(y))

    @staticmethod
    def _soften_axis(val: float, low: float, high: float) -> float:
        margin = EDGE_RESISTANCE_MARGIN
        if val < low + margin:
            over = (low + margin) - val
            val = (low + margin) - over * EDGE_RESISTANCE_STRENGTH
        elif val > high - margin:
            over = val - (high - margin)
            val = (high - margin) + over * EDGE_RESISTANCE_STRENGTH
        return val

    # ------------------------------------------------------------------
    # Flick momentum + edge collision
    # ------------------------------------------------------------------

    def _walk_to(self, x: int, y: int, speed: float = 600.0):
        """Smoothly walk to (x, y) instead of teleporting, clamped to screen."""
        self._movement.pause(30.0)  # Yield to forced walk
        # Clamp target to screen bounds to prevent walking off-screen
        screen = self.screen()
        if screen:
            geom = screen.availableGeometry()
            x = max(geom.left(), min(x, geom.right() - self.width()))
            y = max(geom.top(), min(y, geom.bottom() - self.height()))
        self._walk_target_x = float(x)
        self._walk_target_y = float(y)
        self._walk_speed = speed
        if not self._walk_timer.isActive():
            self._walk_timer.start()

    def _tick_walk(self):
        """Animate smooth walking toward target position."""
        if self._walk_target_x is None or self._walk_target_y is None:
            self._walk_timer.stop()
            return
        pos = self.pos()
        dx = self._walk_target_x - pos.x()
        dy = self._walk_target_y - pos.y()
        dist = math.sqrt(dx * dx + dy * dy)
        step = self._walk_speed * 0.016  # ~16ms per tick
        if dist <= step:
            self.move(int(self._walk_target_x), int(self._walk_target_y))
            self._walk_target_x = None
            self._walk_target_y = None
            self._walk_timer.stop()
            self._movement.resume()
            self._save_config()
            return
        ratio = step / dist
        nx = pos.x() + dx * ratio
        ny = pos.y() + dy * ratio
        self.move(int(nx), int(ny))

    def _stop_walk(self):
        """Cancel any in-progress walk animation."""
        self._walk_target_x = None
        self._walk_target_y = None
        self._walk_timer.stop()

    def _tick_momentum(self):
        """Animate momentum after a flick release."""
        if abs(self._momentum_vx) < 5 and abs(self._momentum_vy) < 5:
            self._momentum_timer.stop()
            self._movement.resume()
            return

        dt = 0.016  # ~60fps
        friction = 0.92
        pos = self.pos()
        nx = pos.x() + self._momentum_vx * dt
        ny = pos.y() + self._momentum_vy * dt

        # Edge collision
        screen = self.screen()
        if screen:
            geom = screen.availableGeometry()
            hit_edge = False
            if nx < geom.left():
                nx = float(geom.left())
                self._momentum_vx = -self._momentum_vx * 0.4
                hit_edge = True
                self.animator.queue_reaction(ReactionType.SQUISH_H)
            elif nx > geom.right() - self.width():
                nx = float(geom.right() - self.width())
                self._momentum_vx = -self._momentum_vx * 0.4
                hit_edge = True
                self.animator.queue_reaction(ReactionType.SQUISH_H)
            if ny < geom.top():
                ny = float(geom.top())
                self._momentum_vy = -self._momentum_vy * 0.4
                hit_edge = True
                self.animator.queue_reaction(ReactionType.SQUISH_V)
            elif ny > geom.bottom() - self.height():
                ny = float(geom.bottom() - self.height())
                self._momentum_vy = -self._momentum_vy * 0.4
                hit_edge = True
                self.animator.queue_reaction(ReactionType.SQUISH_V)

            if hit_edge:
                self.animator.spawn_particle("stars")
                # Dust poof on landing
                for _ in range(3):
                    self.animator.spawn_particle("dust")
                self.emotions.spike("worried", 0.3)
                self.emotions.on_negative_interaction()

        self.move(int(nx), int(ny))
        self._momentum_vx *= friction
        self._momentum_vy *= friction

    # ------------------------------------------------------------------
    # Long press
    # ------------------------------------------------------------------

    def _on_long_press(self):
        """Triggered after 2s hold without moving."""
        self._long_press_triggered = True
        self.emotions.spike("curious", 0.3)
        self.animator.queue_reaction(ReactionType.WIGGLE)
        self._say("Hey... you can let go now...")
        self.emotions.on_positive_interaction()

    # ------------------------------------------------------------------
    # Pet detection
    # ------------------------------------------------------------------

    def _on_pet_detected(self):
        """Slow mouse movement over the fish — petted!"""
        self.emotions.on_petting()
        self.animator.queue_reaction(ReactionType.PURR)
        self.animator.spawn_particle("heart")
        self._relationship.add_points("petting")

    # ------------------------------------------------------------------
    # Shake detection
    # ------------------------------------------------------------------

    def _on_shake_detected(self):
        """Too much shaking during drag."""
        self.emotions.on_shaken()
        self.animator.queue_reaction(ReactionType.SHAKE_OFF)
        self.animator.spawn_particle("exclamation")
        self._say("Woah! Stop that!")
        self._relationship.add_points("shake")

    # ------------------------------------------------------------------
    # File drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
            self.emotions.spike("curious", 0.3)
            self.animator.queue_reaction(ReactionType.HEAD_TILT)

    def dropEvent(self, event):
        self._last_interaction_time = time.monotonic()
        mime = event.mimeData()
        if mime.hasUrls():
            urls = mime.urls()
            if urls:
                name = urls[0].fileName() or urls[0].toString()
                self._say(f"Ooh, what's this? {name[:30]}...")
        elif mime.hasText():
            snippet = mime.text()[:30]
            self._say(f"Hmm... '{snippet}'...")
        self.emotions.spike("curious", 0.4)
        self.animator.spawn_particle("question")
        self.emotions.on_positive_interaction()
        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Global keyboard polling (Ctrl+Z, Ctrl+S, PrintScreen)
    # ------------------------------------------------------------------

    def _poll_keyboard(self):
        """Poll for global hotkeys using Windows API."""
        try:
            import ctypes
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            self._kb_timer.stop()
            return

        VK_Z = 0x5A
        VK_S = 0x53
        VK_SNAPSHOT = 0x2C
        VK_CONTROL = 0x11
        VK_SHIFT = 0x10
        VK_F = 0x46

        ctrl_down = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
        shift_down = user32.GetAsyncKeyState(VK_SHIFT) & 0x8000

        for vk, key_name in [(VK_Z, "ctrl_z"), (VK_S, "ctrl_s"), (VK_SNAPSHOT, "prtsc"), (VK_F, "ctrl_shift_f")]:
            is_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            was_down = self._prev_key_states.get(vk, False)

            if is_down and not was_down:
                if key_name == "ctrl_z" and ctrl_down:
                    self._on_ctrl_z()
                elif key_name == "ctrl_s" and ctrl_down:
                    self._on_ctrl_s()
                elif key_name == "prtsc":
                    self._on_screenshot()
                elif key_name == "ctrl_shift_f" and ctrl_down and shift_down:
                    self._start_screen_review()

            self._prev_key_states[vk] = is_down

    def _on_ctrl_z(self):
        """User pressed Ctrl+Z — sympathetic wince."""
        self.emotions.spike("worried", 0.15)
        self.animator.queue_reaction(ReactionType.HEAD_TILT)

    def _on_ctrl_s(self):
        """User pressed Ctrl+S — approving nod."""
        self.emotions.spike("happy", 0.1)
        self.animator.queue_reaction(ReactionType.NOD)

    def _on_screenshot(self):
        """PrintScreen detected — camera flash blink."""
        self.emotions.spike("excited", 0.2)
        self.animator.trigger_double_blink()
        self.animator.spawn_particle("sparkle")

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _build_context_menu(self):
        self._menu = QMenu(self)
        self._menu.setStyleSheet("""
            QMenu {
                background-color: #1A1A2E;
                color: #E2E8F0;
                border: 2px solid #5BA8C8;
                border-radius: 6px;
                padding: 6px 4px;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 3px;
                margin: 1px 4px;
            }
            QMenu::item:selected {
                background-color: #5BA8C8;
                color: #0F172A;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        settings_action = self._menu.addAction("Settings")
        settings_action.triggered.connect(self._open_settings)

        voice_action = self._menu.addAction("Listen")
        voice_action.triggered.connect(self._toggle_listening)

        games_action = self._menu.addAction("Games")
        games_action.triggered.connect(self._open_games)

        hobbies_action = self._menu.addAction("Hobbies")
        hobbies_action.triggered.connect(self._open_hobbies)

        chat_action = self._menu.addAction("Chat")
        chat_action.triggered.connect(self._open_chat_window)

        review_action = self._menu.addAction("Review my screen")
        review_action.triggered.connect(lambda: self._start_screen_review())

        sleep_action = self._menu.addAction("Sleep")
        sleep_action.triggered.connect(self._enter_sleep)

        log_action = self._menu.addAction("Fish Log")
        log_action.triggered.connect(self._show_fish_log)

        self._menu.addSeparator()

        quit_action = self._menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)

    def contextMenuEvent(self, event):
        self._menu.exec(event.globalPos())

    # ------------------------------------------------------------------
    # Voice / Command handling
    # ------------------------------------------------------------------

    def _on_transcription(self, text: str):
        """Called when voice recorder delivers transcribed text."""
        self._last_interaction_time = time.monotonic()
        self._behavior_engine.record_interaction()

        # Show transcription in chat window if open
        if self._chat_window is not None and self._chat_window.isVisible():
            self._chat_window._add_user_message(text)

        try:
            result = self._cmd_parser.parse(text)
        except Exception:
            self._say("Something went wrong parsing that.")
            return

        # No command matched — fall back to AI conversation
        if result is None:
            self._chat.send(text)
            self.emotions.spike("curious", 0.15)
            return

        try:
            self._execute_command(result)
        except Exception:
            self._say("Oops, something went wrong with that command.")
            self._tts.say("Sorry, that didn't work.")

    def _execute_command(self, result):
        self._command_count += 1

        # Special actions that need the widget
        if result.action == "come_to_cursor":
            pos = QCursor.pos()
            self._walk_to(pos.x() - self.width() // 2, pos.y() - self.height() // 2, speed=800.0)
        elif result.action == "hide":
            self.hide()
            # Auto-show after 30s so fish doesn't permanently vanish
            QTimer.singleShot(30000, self._show_fish)
        elif result.action == "rest_mode":
            self.emotions.values["sleepy"] = 0.8
            self._last_break_time = time.monotonic()
        elif result.action == "status":
            emo = self.emotions.dominant_emotion()
            result.response = f"I'm feeling {emo} right now."
        elif result.action == "set_timer":
            secs = int(result.target)
            self._start_timer(secs)
        elif result.action == "set_named_timer":
            parts = result.target.split("|", 1)
            secs = int(parts[0])
            name = parts[1] if len(parts) > 1 else "timer"
            self._start_named_timer(secs, name)
        elif result.action == "set_reminder":
            parts = result.target.split("|", 1)
            secs = int(parts[0])
            msg = parts[1] if len(parts) > 1 else "Time's up!"
            self._start_reminder(secs, msg)
        elif result.action == "set_alarm":
            self._set_alarm(result.target)
            return  # response set inside _set_alarm
        elif result.action == "list_timers":
            result.response = self._list_active_timers()
        elif result.action == "cancel_timer":
            result.response = self._cancel_timer(result.target)
        elif result.action == "confirm_power":
            # Store pending power action for "yes" confirmation
            self._pending_power = result.target  # "shutdown" or "restart"
        elif result.action == "confirm_yes":
            self._execute_pending_power()
        elif result.action == "todo_add":
            msg = self._todo_list.add(result.target)
            result.response = msg
        elif result.action == "todo_list":
            result.response = self._todo_list.list_pending()
        elif result.action == "todo_complete":
            result.response = self._todo_list.complete(result.target)
        elif result.action == "todo_remove":
            result.response = self._todo_list.remove(result.target)
        elif result.action == "companion_on":
            self._companion_mode = True
            self._config.setdefault("intelligence", {})["companion_mode"] = True
            self._save_config()
        elif result.action == "companion_off":
            self._companion_mode = False
            self._config.setdefault("intelligence", {})["companion_mode"] = False
            self._save_config()
        elif result.action == "briefing":
            weather = self.emotions.weather
            mood = self.emotions.dominant_emotion()
            todo_count = self._todo_list.count_pending()
            result.response = generate_morning_briefing(weather, mood, todo_count)
        elif result.action == "joke":
            result.response = get_random_joke_or_fact()

        # --- API-backed commands (run in thread to avoid blocking) ---
        elif result.action in ("weather", "forecast", "wikipedia", "news",
                               "translate", "define", "exchange_rate",
                               "holiday_check", "sun_times", "speed_test",
                               "find_file"):
            self._run_api_action(result)
            return  # response will be shown async

        # --- Clipboard actions ---
        elif result.action == "read_clipboard":
            cb = QApplication.clipboard()
            text_on_clip = cb.text()
            if text_on_clip:
                short = text_on_clip[:200] + ("..." if len(text_on_clip) > 200 else "")
                result.response = f"Clipboard says: {short}"
            else:
                result.response = "Clipboard is empty."

        elif result.action == "save_clipboard":
            import os
            cb = QApplication.clipboard()
            text_on_clip = cb.text()
            if text_on_clip:
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                fname = f"clipboard_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                path = os.path.join(desktop, fname)
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text_on_clip)
                    result.response = f"Saved clipboard to {fname} on Desktop."
                except Exception:
                    result.response = "Couldn't save clipboard."
                    result.success = False
            else:
                result.response = "Nothing on clipboard to save."
                result.success = False

        # --- Groq-driven prompts ---
        elif result.action == "groq_prompt":
            self._run_groq_prompt(result.target)
            return  # response comes async via _on_chat_response

        # --- Pomodoro timer (25 min work, 5 min break) ---
        elif result.action == "pomodoro":
            self._start_pomodoro()

        # --- Media: what's playing ---
        elif result.action == "whats_playing":
            title = self._detect_playing_media()
            result.response = title if title else "Can't tell what's playing."

        # --- Mic toggle ---
        elif result.action == "toggle_mic":
            if result.target == "mute":
                self._voice.stop_vad()
                result.response = "Mic muted."
            else:
                self._voice.start_vad()
                result.response = "Mic unmuted."

        # --- System status ---
        elif result.action == "system_status":
            result.response = self._get_system_status()

        elif result.action == "top_processes":
            result.response = self._get_top_processes()

        elif result.action == "session_time":
            elapsed = time.monotonic() - self._session_start
            hours = int(elapsed // 3600)
            mins = int((elapsed % 3600) // 60)
            result.response = f"You've been on for {hours}h {mins}m this session."

        elif result.action == "vscode_time":
            result.response = self._get_vscode_time()

        elif result.action == "posture_check":
            elapsed = time.monotonic() - self._last_break_time
            hours = int(elapsed // 3600)
            mins = int((elapsed % 3600) // 60)
            result.response = f"You've been sitting for {hours}h {mins}m since your last break."

        elif result.action == "last_break":
            elapsed = time.monotonic() - self._last_break_time
            mins = int(elapsed // 60)
            if mins < 2:
                result.response = "You just took a break!"
            else:
                result.response = f"Your last break was {mins} minutes ago."

        elif result.action == "command_count":
            result.response = f"You've used {self._command_count} commands this session."

        elif result.action == "fish_mood":
            result.response = self._get_mood_and_reason()

        elif result.action == "daily_summary":
            result.response = self._get_daily_summary()

        elif result.action == "app_too_long":
            result.response = self._get_longest_running_app()

        elif result.action == "media_sleep_timer":
            mins = int(result.target) if result.target.isdigit() else 30
            self._start_media_sleep_timer(mins)

        # --- Games ---
        elif result.action == "high_scores":
            result.response = self._get_high_scores()

        elif result.action == "play_game":
            self._open_games()
            result.response = "Opening games!"

        elif result.action == "game_picker":
            self._open_games()
            result.response = "Here are the games!"

        elif result.action == "hobby_picker":
            self._open_hobbies()
            result.response = "Pick a hobby!"

        elif result.action == "screen_review":
            focus = result.target if result.target else None
            self._start_screen_review(focus)
            result.response = "Let me take a look..."

        elif result.action == "point_at_screen":
            result.response = self._point_at_last_mention()

        # Emotion reactions
        if result.success:
            self.emotions.spike("happy", 0.15)
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self.emotions.on_positive_interaction()
        else:
            self.emotions.spike("worried", 0.2)
            self.animator.spawn_particle("question")

        # Show response in bubble + speak it
        if result.response:
            self._say(result.response)
            self._tts.say(result.response)

    def _on_chat_response(self, text: str):
        """Called when AI chat generates a response."""
        self._say(text)
        self._tts.say(text)
        self.emotions.spike("happy", 0.1)
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self._shared_state.record_phrase()
        self._relationship.add_points("conversation")
        self._behavior_engine.record_interaction()

    def _get_chat_context(self) -> dict:
        """Return live context dict for the AI system prompt."""
        import datetime
        elapsed = time.monotonic() - self._session_start
        return {
            "hour": datetime.datetime.now().hour,
            "session_hours": int(elapsed // 3600),
            "session_mins": int((elapsed % 3600) // 60),
            "active_app": getattr(self._behavior_engine, '_active_app', ''),
            "energy": self.emotions._energy,
            "dominant": self.emotions.dominant_emotion(),
        }

    # ------------------------------------------------------------------
    # Screen review
    # ------------------------------------------------------------------

    def _start_screen_review(self, focus: str | None = None):
        """Kick off screenshot → OCR → Groq review pipeline."""
        self._say("Let me take a look...")
        self._tts.say("Let me take a look.")
        self.animator.queue_reaction(ReactionType.HEAD_TILT)
        self._reviewer.review(focus)

    def _point_at_last_mention(self) -> str:
        """Try to move the fish to point at whatever it last commented about on screen."""
        comment = self._reviewer._last_peek_comment
        if not comment or not self._reviewer._last_peek_boxes:
            return "I haven't looked at the screen recently — ask me to review it first!"

        # Extract quoted words or key nouns from the comment to search for
        import re
        # Try quoted strings first (e.g., "Q LittleFish")
        quoted = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', comment)
        search_terms = quoted if quoted else []

        # Also try capitalized multi-word phrases (likely UI elements)
        if not search_terms:
            caps = re.findall(r'\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)+)\b', comment)
            search_terms = caps

        # Fall back to longest meaningful words from the comment
        if not search_terms:
            words = [w for w in comment.split()
                     if len(w) > 4 and w.lower() not in {
                         "their", "there", "these", "those", "about",
                         "which", "where", "would", "could", "should",
                         "screen", "button", "thing", "something",
                     }]
            search_terms = words[:3]

        # Search OCR data for each term
        for term in search_terms:
            pos = self._reviewer.find_on_screen(term)
            if pos:
                x, y = pos
                # Walk to that position (offset so fish is beside it, not on top)
                self._walk_to(x - self.width() // 2, y - self.height(), speed=800.0)
                self.animator.queue_reaction(ReactionType.HEAD_TILT)
                return f"Right here! I see it around this area."

        return "I can't find it on screen anymore — it may have changed."

    def _on_review_ready(self, text: str):
        """Called when ScreenReviewer delivers the critique."""
        self._say(text)
        self._tts.say(text)
        self.emotions.spike("curious", 0.3)
        self.animator.queue_reaction(ReactionType.NOD)
        self._shared_state.record_phrase()
        # Auto-open chat window so the review is always readable
        if not self._chat_window.isVisible():
            self._open_chat_window()

    def _on_peek_ready(self, text: str):
        """Called when ScreenReviewer delivers a casual autonomous comment."""
        if self._is_user_chatting:
            return  # don't interrupt an active conversation
        self._say(text)
        self._tts.say(text)
        self.emotions.spike("curious", 0.15)
        self._shared_state.record_phrase()

    def _show_bubble(self, text: str):
        """Display a chat bubble above the fish."""
        anchor = self.mapToGlobal(QPoint(self.width() // 2, 0))
        self._bubble.show_message(text, anchor)

    def _sync_to_chat(self, text: str):
        """Route fish-initiated messages to the chat window and history."""
        if self._chat_window is None:
            from widget.chat_window import ChatWindow
            self._chat_window = ChatWindow(self._chat, self)
        self._chat_window._add_fish_message(text)
        # Persist to chat history so messages survive window re-open / restart
        hist = self._chat._history
        if not hist or hist[-1].get("content") != text:
            hist.append({"role": "assistant", "content": text})
            from core.intelligence import save_chat_history
            save_chat_history(hist)

    def _say(self, text: str):
        """Show bubble + always sync to chat history. Use this for all fish speech."""
        self._show_bubble(text)
        self._sync_to_chat(text)

    # ------------------------------------------------------------------
    # API / async command helpers
    # ------------------------------------------------------------------

    def _run_api_action(self, result):
        """Run an API-backed command in a thread so the UI stays responsive."""
        import threading
        from core import web_apis

        action = result.action
        target = result.target

        def _work():
            try:
                if action == "weather":
                    text = web_apis.weather(target or None)
                elif action == "forecast":
                    text = web_apis.forecast(target or None)
                elif action == "wikipedia":
                    text = web_apis.wikipedia_summary(target)
                elif action == "news":
                    text = web_apis.top_news()
                elif action == "translate":
                    parts = target.split("|", 1)
                    lang = parts[0] if parts else "en"
                    src = parts[1] if len(parts) > 1 else ""
                    text = web_apis.translate_text(src, lang)
                elif action == "define":
                    text = web_apis.define_word(target)
                elif action == "exchange_rate":
                    parts = target.split("|")
                    fr = parts[0] if parts else "USD"
                    to = parts[1] if len(parts) > 1 else "EUR"
                    amt = float(parts[2]) if len(parts) > 2 else 1.0
                    text = web_apis.exchange_rate(fr, to, amt)
                elif action == "holiday_check":
                    text = web_apis.holiday_check(target or None)
                elif action == "sun_times":
                    text = web_apis.sun_times()
                elif action == "speed_test":
                    text = web_apis.speed_test()
                elif action == "find_file":
                    text = self._find_file(target)
                else:
                    text = "Not sure how to do that."
            except Exception:
                text = "Something went wrong."
            # Schedule UI update on main thread
            QTimer.singleShot(0, lambda: self._show_api_result(text))

        threading.Thread(target=_work, daemon=True).start()
        self._say("Let me check...")

    def _show_api_result(self, text: str):
        self._say(text)
        self._tts.say(text)
        self.emotions.spike("happy", 0.1)

    def _find_file(self, name: str) -> str:
        """Search user home for a file by name."""
        import subprocess
        try:
            result = subprocess.run(
                ["where", "/R", Path.home().as_posix(), f"*{name}*"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            if lines:
                top = lines[:3]
                msg = "Found: " + ", ".join(Path(p).name for p in top)
                if len(lines) > 3:
                    msg += f" ... and {len(lines) - 3} more."
                return msg
            return f"Couldn't find any files matching '{name}'."
        except Exception:
            return "File search failed."

    def _run_groq_prompt(self, target: str):
        """Send a styled prompt to Groq chat. Target format: 'action' or 'action|context'."""
        parts = target.split("|", 1)
        action = parts[0]
        context = parts[1] if len(parts) > 1 else ""

        prompt_map = {
            "roast": "Roast me in one sentence. Be funny and savage.",
            "motivate": "Give me a short motivational line. One sentence, no fluff.",
            "proofread": f"Proofread this and give a corrected version only: {context}",
            "name": f"Suggest 3 creative names for: {context}. Just the names, nothing else.",
            "suggest_watch": "Suggest one thing to watch right now. One sentence.",
            "suggest_eat": "Suggest one thing to eat right now. One sentence.",
            "quiz": f"Ask me one trivia question about {context}. Just the question.",
            "email": f"Draft a short professional email about: {context}",
            "explain": f"Explain this simply in 2 sentences: {context}",
            "summarize": f"Summarize this in 2 sentences: {context}",
            "brainstorm": f"Give me 3 quick ideas for: {context}. Just bullet points.",
        }
        prompt = prompt_map.get(action, f"{action}: {context}")
        self._chat.send(prompt)
        self.emotions.spike("curious", 0.15)

    def _detect_playing_media(self) -> str:
        """Try to detect currently playing media from window titles."""
        import ctypes
        try:
            # Look for common media player window titles
            import ctypes.wintypes
            titles = []

            def enum_callback(hwnd, _):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                        titles.append(buf.value)
                return True

            enum_func = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            ctypes.windll.user32.EnumWindows(enum_func(enum_callback), 0)

            # Look for common patterns: "Song - Artist - Spotify", "Title - YouTube"
            media_keywords = ["spotify", "youtube", "music", "vlc", "media player",
                              "foobar", "winamp", "itunes"]
            for title in titles:
                tl = title.lower()
                for kw in media_keywords:
                    if kw in tl and len(title) > 5:
                        return f"Looks like: {title}"
            return ""
        except Exception:
            return ""

    def _get_system_status(self) -> str:
        """Return a quick system status summary."""
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        parts = [f"CPU: {cpu}%, RAM: {ram}%"]
        try:
            battery = psutil.sensors_battery()
            if battery:
                plug = "plugged in" if battery.power_plugged else "on battery"
                parts.append(f"Battery: {battery.percent}% ({plug})")
        except Exception:
            pass
        return " | ".join(parts)

    def _get_top_processes(self) -> str:
        """Return top 3 CPU-consuming processes."""
        import psutil
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent"]):
            try:
                procs.append((p.info["name"], p.info["cpu_percent"] or 0))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x[1], reverse=True)
        top = procs[:3]
        if top:
            items = [f"{name} ({cpu:.0f}%)" for name, cpu in top]
            return "Top processes: " + ", ".join(items)
        return "Couldn't get process info."

    def _get_high_scores(self) -> str:
        """Return game high scores from the scores file."""
        from games.game_manager import _load_scores
        scores = _load_scores()
        if scores:
            items = [f"{game}: {score}" for game, score in scores.items()]
            return "High scores: " + ", ".join(items)
        return "No high scores yet. Play some games!"

    def _get_vscode_time(self) -> str:
        """Check how long VS Code has been running."""
        import psutil
        try:
            for proc in psutil.process_iter(["name", "create_time"]):
                name = (proc.info["name"] or "").lower()
                if "code" in name:
                    elapsed = time.time() - proc.info["create_time"]
                    hours = int(elapsed // 3600)
                    mins = int((elapsed % 3600) // 60)
                    return f"VS Code has been open for {hours}h {mins}m."
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return "VS Code doesn't seem to be running."

    def _posture_reminder(self):
        """Auto-triggered every 2 hours to remind user to stretch."""
        self._say("You've been sitting for 2 hours! Time to stretch and take a break.")
        self._tts.say("Hey! You've been sitting for a while. Stand up and stretch!")
        self.emotions.spike("worried", 0.2)
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.spawn_particle("exclamation")

    def _get_mood_and_reason(self) -> str:
        """Return current mood with explanation."""
        dominant = self.emotions.dominant_emotion()
        val = self.emotions.values.get(dominant, 0)
        # Build a reason string based on emotional state
        reasons = []
        if self.emotions.values.get("bored", 0) > 0.4:
            reasons.append("I'm a bit bored")
        if self.emotions.values.get("happy", 0) > 0.5:
            reasons.append("we've been chatting")
        if self.emotions.values.get("sleepy", 0) > 0.4:
            reasons.append("it's getting late")
        if self.emotions.values.get("worried", 0) > 0.3:
            reasons.append("something seems off with the system")
        if self.emotions.values.get("focused", 0) > 0.4:
            reasons.append("you seem to be working hard")
        if self.emotions.values.get("excited", 0) > 0.4:
            reasons.append("something fun just happened")
        reason = " because " + " and ".join(reasons) if reasons else ""
        return f"I'm feeling {dominant} ({val:.0%} intensity){reason}."

    def _get_daily_summary(self) -> str:
        """Return a summary of the day's activity."""
        elapsed = time.monotonic() - self._session_start
        hours = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        dominant = self.emotions.dominant_emotion()
        parts = [
            f"Session: {hours}h {mins}m",
            f"Commands used: {self._command_count}",
            f"Interactions: {self._shared_state._interaction_count}",
            f"Games played: {self._shared_state._games_played}",
            f"Current mood: {dominant}",
        ]
        return "Daily summary — " + " | ".join(parts)

    def _get_longest_running_app(self) -> str:
        """Find apps that have been open the longest."""
        import psutil
        try:
            apps = []
            for proc in psutil.process_iter(["name", "create_time"]):
                name = (proc.info["name"] or "").lower()
                # Skip system processes
                if name in ("system", "idle", "svchost.exe", "csrss.exe",
                            "wininit.exe", "services.exe", "lsass.exe",
                            "smss.exe", "winlogon.exe", "dwm.exe",
                            "explorer.exe", "registry", ""):
                    continue
                try:
                    elapsed = time.time() - proc.info["create_time"]
                    if elapsed > 3600:  # only show apps open > 1 hour
                        apps.append((proc.info["name"], elapsed))
                except (TypeError, ValueError):
                    continue
            if not apps:
                return "No apps have been open for more than an hour."
            apps.sort(key=lambda x: x[1], reverse=True)
            top = apps[:3]
            items = []
            for name, secs in top:
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                items.append(f"{name} ({h}h {m}m)")
            return "Longest running apps: " + ", ".join(items)
        except Exception:
            return "Couldn't check running apps."

    def _start_media_sleep_timer(self, minutes: int):
        """Set a timer that sends a media pause key after X minutes."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(minutes * 60 * 1000)
        timer._fish_name = f"media sleep ({minutes}m)"
        timer._fish_start = time.monotonic()
        timer._fish_seconds = minutes * 60
        timer.timeout.connect(self._on_media_sleep_done)
        timer.start()
        if not hasattr(self, '_active_timers'):
            self._active_timers = []
        self._active_timers.append(timer)
        self._say(f"Media will pause in {minutes} minutes.")
        self._tts.say(f"Got it, I'll pause your media in {minutes} minutes.")

    def _on_media_sleep_done(self):
        """Pause media when sleep timer is up."""
        try:
            import ctypes
            VK_MEDIA_PLAY_PAUSE = 0xB3
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)
        except Exception:
            pass
        self._say("Media paused. Goodnight!")
        self._tts.say("I've paused your media. Goodnight!")
        self.emotions.spike("sleepy", 0.3)

    # ------------------------------------------------------------------
    # Phase 4: Particles & idle behavior
    # ------------------------------------------------------------------

    def _maybe_spawn_particle(self):
        """Spawn particles based on current dominant emotion + seasonal + weather."""
        import random
        import datetime
        emo = self.emotions.dominant_emotion()
        val = self.emotions.get(emo)
        particle_map = {
            "sleepy": "zzz",
            "excited": "sparkle",
            "worried": "sweat",
            "happy": "heart",
            "curious": "question",
            "focused": "star",
            "bored": "zzz",
        }
        kind = particle_map.get(emo)
        # Strong emotion = higher chance, but always some chance for ambient life
        if kind:
            chance = 0.3 if val < 0.35 else (0.55 if val < 0.6 else 0.8)
            if random.random() < chance:
                self.animator.spawn_particle(kind)

        # Seasonal particles
        month = datetime.datetime.now().month
        if month == 12 and random.random() < 0.4:
            self.animator.spawn_particle("snow")
        elif month == 10 and random.random() < 0.35:
            self.animator.spawn_particle("leaf")

        # Weather-based particles (rain, lightning)
        weather = self.emotions.weather
        if weather:
            wl = weather.lower()
            if 'rain' in wl or 'drizzle' in wl or 'shower' in wl:
                for _ in range(random.randint(2, 5)):
                    self.animator.spawn_particle("rain")
            if 'thunder' in wl or 'storm' in wl:
                if random.random() < 0.25:
                    self.animator.spawn_particle("lightning")

        # Sleep bubble when sleepy
        if emo == "sleepy" and val > 0.3:
            if random.random() < 0.5:
                self.animator.spawn_particle("sleep_bubble")

        # Fireworks on birthday / New Year
        seasonal = self.emotions.get_seasonal_event()
        if seasonal in ("Birthday", "New Year", "New Year's Eve"):
            if random.random() < 0.5:
                for _ in range(random.randint(3, 6)):
                    self.animator.spawn_particle("firework")

    # ------------------------------------------------------------------
    # Movement state reactions
    # ------------------------------------------------------------------

    def _on_movement_state_changed(self, old: MovementState, new: MovementState):
        """Visual reactions when the movement engine changes state."""
        if new == MovementState.RETREAT:
            self.animator.queue_reaction(ReactionType.FLINCH)
            self.animator.spawn_particle("exclamation")
        elif new == MovementState.CURIOUS:
            self.animator.queue_reaction(ReactionType.STRETCH)
            self.animator.spawn_particle("question")
            self.emotions.spike("curious", 0.2)
        elif new == MovementState.CHASE:
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self.emotions.spike("excited", 0.15)
        elif new == MovementState.WANDER and old == MovementState.IDLE:
            self.animator.queue_reaction(ReactionType.WIGGLE)
        elif new == MovementState.SETTLE:
            self.animator.trigger_slow_blink()

    # ------------------------------------------------------------------
    # Behavior engine handler
    # ------------------------------------------------------------------

    def _on_behavior(self, action: str, message: str):
        """Handle an autonomous behavior triggered by BehaviorEngine."""
        import random as _rng

        # Record interaction for relationship
        self._behavior_engine.record_interaction()

        # When sleeping, only allow wake_up — no talking, moving, or animations
        is_sleepy = self.emotions.dominant_emotion() == "sleepy"
        if is_sleepy and action != "wake_up":
            return

        # When user is actively chatting, suppress speech behaviors
        # (allow silent actions like blink, stretch, look_around, etc.)
        _SPEECH_ACTIONS = {
            "say", "thought", "rate_app", "opinion", "backstory",
            "milestone", "separation_greeting", "screen_peek",
            "excited", "worried", "grumpy", "sleepy_lock",
        }
        if self._is_user_chatting and action in _SPEECH_ACTIONS:
            return

        if action == "say" and message:
            final_msg = message
            self._say(final_msg)
            self._tts.say(final_msg)
        elif action == "thought":
            thought = self._behavior_engine.get_random_thought()
            self._say(thought)
        elif action == "rate_app":
            rating = self._behavior_engine.get_app_rating()
            self._say(rating)
            self._tts.say(rating)
        elif action == "opinion":
            msg = self._behavior_engine.get_opinion_message()
            if msg:
                self._say(msg)
                self._tts.say(msg)
        elif action == "backstory":
            msg = self._behavior_engine.get_backstory_fragment()
            if msg:
                self._say(msg)
                self._tts.say(msg)
        elif action == "milestone":
            mid, msg = self._behavior_engine.get_milestone_data()
            if msg:
                self._say(msg)
                self._tts.say(msg)
                self.animator.spawn_particle("sparkle")
                self.animator.queue_reaction(ReactionType.BOUNCE)
        elif action == "separation_greeting":
            msg = self._behavior_engine.get_separation_greeting()
            if msg:
                self._say(msg)
                self._tts.say(msg)
                self._behavior_engine._separation_greeting_given = True
        elif action == "comfortable_silence":
            # Just a gentle particle — no words needed
            self.animator.spawn_particle("sparkle")
        elif action == "sleep":
            if getattr(self.emotions, '_night_owl', False):
                # Night owl — refuse to sleep, do something else instead
                self.animator.queue_reaction(ReactionType.HEAD_TILT)
                return
            self.emotions.values["sleepy"] = 0.8
            self.animator.spawn_particle("zzz")
        elif action == "wake_up":
            self.emotions.values["sleepy"] = 0.2
            self.animator.queue_reaction(ReactionType.BOUNCE)
            if message:
                self._say(message)
        elif action == "yawn":
            self.animator.spawn_particle("zzz")
        elif action == "stare":
            # Eyes drift to one side for a moment
            self.renderer.set_eye_offset(_rng.choice([-3, 3]), 0)
            QTimer.singleShot(3000, lambda: self.renderer.set_eye_offset(0, 0))
        elif action == "stretch":
            self.animator.queue_reaction(ReactionType.BOUNCE)
        elif action == "look_around":
            self.renderer.set_eye_offset(_rng.randint(-3, 3), _rng.randint(-2, 2))
            QTimer.singleShot(2000, lambda: self.renderer.set_eye_offset(0, 0))
        elif action == "spin":
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self.animator.spawn_particle("sparkle")
        elif action == "sigh":
            self.animator.spawn_particle("dust")
        elif action == "sleepy_lock":
            if getattr(self.emotions, '_night_owl', False):
                return  # Night owl — ignore midnight lock
            self.emotions.values["sleepy"] = 0.9
            self.animator.spawn_particle("zzz")
            if message:
                self._say(message)
        elif action == "grumpy":
            self.emotions.spike("worried", 0.3)
            if message:
                self._say(message)
        elif action == "blink":
            self.animator.queue_reaction(ReactionType.BOUNCE)
        elif action == "excited":
            self.emotions.spike("excited", 0.4)
            self.animator.queue_reaction(ReactionType.BOUNCE)
            if message:
                self._say(message)
        elif action == "worried":
            self.emotions.spike("worried", 0.3)
            self.animator.spawn_particle("sweat")
            if message:
                self._say(message)
        elif action == "focus":
            self.emotions.spike("focused", 0.4)
        elif action == "wander":
            self._movement.force_wander()
        elif action == "throw_particle":
            self.animator.spawn_particle(_rng.choice(["star", "sparkle", "heart"]))
        elif action == "bounce":
            self.animator.queue_reaction(ReactionType.BOUNCE)
        elif action == "follow_cursor":
            self._movement.force_chase()
        elif action == "dance":
            for i in range(3):
                QTimer.singleShot(i * 400, lambda: self.animator.queue_reaction(ReactionType.BOUNCE))
            self.animator.spawn_particle("sparkle")
        elif action == "bubble_particle":
            self.animator.spawn_particle("sleep_bubble")
        elif action == "peek_edge":
            screen = QApplication.primaryScreen().availableGeometry()
            self._movement.force_settle(
                float(screen.x() + screen.width() - self.width() - 5),
                float(self.y()),
            )
        elif action == "screen_peek":
            # Autonomous screen glance — peek at what the user is doing
            try:
                from core.system_monitor import _get_active_window_title, _get_active_process_name
                title = _get_active_window_title()
                proc = _get_active_process_name()
                self._reviewer.peek(title, proc)
            except Exception:
                pass
        elif action == "play_anim":
            # Play a complex animation sequence from the library
            self._play_animation_sequence(message)

    def _play_animation_sequence(self, anim_name: str):
        """Play a named animation from the animation library."""
        from core.animation_library import ANIMATION_LIBRARY
        seq = ANIMATION_LIBRARY.get(anim_name)
        if seq is None:
            return
        # Don't interrupt an already playing sequence
        if self.animator.is_playing_sequence:
            return
        # Don't play if dragging or talking
        if self._is_dragging or self._tts.is_speaking:
            return
        self.animator.play_sequence(seq)

    def _idle_behavior(self):
        """Rich idle behaviors — ambient life + active idle + deep idle."""
        import random
        if self._is_dragging or self._tts.is_speaking or self._voice.is_recording:
            return
        # Don't override animation library sequences
        if self.animator.is_playing_sequence:
            return

        # Sleepy behavior — truly asleep, minimal activity
        if self.emotions.dominant_emotion() == "sleepy":
            r = random.random()
            if r < 0.15:
                self.animator.trigger_slow_blink()
            # No looking around or sleepiness reduction — fish is sleeping
            return

        idle_secs = time.monotonic() - self._last_interaction_time

        # Quiet mode (VS Code active) — calmer but still alive
        if self._quiet_mode:
            r = random.random()
            if r < 0.10:
                self.animator.trigger_slow_blink()
            elif r < 0.22:
                self.animator.trigger_look_around()
            elif r < 0.30:
                self.animator.queue_reaction(ReactionType.STRETCH)
            elif r < 0.35:
                self.animator.spawn_particle(random.choice(["sparkle", "star"]))
            # Movement handled by MovementEngine
            return

        # Tier 3: Deep idle (10+ min) — relaxed daydreaming, NOT forced sleep
        if idle_secs > 600:
            r = random.random()
            if r < 0.20:
                self.animator.trigger_slow_blink()
            elif r < 0.35:
                self.animator.trigger_nod_off()
            elif r < 0.45:
                self.animator.trigger_look_around()
            elif r < 0.55:
                self.emotions.spike("bored", 0.2)
            # Movement handled by MovementEngine (WANDER when bored)
            return

        # Tier 2: Active idle (2-10 min) — rich behaviors
        if idle_secs > 120:
            r = random.random()
            if r < 0.18:
                self.animator.trigger_look_around()
            elif r < 0.28:
                self.animator.queue_reaction(ReactionType.STRETCH)
            elif r < 0.38:
                # Yawn: slow blink + sleepy face + stretch
                self.animator.trigger_slow_blink()
                self.animator.set_face("sleepy")
                self.animator.queue_reaction(ReactionType.STRETCH)
            elif r < 0.46:
                self.emotions.spike("curious", 0.25)
                self.animator.spawn_particle("question")
            elif r < 0.53:
                self.animator.queue_reaction(ReactionType.NOD)
            elif r < 0.60:
                self.animator.trigger_double_blink()
            elif r < 0.68:
                self.animator.queue_reaction(ReactionType.HEAD_TILT)
            elif r < 0.76:
                self.animator.trigger_look_around()
                self.animator.spawn_particle("music")
            elif r < 0.84:
                # Context-based emote pop-ups
                if self._quiet_mode:
                    self.animator.spawn_particle("emote_book")
                elif hasattr(self, '_music_playing') and self._music_playing:
                    self.animator.spawn_particle("emote_music")
                else:
                    import datetime
                    hour = datetime.datetime.now().hour
                    if hour < 11:
                        self.animator.spawn_particle("emote_coffee")
                    else:
                        self.animator.spawn_particle("emote_book")
            else:
                self.animator.trigger_slow_blink()
            # Movement handled by MovementEngine
            return

        # Tier 1: Ambient (0-2 min) — lively background life
        r = random.random()
        if r < 0.12:
            self.animator.trigger_slow_blink()
        elif r < 0.24:
            self.animator.trigger_double_blink()
        elif r < 0.34:
            self.animator.queue_reaction(ReactionType.BOUNCE)
        elif r < 0.46:
            self.animator.trigger_look_around()
        elif r < 0.54:
            self.animator.queue_reaction(ReactionType.HEAD_TILT)
        elif r < 0.60:
            self.animator.queue_reaction(ReactionType.NOD)
        # Movement handled by MovementEngine

    def _on_listening_started(self):
        self.emotions.on_mic_active()
        self.animator.set_face("curious")
        self._say("I'm listening...")

    def _on_listening_stopped(self):
        self._bubble.dismiss()

    def _on_voice_error(self, msg: str):
        print(f"[Voice Error] {msg}")
        self._say(f"Oops: {msg[:60]}")

    def _on_compliment(self):
        self.emotions.on_compliment()
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.spawn_particle("heart")
        self.animator.spawn_particle("sparkle")
        self._say("Aww, thank you!")
        self._relationship.add_points("compliment")
        self._behavior_engine.record_interaction()

    def _on_insult(self):
        self.emotions.on_insult()
        self.animator.queue_reaction(ReactionType.FLINCH)
        self.animator.spawn_particle("sweat")
        self._say("That... that hurt...")
        self._relationship.add_points("insult")
        self._behavior_engine.record_interaction()

    def _on_name_called(self):
        self.emotions.on_name_called()
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.spawn_particle("exclamation")
        self._say("You called?")

    def _on_whisper(self):
        self.emotions.on_whisper_detected()
        self.animator.queue_reaction(ReactionType.HEAD_TILT)

    def _on_singing(self):
        self.emotions.on_singing_detected()
        self.animator.queue_reaction(ReactionType.PURR)
        self.animator.spawn_particle("music")
        self.animator.spawn_particle("music")

    def _on_mic_spike(self):
        self.animator.queue_reaction(ReactionType.FLINCH)
        self.animator.trigger_look_around()

    def _toggle_listening(self):
        """Push-to-talk toggle — triggered by hotkey or context menu."""
        if not self._voice_enabled:
            return
        self._last_interaction_time = time.monotonic()
        if self._voice.is_recording:
            self._voice.stop_listening()
        else:
            self._voice.start_listening()

    # ------------------------------------------------------------------
    # Unprompted speech
    # ------------------------------------------------------------------

    def _unprompted_thought(self):
        """Fish spontaneously says something — the soul of the pet."""
        import random
        # Don't talk while sleeping
        if self.emotions.dominant_emotion() == "sleepy":
            self._reschedule_unprompted()
            return
        # Don't interrupt active chat conversation
        if self._is_user_chatting:
            self._reschedule_unprompted()
            return
        # Don't interrupt if busy
        if self._tts.is_speaking or self._voice.is_recording:
            self._reschedule_unprompted()
            return
        # VS Code quiet mode — still talk, just less often (50% skip)
        if self._quiet_mode and random.random() < 0.5:
            self._reschedule_unprompted()
            return

        # Record relationship points for unprompted speech
        self._relationship.add_points("conversation")

        # 30% pool phrase (simple emotes), 70% AI-generated (conversational)
        if (random.random() < 0.3 or not get_groq_keys()):
            phrase = random.choice(UNPROMPTED_PHRASES)
            self._say(phrase)
            self._tts.say(phrase)
        else:
            self._chat.send_unprompted()

        self._shared_state.record_phrase()
        self._reschedule_unprompted()

    def _calc_unprompted_interval(self) -> int:
        """Calculate unprompted interval in ms, modulated by profile talkativeness."""
        import random
        base_min, base_max = 300000, 600000  # 5-10 min
        if self._user_profile:
            from core.user_profile import TALKATIVENESS_MAP
            talk = TALKATIVENESS_MAP.get(self._user_profile.talkativeness, {})
            mult = talk.get("initiation_multiplier", 1.0)
            # Lower multiplier = more frequent (inverse)
            base_min = int(base_min / max(0.3, mult))
            base_max = int(base_max / max(0.3, mult))
        return random.randint(base_min, base_max)

    def _reschedule_unprompted(self):
        self._unprompted_timer.setInterval(self._calc_unprompted_interval())

    # ------------------------------------------------------------------
    # VS Code / focus quiet mode
    # ------------------------------------------------------------------

    def _on_code_editor_active(self):
        """Called when VS Code or similar is detected — enter quiet mode.
        Only extends timeout if not already in quiet mode, preventing
        the monitor from keeping the fish permanently frozen."""
        if not self._quiet_mode:
            self._quiet_mode = True
            self._quiet_mode_until = time.monotonic() + 60.0
        self.emotions.on_code_editor_active()

    # ------------------------------------------------------------------
    # Keyboard hotkey (Right Ctrl = push-to-talk)
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Control and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            # We can't distinguish left/right ctrl natively in Qt easily,
            # so we use nativeScanCode: Right Ctrl = 285 on Windows
            if event.nativeScanCode() == 285:
                self._toggle_listening()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self):
        from config.config_ui import SettingsDialog
        if self._settings_dialog is None or not self._settings_dialog.isVisible():
            self._settings_dialog = SettingsDialog(self._config, self)
            self._settings_dialog.show()
        else:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------

    def _build_tray_icon(self):
        ico_path = Path(__file__).parent.parent / "littlefish.ico"
        if ico_path.exists():
            icon = QIcon(str(ico_path))
        else:
            icon = self._create_fish_icon()
        self._tray = QSystemTrayIcon(icon, self)
        name = self._user_profile.fish_name or self._custom_name or "Little Fish"
        self._tray.setToolTip(name)

        tray_menu = QMenu()
        show_action = tray_menu.addAction(f"Show {name}")
        show_action.triggered.connect(self._show_fish)
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)
        self._tray.setContextMenu(tray_menu)

        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _create_fish_icon(self) -> QIcon:
        """Generate a pixel-art fish icon — no asset file needed."""
        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # Body
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#5BA8C8")))
        p.drawRoundedRect(2, 2, 28, 28, 3, 3)
        p.setBrush(QBrush(QColor("#7EC8E3")))
        p.drawRoundedRect(3, 3, 26, 26, 2, 2)
        # Eyes
        p.fillRect(10, 11, 3, 4, QColor("#1A1A2E"))
        p.fillRect(19, 11, 3, 4, QColor("#1A1A2E"))
        # Mouth
        p.fillRect(12, 20, 1, 1, QColor("#1A1A2E"))
        p.fillRect(13, 21, 1, 1, QColor("#1A1A2E"))
        p.fillRect(14, 21, 1, 1, QColor("#1A1A2E"))
        p.fillRect(15, 21, 1, 1, QColor("#1A1A2E"))
        p.fillRect(16, 21, 1, 1, QColor("#1A1A2E"))
        p.fillRect(17, 20, 1, 1, QColor("#1A1A2E"))
        p.end()
        return QIcon(pixmap)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_fish()

    def _show_fish(self):
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    # Games
    # ------------------------------------------------------------------

    def _open_games(self):
        """Show a game picker menu next to the fish."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1A1A2E;
                color: #E0E0E0;
                border: 2px solid #7EC8E3;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #5BA8C8;
                color: #1A1A2E;
            }
        """)
        for label, desc, game_cls in GAME_LIST:
            action = menu.addAction(f"🎮  {label}")
            action.setToolTip(desc)
            action.triggered.connect(lambda checked, gc=game_cls: self._start_game(gc))
        menu.exec(self.mapToGlobal(QPoint(self.width(), 0)))
        self._last_interaction_time = time.monotonic()

    def _open_hobbies(self):
        """Show a hobby picker menu with all animations organized by category."""
        from core.animation_library import ANIMATION_LIBRARY

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1A1A2E;
                color: #E0E0E0;
                border: 2px solid #7EC8E3;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #5BA8C8;
                color: #1A1A2E;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        # Nice display names for animation keys
        _DISPLAY_NAMES = {
            "coffee_sip": "Sip Coffee",
            "yawn_stretch": "Yawn & Stretch",
            "eat_snack": "Eat a Snack",
            "read_book": "Read a Book",
            "nap_blanket": "Nap with Blanket",
            "brush_teeth": "Brush Teeth",
            "morning_routine": "Morning Routine",
            "big_stretch": "Big Stretch",
            "monday_drama": "Monday Drama",
            "rain_umbrella": "Umbrella in Rain",
            "sunny_shades": "Sunglasses Vibes",
            "cold_shiver": "Shiver in Cold",
            "heat_melt": "Melt in Heat",
            "dramatic_tear": "Dramatic Tear",
            "laugh_fall": "Laugh & Fall Over",
            "blush": "Blush",
            "hide_face": "Hide Face",
            "proud_puff": "Proud Puff",
            "existential_stare": "Existential Stare",
            "victory_pose": "Victory Pose",
            "sulk": "Sulk",
            "excited_wiggle": "Excited Wiggle",
            "contemplate": "Contemplate",
            "lift_weights": "Lift Weights",
            "type_frantic": "Type Frantically",
            "little_dance": "Little Dance",
            "stargaze": "Stargaze",
            "deep_focus": "Deep Focus",
            "pushups": "Push-ups",
            "head_bob": "Head Bob to Music",
            "chase_tail": "Chase Own Tail",
            "hiccup": "Hiccup",
            "sneeze_fly": "Sneeze Fly",
            "spooked_reflection": "Spooked by Reflection",
            "trip": "Trip Over Nothing",
            "statue": "Pretend Statue",
            "burp": "Burp",
            "jump_scare": "Jump Scare",
            "try_whistle": "Try to Whistle",
            "santa_gift": "Deliver Gift",
            "new_year_fireworks": "New Year Fireworks",
            "valentine_hearts": "Valentine Hearts",
            "halloween_spook": "Halloween Spook",
            "spring_stretch": "Spring Stretch",
            "summer_vibes": "Summer Vibes",
            "cooking": "Cooking",
            "painting": "Painting",
            "karate_chop": "Karate Chop",
            "ghost_pretend": "Ghost Pretend",
            "writing_letter": "Write a Letter",
            "yoga": "Yoga",
            "bird_watching": "Bird Watching",
            "air_guitar": "Air Guitar",
            "pillow_fort": "Pillow Fort",
            "shadow_puppets": "Shadow Puppets",
        }

        _CATEGORY_LABELS = {
            "hobbies": "Hobbies",
            "daily_life": "Daily Life",
            "activity": "Activities",
            "silly": "Silly",
            "emotional": "Emotional",
            "weather": "Weather",
            "seasonal": "Seasonal",
        }

        # Group animations by category
        by_cat: dict[str, list[tuple[str, str]]] = {}
        for name, seq in ANIMATION_LIBRARY.items():
            cat = seq.category
            display = _DISPLAY_NAMES.get(name, name.replace("_", " ").title())
            by_cat.setdefault(cat, []).append((name, display))

        # Show hobbies first, then the rest
        cat_order = ["hobbies", "daily_life", "activity", "silly",
                      "emotional", "weather", "seasonal"]
        for cat in cat_order:
            items = by_cat.get(cat)
            if not items:
                continue
            label = _CATEGORY_LABELS.get(cat, cat.title())
            submenu = menu.addMenu(label)
            submenu.setStyleSheet(menu.styleSheet())
            for anim_name, display in sorted(items, key=lambda x: x[1]):
                action = submenu.addAction(display)
                action.triggered.connect(
                    lambda checked, n=anim_name: self._play_animation_sequence(n))

        menu.exec(self.mapToGlobal(QPoint(self.width(), 0)))
        self._last_interaction_time = time.monotonic()

    def _start_game(self, game_cls):
        """Instantiate a desktop game and start it."""
        self._movement.pause(300.0)  # Pause during game
        game = game_cls(self)
        game.on_game_event = self._on_game_event
        self._active_game = game
        game.start_game()

    def _on_game_event(self, event: str):
        import random as _rng
        self._behavior_engine.record_interaction()
        self._last_interaction_time = time.monotonic()

        # ── Universal events ────────────────────────────────────────
        if event == "start":
            self.emotions.spike("excited", 0.6)
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self._shared_state.record_game()
            self._relationship.add_points("game_played")
            starts = ["Let's go!", "Game time!", "Here we go!"]
            self._say(_rng.choice(starts))
            return

        if event == "quit":
            self._movement.resume()
            return

        # ── Catch & Snack events ────────────────────────────────────
        if event == "streak":
            self.animator.spawn_particle("sparkle")
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self.emotions.spike("excited", 0.3)

        elif event == "ate_bad":
            self.animator.queue_reaction(ReactionType.FLINCH)
            self.animator.spawn_particle("sweat")
            self._say(_rng.choice(["Bleh! A bug!", "Eww!", "That was NOT food!"]))
            self.emotions.spike("worried", 0.2)

        elif event == "frustrated_trying":
            self.emotions.spike("frustrated", 0.5)
            self.animator.set_face("frustrated")
            self.animator.queue_reaction(ReactionType.RAGE_SHAKE)
            self._say(_rng.choice([
                "Come ON! I can do this!", "Okay, focus!!", "TRYING HARDER.",
            ]))

        elif event == "frustrated_giving_up":
            self.emotions.spike("frustrated", 0.4)
            self.animator.set_face("frustrated")
            self.animator.queue_reaction(ReactionType.WIGGLE)
            self._say(_rng.choice([
                "*dramatic sigh* This is hopeless...",
                "I give up. The food wins.",
                "Maybe I'm just not hungry...",
            ]))

        elif event == "miss_streak":
            self.animator.spawn_particle("sweat")
            self.emotions.spike("worried", 0.2)

        # ── Whack-a-Bubble events ───────────────────────────────────
        elif event == "pop":
            self.animator.spawn_particle("sparkle")
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self.emotions.spike("happy", 0.15)

        elif event == "pop_streak":
            self.animator.spawn_particle("star")
            self.animator.spawn_particle("confetti")
            self.animator.queue_reaction(ReactionType.STRETCH)
            self.emotions.spike("excited", 0.4)
            self._say(_rng.choice(["Combo!", "On fire!", "POP POP POP!"]))

        elif event == "miss_badly":
            self.animator.queue_reaction(ReactionType.SQUISH_H)
            self.animator.spawn_particle("sweat")
            self.emotions.spike("worried", 0.3)
            self._say(_rng.choice([
                "*covers face*", "I can't look...",
                "That was embarrassing...", "pretend you didn't see that",
            ]))

        elif event == "miss_pop":
            self.animator.queue_reaction(ReactionType.FLINCH)
            self.emotions.spike("frustrated", 0.15)

        # ── Flappy events ───────────────────────────────────────────
        elif event == "died_immediately":
            self.emotions.on_game_finished(won=False)
            self.animator.queue_reaction(ReactionType.WIGGLE)
            self._say(_rng.choice([
                "I meant to do that.",
                "Speed run. Any percent.",
                "That was a practice round.",
                "The pipe came out of nowhere!",
            ]))

        elif event == "died_long_run":
            self.emotions.on_game_finished(won=False)
            self.emotions.spike("frustrated", 0.5)
            self.animator.set_face("frustrated")
            self.animator.queue_reaction(ReactionType.RAGE_SHAKE)
            self.animator.spawn_particle("sweat")
            self._say(_rng.choice([
                "NO! I was doing so well!",
                "SO close! UGH!",
                "*genuine anguish*",
                "I need a moment...",
            ]))

        elif event == "died_normal":
            self.emotions.on_game_finished(won=False)
            self.animator.queue_reaction(ReactionType.FLINCH)
            self._say(_rng.choice([
                "Oof!", "Not bad, not great.",
                "One more try?", "I'll get it next time.",
            ]))

        elif event == "milestone_10":
            self.animator.spawn_particle("sparkle")
            self.animator.spawn_particle("star")
            self.emotions.spike("excited", 0.4)
            self._say("10 pipes! I'm amazing!")

        elif event == "milestone_25":
            self.animator.spawn_particle("confetti")
            self.animator.spawn_particle("confetti")
            self.emotions.spike("excited", 0.6)
            self._say("25?! I'm a LEGEND!")

        # ── Ending events (all games) ───────────────────────────────
        elif event == "total_fail":
            self.emotions.on_game_finished(won=False)
            self.animator.queue_reaction(ReactionType.DIZZY)
            self._say(_rng.choice([
                "Well... at least I tried.",
                "We don't talk about this.",
                "That was... something.",
            ]))

        elif event == "bad_game":
            self.emotions.on_game_finished(won=False)
            self.animator.queue_reaction(ReactionType.FLINCH)
            self.animator.spawn_particle("sweat")
            self._say(_rng.choice([
                "Rough round...", "I've had better days.",
                "Practice makes perfect, right?",
            ]))

        elif event == "decent_game":
            self.emotions.on_game_finished(won=False)
            self.animator.queue_reaction(ReactionType.NOD)
            self._say(_rng.choice([
                "Not bad!", "Solid run!",
                "Room for improvement, but decent!",
            ]))

        elif event == "new_record":
            self.emotions.on_game_finished(won=True)
            self.animator.spawn_particle("confetti")
            self.animator.spawn_particle("star")
            self.animator.spawn_particle("confetti")
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self.emotions.spike("excited", 0.8)
            self._say(_rng.choice([
                "NEW HIGH SCORE!!!", "I'M THE CHAMPION!",
                "🏆 BEST. FISH. EVER. 🏆",
            ]))
            self._relationship.add_points("game_played")

        # Resume movement engine after any game-ending event
        if event in ("total_fail", "bad_game", "decent_game", "new_record",
                      "died_immediately", "died_long_run", "died_normal"):
            self._movement.resume()

    # ------------------------------------------------------------------
    # Sleep mode
    # ------------------------------------------------------------------

    def _enter_sleep(self):
        """Put the fish to sleep — slows down, closes eyes, zzz particles."""
        self.emotions.values["sleepy"] = 0.8
        self.animator.set_face("sleepy")
        self.animator.trigger_nod_off()
        self.animator.spawn_particle("zzz")
        self._say("*yawns*... goodnight...")
        self._tts.say("goodnight")

    # ------------------------------------------------------------------
    # Timer & Reminder
    # ------------------------------------------------------------------

    def _start_timer(self, seconds: int, name: str = ""):
        """Set a countdown timer."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(seconds * 1000)
        timer._fish_name = name  # attach name for listing
        timer._fish_start = time.monotonic()
        timer._fish_seconds = seconds
        timer.timeout.connect(lambda: self._on_timer_done(timer))
        timer.start()
        if not hasattr(self, '_active_timers'):
            self._active_timers = []
        self._active_timers.append(timer)

    def _start_named_timer(self, seconds: int, name: str):
        """Set a named countdown timer (e.g. 'pasta timer')."""
        self._start_timer(seconds, name=name)

    def _on_timer_done(self, timer):
        name = getattr(timer, '_fish_name', '')
        label = f"{name} timer" if name else "Timer"
        self._say(f"{label}: Time's up!")
        self._tts.say(f"Hey! {label} is done!")
        self.emotions.spike("excited", 0.4)
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.spawn_particle("exclamation")
        self._play_alert_sound()
        if hasattr(self, '_active_timers'):
            self._active_timers = [t for t in self._active_timers if t is not timer]

    def _start_reminder(self, seconds: int, message: str):
        """Set a reminder with a message."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(seconds * 1000)
        timer._fish_name = f"reminder: {message[:30]}"
        timer._fish_start = time.monotonic()
        timer._fish_seconds = seconds
        timer.timeout.connect(lambda: self._on_reminder_done(timer, message))
        timer.start()
        if not hasattr(self, '_active_timers'):
            self._active_timers = []
        self._active_timers.append(timer)

    def _on_reminder_done(self, timer, message: str):
        self._say(f"Reminder: {message}")
        self._tts.say(f"Hey! Don't forget: {message}")
        self.emotions.spike("excited", 0.3)
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.spawn_particle("exclamation")
        self._play_alert_sound()
        if hasattr(self, '_active_timers'):
            self._active_timers = [t for t in self._active_timers if t is not timer]

    def _set_alarm(self, time_str: str):
        """Set a wake-up alarm for a specific time."""
        from core.command_parser import _parse_alarm_time
        seconds, label = _parse_alarm_time(time_str)
        if seconds is None:
            self._say(f"Couldn't understand the time: {time_str}")
            self._tts.say("Sorry, I couldn't understand that time.")
            return
        self._start_timer(seconds, name=f"alarm ({label})")
        self._say(f"Alarm set for {label}!")
        self._tts.say(f"Alarm set for {label}.")

    def _list_active_timers(self) -> str:
        """List all active timers with remaining time."""
        timers = getattr(self, '_active_timers', [])
        if not timers:
            return "No active timers."
        lines = []
        for i, t in enumerate(timers, 1):
            name = getattr(t, '_fish_name', '') or f"Timer {i}"
            start = getattr(t, '_fish_start', 0)
            total = getattr(t, '_fish_seconds', 0)
            elapsed = time.monotonic() - start
            remaining = max(0, total - elapsed)
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            lines.append(f"{name}: {mins}m {secs}s left")
        return " | ".join(lines)

    def _cancel_timer(self, name: str) -> str:
        """Cancel a timer by name, or all timers if name is empty."""
        timers = getattr(self, '_active_timers', [])
        if not timers:
            return "No active timers to cancel."
        if not name:
            # Cancel all
            for t in timers:
                t.stop()
            self._active_timers = []
            return f"Cancelled all {len(timers)} timer(s)."
        # Cancel by name
        target = name.lower()
        cancelled = []
        remaining = []
        for t in timers:
            t_name = getattr(t, '_fish_name', '').lower()
            if target in t_name:
                t.stop()
                cancelled.append(t)
            else:
                remaining.append(t)
        self._active_timers = remaining
        if cancelled:
            return f"Cancelled {len(cancelled)} timer(s) matching '{name}'."
        return f"No timer found matching '{name}'."

    def _start_pomodoro(self):
        """Start a Pomodoro session: 25 min work, then 5 min break."""
        self._pomodoro_count = getattr(self, '_pomodoro_count', 0) + 1
        count = self._pomodoro_count

        work_timer = QTimer(self)
        work_timer.setSingleShot(True)
        work_timer.setInterval(25 * 60 * 1000)
        work_timer._fish_name = f"pomodoro #{count} (work)"
        work_timer._fish_start = time.monotonic()
        work_timer._fish_seconds = 25 * 60

        def _on_work_done():
            self._say("Pomodoro work phase done! Take a 5-minute break.")
            self._tts.say("Work phase done! Take a break.")
            self.emotions.spike("happy", 0.3)
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self._play_alert_sound()
            if hasattr(self, '_active_timers'):
                self._active_timers = [t for t in self._active_timers if t is not work_timer]
            # Start break timer
            break_timer = QTimer(self)
            break_timer.setSingleShot(True)
            break_timer.setInterval(5 * 60 * 1000)
            break_timer._fish_name = f"pomodoro #{count} (break)"
            break_timer._fish_start = time.monotonic()
            break_timer._fish_seconds = 5 * 60
            break_timer.timeout.connect(lambda: self._on_pomo_break_done(break_timer))
            break_timer.start()
            if not hasattr(self, '_active_timers'):
                self._active_timers = []
            self._active_timers.append(break_timer)

        work_timer.timeout.connect(_on_work_done)
        work_timer.start()
        if not hasattr(self, '_active_timers'):
            self._active_timers = []
        self._active_timers.append(work_timer)
        self._say(f"Pomodoro #{count} started! 25 minutes of focus.")
        self._tts.say(f"Pomodoro {count} started. Focus time!")
        self.emotions.spike("focused", 0.4)

    def _on_pomo_break_done(self, timer):
        self._say("Break's over! Ready for another round?")
        self._tts.say("Break's over! Ready for another round?")
        self.emotions.spike("excited", 0.3)
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self._play_alert_sound()
        if hasattr(self, '_active_timers'):
            self._active_timers = [t for t in self._active_timers if t is not timer]

    def _play_alert_sound(self):
        """Play an alert sound for timer/alarm notifications."""
        try:
            import winsound
            # Play a series of beeps as an alert
            winsound.Beep(800, 200)
            winsound.Beep(1000, 200)
            winsound.Beep(800, 200)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Power actions (with confirmation)
    # ------------------------------------------------------------------

    def _execute_pending_power(self):
        """Execute a confirmed shutdown or restart."""
        import subprocess
        action = getattr(self, '_pending_power', None)
        if not action:
            return
        self._pending_power = None
        if action in ("shutdown", "shut down"):
            self._say("Shutting down... goodbye!")
            self._tts.say("Goodbye!")
            self._quit()
            subprocess.run(["shutdown", "/s", "/t", "5"], shell=True)
        elif action in ("restart", "reboot"):
            self._say("Restarting... see you soon!")
            self._tts.say("See you soon!")
            self._quit()
            subprocess.run(["shutdown", "/r", "/t", "5"], shell=True)

    # ------------------------------------------------------------------
    # Fish Log
    # ------------------------------------------------------------------

    def _show_fish_log(self):
        """Show mood log history in a dialog."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLabel
        log = self._shared_state.read_mood_log()

        dlg = QDialog(self)
        dlg.setWindowTitle("Fish Log")
        dlg.setFixedSize(360, 400)
        dlg.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        dlg.setStyleSheet("""
            QDialog { background-color: #1E2D3D; color: #ECF0F1; }
            QTextEdit { background-color: #2C3E50; color: #ECF0F1;
                        border: 1px solid #5BA8C8; border-radius: 4px;
                        font-family: Consolas; font-size: 11px; }
            QLabel { color: #7EC8E3; font-size: 13px; font-weight: bold; }
        """)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Mood History"))
        text = QTextEdit()
        text.setReadOnly(True)
        if log:
            lines = []
            for entry in reversed(log[-48:]):
                ts = entry.get("time", "?")
                mood = entry.get("mood", "?")
                lines.append(f"{ts}  —  {mood}")
            text.setPlainText("\n".join(lines))
        else:
            text.setPlainText("No mood data logged yet.\nMood is logged every hour.")
        layout.addWidget(text)
        dlg.show()
        self._fish_log_dialog = dlg  # prevent GC

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def _quit(self):
        self._save_config()
        self._write_shared_state()
        self._shared_state.write_stopped()
        self.emotions.save_mood_memory(self._shared_state._interaction_count)
        self.emotions._save_trust()
        self._relationship.record_session_end()
        self._relationship.save()
        self._voice.stop_listening()
        self._tts.stop()
        self._monitor.stop()
        self._monitor.wait(2000)
        self._tray.hide()
        QApplication.quit()

    # ------------------------------------------------------------------
    # Shared state helpers
    # ------------------------------------------------------------------

    def _write_shared_state(self):
        snap = self.emotions.snapshot()
        self._shared_state.write(
            emotions=self.emotions.values,
            dominant=self.emotions.dominant_emotion(),
            is_quiet=self._quiet_mode,
            compound=tuple(snap.get("compound", ())),
            energy=snap.get("energy", 1.0),
            relationship_stage=self._relationship.stage,
            relationship_points=self._relationship.points,
            fish_name=self._user_profile.fish_name or "Little Fish",
        )
        # Check if launcher requested to open settings
        from core.shared_state import STATE_PATH
        flag = STATE_PATH.parent / "open_settings_flag"
        try:
            if flag.exists():
                flag.unlink()
                self._open_settings()
        except OSError:
            pass

    def _log_mood(self):
        self._shared_state.append_mood_log(self.emotions.dominant_emotion())

    # ------------------------------------------------------------------
    # Close override — minimize to tray instead
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    # ------------------------------------------------------------------
    # Monitor signal wiring
    # ------------------------------------------------------------------

    def _connect_monitor_signals(self):
        m = self._monitor
        e = self.emotions
        m.late_night.connect(e.on_late_night)
        m.idle_15min.connect(e.on_idle_15min)
        m.idle_45min.connect(e.on_idle_45min)
        m.user_returned.connect(self._on_user_returned)
        m.code_editor_active.connect(self._on_code_editor_active)
        m.youtube_watching.connect(e.on_youtube_watching)
        m.cpu_high.connect(e.on_cpu_high)
        m.cpu_spike.connect(e.on_cpu_spike)
        m.cpu_spike.connect(self._on_cpu_spike_visual)
        m.battery_low.connect(e.on_battery_low)
        m.battery_plugged.connect(e.on_battery_plugged)
        m.morning_boost.connect(e.on_morning)
        m.monday_detected.connect(e.on_monday)

        # New signals
        m.music_detected.connect(self._on_music_detected)
        m.game_detected.connect(self._on_game_detected)
        m.cpu_normal.connect(self._on_cpu_normal)
        m.battery_full.connect(self._on_battery_full)
        m.ram_high.connect(self._on_ram_high)
        m.usb_connected.connect(self._on_usb_connected)
        m.screen_locked.connect(self._on_screen_locked)
        m.screen_unlocked.connect(self._on_screen_unlocked)
        m.midnight_event.connect(self._on_midnight)
        m.new_hour.connect(self._on_new_hour)
        m.clipboard_changed.connect(e.on_clipboard_changed)
        m.clipboard_content.connect(self._on_clipboard_content)
        m.network_lost.connect(self._on_network_lost)
        m.network_restored.connect(self._on_network_restored)
        m.fullscreen_entered.connect(self._on_fullscreen_entered)
        m.fullscreen_exited.connect(self._on_fullscreen_exited)

    def _on_user_returned(self):
        """User returns from idle — welcome back reaction."""
        self._last_interaction_time = time.monotonic()
        self.emotions.on_user_returned()
        self._behavior_engine.record_interaction()
        self._relationship.add_points("conversation")
        self._say("Hey, welcome back!")
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.spawn_particle("sparkle")
        # Intelligence: record activity + morning briefing
        self._schedule_tracker.record_activity()
        self._check_morning_briefing()

    def _on_music_detected(self):
        self.emotions.on_music_detected()
        self.animator.queue_reaction(ReactionType.NOD)
        self.animator.spawn_particle("music")
        self._music_playing = True

    def _on_game_detected(self):
        self.emotions.on_game_detected()
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.spawn_particle("sparkle")

    def _on_cpu_normal(self):
        self.emotions.on_cpu_normal()
        self.animator.queue_reaction(ReactionType.STRETCH)
        # Clear rage tint
        self.renderer._rage_tint = 0.0

    def _on_cpu_spike_visual(self):
        """Rage shake + red tint on CPU spike."""
        self.animator.queue_reaction(ReactionType.RAGE_SHAKE)
        self.renderer._rage_tint = 1.0
        # Fade out rage tint after 2s
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(2000)
        timer.timeout.connect(lambda: setattr(self.renderer, '_rage_tint', 0.0))
        timer.start()
        self._rage_tint_timer = timer  # prevent GC

    def _on_battery_full(self):
        self.emotions.on_battery_full()
        self.animator.spawn_particle("spark")
        self.animator.spawn_particle("spark")
        self.animator.spawn_particle("sparkle")
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self._say("Fully charged!")

    def _on_ram_high(self):
        self.emotions.on_ram_high()
        self.animator.spawn_particle("sweat")

    def _on_usb_connected(self):
        self.emotions.on_usb_connected()
        self.animator.queue_reaction(ReactionType.HEAD_TILT)
        self.animator.spawn_particle("question")

    def _on_screen_locked(self):
        self.emotions.on_screen_locked()
        self.animator.set_face("sleepy")
        self.animator.trigger_nod_off()
        self.animator.spawn_particle("zzz")

    def _on_screen_unlocked(self):
        self.emotions.on_screen_unlocked()
        self._say("Oh! You're back!")
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self.animator.queue_reaction(ReactionType.STRETCH)
        self.animator.spawn_particle("sparkle")

    def _on_midnight(self):
        self.emotions.on_midnight()
        self.animator.trigger_slow_blink()
        self.animator.trigger_slow_blink()
        self.animator.set_face("sleepy")
        self.animator.spawn_particle("zzz")
        # Day transition — streak and relationship tracking
        self._relationship.save()

    def _on_new_hour(self):
        self.emotions.on_new_hour()
        self.animator.trigger_double_blink()

    def _on_network_lost(self):
        self.emotions.on_network_lost()
        self.animator.spawn_particle("antenna_down")
        self.animator.spawn_particle("sweat")
        self._say("The internet went away...")

    def _on_network_restored(self):
        self.emotions.on_network_restored()
        self.animator.spawn_particle("sparkle")

    def _on_fullscreen_entered(self):
        """Auto-minimize to corner when fullscreen app detected."""
        self.emotions.on_fullscreen_entered()
        self._pre_fullscreen_pos = self.pos()
        screen = self.screen()
        if screen:
            geom = screen.availableGeometry()
            self.move(geom.right() - self.width() - 5,
                      geom.bottom() - self.height() - 5)

    def _on_fullscreen_exited(self):
        """Return to previous position."""
        self.emotions.on_fullscreen_exited()
        if hasattr(self, '_pre_fullscreen_pos'):
            self.move(self._pre_fullscreen_pos)
        self._ensure_on_screen()

    # ------------------------------------------------------------------
    # Intelligence: Clipboard reactions
    # ------------------------------------------------------------------

    def _poll_clipboard(self):
        """Check clipboard from main thread (safe on Windows)."""
        try:
            cb = QApplication.clipboard()
            text = cb.text() or ""
            if text and text != self._last_clip_text and self._last_clip_text:
                self.emotions.on_clipboard_changed()
                self._on_clipboard_content(text)
            self._last_clip_text = text
        except Exception:
            pass

    def _on_clipboard_content(self, text: str):
        """Analyze clipboard content and react accordingly."""
        if not self._clipboard_reactions:
            return
        result = analyze_clipboard(text)
        if result == "code":
            self.emotions.spike("focused", 0.3)
            self.animator.set_face("focused")
            self.animator.spawn_particle("emote_book")
        elif result == "url":
            self.emotions.spike("curious", 0.3)
            self.animator.queue_reaction(ReactionType.HEAD_TILT)
            self.animator.spawn_particle("question")
        elif result == "long_text":
            self.emotions.spike("curious", 0.2)
            self.animator.set_face("focused")

    # ------------------------------------------------------------------
    # Intelligence: App awareness
    # ------------------------------------------------------------------

    def _check_app_awareness(self):
        """Check current foreground app and react with relationship-gated lines."""
        if not self._app_awareness:
            return
        if self._is_user_chatting:
            return  # don't interrupt an active conversation
        try:
            from core.system_monitor import _get_active_process_name, _get_active_window_title
            proc = _get_active_process_name()
            title = _get_active_window_title()
            if not proc and not title:
                return
            rel_stage = self._relationship.stage if self._relationship else "stranger"
            result = self._app_reactor.check(title, proc, rel_stage)
            if result:
                if result["emotion"]:
                    self.emotions.spike(result["emotion"], result["emotion_amount"])
                if result["text"]:
                    self._say(result["text"])
                    self._tts.say(result["text"])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Intelligence: Companion mode
    # ------------------------------------------------------------------

    def _companion_follow_cursor(self):
        """In companion mode, drift slowly toward the cursor."""
        if not self._companion_mode or self._is_dragging:
            return
        if self.emotions.dominant_emotion() == "sleepy":
            return
        cursor = QCursor.pos()
        pos = self.pos()
        center_x = pos.x() + self.width() // 2
        center_y = pos.y() + self.height() // 2
        dx = cursor.x() - center_x
        dy = cursor.y() - center_y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > 150:  # Only follow if cursor is far enough
            speed = 0.8
            nx = pos.x() + int(dx / dist * speed)
            ny = pos.y() + int(dy / dist * speed)
            self.move(nx, ny)

    # ------------------------------------------------------------------
    # Intelligence: Morning briefing
    # ------------------------------------------------------------------

    def _check_morning_briefing(self):
        """Trigger morning briefing on first interaction between 6-10 AM."""
        if not self._briefing_enabled or self._briefing_given_today:
            return
        import datetime
        now = datetime.datetime.now()
        if 6 <= now.hour <= 10:
            weather = self.emotions.weather
            mood = self.emotions.dominant_emotion()
            todo_count = self._todo_list.count_pending()
            msg = generate_morning_briefing(weather, mood, todo_count)
            self._say(msg)
            self._tts.say(msg)
            self._briefing_given_today = True
            self.animator.queue_reaction(ReactionType.BOUNCE)
            self.animator.spawn_particle("sparkle")

    # ------------------------------------------------------------------
    # Intelligence: Jokes / Facts
    # ------------------------------------------------------------------

    def _maybe_tell_joke(self):
        """Randomly tell a joke or fun fact."""
        import random
        if not self._jokes_enabled:
            return
        if self.emotions.dominant_emotion() == "sleepy":
            return
        if self._tts.is_speaking or self._voice.is_recording:
            return
        if self._quiet_mode:
            return
        if self._is_user_chatting:
            return
        joke = get_random_joke_or_fact()
        self._say(joke)
        self._tts.say(joke)
        self.animator.queue_reaction(ReactionType.BOUNCE)
        self._joke_timer.setInterval(random.randint(1800000, 3600000))

    # ------------------------------------------------------------------
    # Intelligence: Chat Window
    # ------------------------------------------------------------------

    @property
    def _is_user_chatting(self) -> bool:
        """True when the chat window is open and the user is actively engaged."""
        return (self._chat_window is not None
                and self._chat_window.isVisible())

    def _open_chat_window(self):
        """Open the text chat window."""
        from widget.chat_window import ChatWindow
        if self._chat_window is None:
            self._chat_window = ChatWindow(self._chat, self)
        if not self._chat_window.isVisible():
            self._chat_window.show()
        self._chat_window.raise_()
        self._chat_window.activateWindow()
