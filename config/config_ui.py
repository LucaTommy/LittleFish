"""
Settings dialog for Little Fish.
Dark-themed PyQt6 panel matching the fish aesthetic.
"""

import sys
import os
import json
from config import load_secrets, save_secrets
import winreg
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QSlider, QLabel, QCheckBox, QComboBox, QPushButton,
    QTabWidget, QWidget, QScrollArea, QLineEdit, QColorDialog,
)


STYLE = """
    QDialog {
        background-color: #1E2D3D;
        color: #ECF0F1;
    }
    QTabWidget::pane {
        border: 1px solid #5BA8C8;
        border-radius: 4px;
        background-color: #1E2D3D;
    }
    QTabBar::tab {
        background: #2C3E50;
        color: #ECF0F1;
        padding: 6px 16px;
        border: 1px solid #5BA8C8;
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        font-size: 12px;
    }
    QTabBar::tab:selected {
        background: #1E2D3D;
        color: #7EC8E3;
        font-weight: bold;
    }
    QGroupBox {
        color: #7EC8E3;
        border: 1px solid #5BA8C8;
        border-radius: 6px;
        margin-top: 12px;
        padding-top: 20px;
        font-weight: bold;
        font-size: 13px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
    }
    QLabel {
        color: #ECF0F1;
        font-size: 12px;
    }
    QSlider::groove:horizontal {
        height: 6px;
        background: #2C3E50;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #7EC8E3;
        width: 14px;
        height: 14px;
        border-radius: 7px;
        margin: -4px 0;
    }
    QSlider::sub-page:horizontal {
        background: #5BA8C8;
        border-radius: 3px;
    }
    QCheckBox {
        color: #ECF0F1;
        font-size: 12px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
    }
    QComboBox {
        background-color: #2C3E50;
        color: #ECF0F1;
        border: 1px solid #5BA8C8;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
    }
    QComboBox::drop-down {
        border: none;
    }
    QComboBox QAbstractItemView {
        background-color: #2C3E50;
        color: #ECF0F1;
        selection-background-color: #7EC8E3;
        selection-color: #1A1A2E;
    }
    QPushButton {
        background-color: #2C3E50;
        color: #ECF0F1;
        border: 1px solid #5BA8C8;
        border-radius: 4px;
        padding: 6px 20px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #5BA8C8;
        color: #1A1A2E;
    }
"""

FACES = ["happy", "bored", "curious", "sleepy", "excited", "worried", "focused", "frustrated", "content"]

APP_NAME = "LittleFish"
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_autostart() -> bool:
    """Check if Little Fish is set to launch on Windows startup."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _set_autostart(enabled: bool):
    """Set or remove Little Fish from Windows startup."""
    if sys.platform != "win32":
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                exe = sys.executable
                script = str(Path(__file__).parent.parent / "main.py")
                # If frozen (PyInstaller), use the exe directly
                if getattr(sys, "frozen", False):
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
                else:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                                      f'"{exe}" "{script}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


class SettingsDialog(QDialog):
    def __init__(self, config: dict, fish_widget):
        super().__init__()
        self._config = config
        self._fish = fish_widget

        self.setWindowTitle("Little Fish — Settings")
        self.setFixedSize(400, 680)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setStyleSheet(STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._build_appearance_tab(), "Appearance")
        tabs.addTab(self._build_permissions_tab(), "Permissions")
        tabs.addTab(self._build_personality_tab(), "Personality")
        tabs.addTab(self._build_intelligence_tab(), "Intelligence")
        tabs.addTab(self._build_apikeys_tab(), "API Keys")
        tabs.addTab(self._build_system_tab(), "System")
        layout.addWidget(tabs)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Tab: Appearance
    # ------------------------------------------------------------------

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        appearance = self._config.get("appearance", {})

        # Size slider
        group = QGroupBox("Appearance")
        form = QFormLayout()
        form.setSpacing(10)

        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(10, 250)
        self._size_slider.setValue(appearance.get("size", 80))
        self._size_label = QLabel(f"{self._size_slider.value()} px")
        self._size_label.setFixedWidth(50)
        size_row = QHBoxLayout()
        size_row.addWidget(self._size_slider)
        size_row.addWidget(self._size_label)
        form.addRow("Size:", size_row)

        # Opacity slider
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 100)
        opacity = appearance.get("opacity", 1.0)
        self._opacity_slider.setValue(int(opacity * 100))
        self._opacity_label = QLabel(f"{self._opacity_slider.value()}%")
        self._opacity_label.setFixedWidth(50)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider)
        opacity_row.addWidget(self._opacity_label)
        form.addRow("Opacity:", opacity_row)

        # Always on top
        self._on_top = QCheckBox("Keep above other windows")
        self._on_top.setChecked(appearance.get("always_on_top", True))
        form.addRow("", self._on_top)

        group.setLayout(form)
        layout.addWidget(group)

        # Customisation group
        custom_group = QGroupBox("Customisation")
        custom_form = QFormLayout()
        custom_form.setSpacing(10)

        # Body color picker
        self._color_btn = QPushButton()
        cur_color = appearance.get("body_color", "#7EC8E3")
        self._color_btn.setStyleSheet(
            f"background-color: {cur_color}; border: 1px solid #5BA8C8; "
            f"border-radius: 4px; min-height: 24px;")
        self._color_btn.clicked.connect(self._on_pick_color)
        custom_form.addRow("Body Color:", self._color_btn)

        # Eye style
        self._eye_combo = QComboBox()
        self._eye_combo.addItems(["default", "round", "dot", "anime", "angry"])
        self._eye_combo.setCurrentText(appearance.get("eye_style", "default"))
        self._eye_combo.currentTextChanged.connect(
            lambda t: self._on_appearance_setting("eye_style", t))
        custom_form.addRow("Eye Style:", self._eye_combo)

        # Mouth style
        self._mouth_combo = QComboBox()
        self._mouth_combo.addItems(["default", "cat", "zigzag", "tiny"])
        self._mouth_combo.setCurrentText(appearance.get("mouth_style", "default"))
        self._mouth_combo.currentTextChanged.connect(
            lambda t: self._on_appearance_setting("mouth_style", t))
        custom_form.addRow("Mouth Style:", self._mouth_combo)

        # Custom name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Little Fish")
        self._name_edit.setMaxLength(20)
        self._name_edit.setText(appearance.get("custom_name", ""))
        self._name_edit.setStyleSheet(
            "background-color: #2C3E50; color: #ECF0F1; border: 1px solid #5BA8C8; "
            "border-radius: 4px; padding: 4px 8px; font-size: 12px;")
        self._name_edit.textChanged.connect(
            lambda t: self._on_appearance_setting("custom_name", t))
        custom_form.addRow("Custom Name:", self._name_edit)

        # Dark border toggle
        self._dark_border_cb = QCheckBox("Dark border")
        self._dark_border_cb.setChecked(appearance.get("dark_border", False))
        self._dark_border_cb.toggled.connect(
            lambda c: self._on_appearance_setting("dark_border", c))
        custom_form.addRow("", self._dark_border_cb)

        # Glow toggle
        self._glow_cb = QCheckBox("Glow effect")
        self._glow_cb.setChecked(appearance.get("glow_enabled", False))
        self._glow_cb.toggled.connect(
            lambda c: self._on_appearance_setting("glow_enabled", c))
        custom_form.addRow("", self._glow_cb)

        # Skin preset
        self._skin_combo = QComboBox()
        self._skin_combo.addItems(["(custom)", "ocean", "sunset", "forest", "midnight", "candy"])
        current_skin = appearance.get("skin_preset", "")
        idx = self._skin_combo.findText(current_skin)
        if idx >= 0:
            self._skin_combo.setCurrentIndex(idx)
        self._skin_combo.currentTextChanged.connect(self._on_skin_preset)
        custom_form.addRow("Skin Preset:", self._skin_combo)

        # Hat
        self._hat_combo = QComboBox()
        self._hat_combo.addItems(["(none)", "top_hat", "beanie", "crown", "propeller",
                                   "cowboy", "wizard", "beret", "pirate", "flower",
                                   "headphones", "halo", "bow"])
        current_hat = appearance.get("hat", "")
        idx = self._hat_combo.findText(current_hat)
        if idx >= 0:
            self._hat_combo.setCurrentIndex(idx)
        self._hat_combo.currentTextChanged.connect(
            lambda t: self._on_appearance_setting("hat", "" if t == "(none)" else t))
        custom_form.addRow("Hat:", self._hat_combo)

        # Tail style
        self._tail_combo = QComboBox()
        self._tail_combo.addItems(["(none)", "fan", "spike", "ribbon"])
        current_tail = appearance.get("tail_style", "")
        idx = self._tail_combo.findText(current_tail)
        if idx >= 0:
            self._tail_combo.setCurrentIndex(idx)
        self._tail_combo.currentTextChanged.connect(
            lambda t: self._on_appearance_setting("tail_style", "" if t == "(none)" else t))
        custom_form.addRow("Tail Style:", self._tail_combo)

        # Sparkle eyes toggle
        self._sparkle_cb = QCheckBox("Sparkle eyes (permanent stars)")
        self._sparkle_cb.setChecked(appearance.get("sparkle_eyes", False))
        self._sparkle_cb.toggled.connect(
            lambda c: self._on_appearance_setting("sparkle_eyes", c))
        custom_form.addRow("", self._sparkle_cb)

        # Shadow toggle
        self._shadow_cb = QCheckBox("Drop shadow")
        self._shadow_cb.setChecked(appearance.get("shadow", False))
        self._shadow_cb.toggled.connect(
            lambda c: self._on_appearance_setting("shadow", c))
        custom_form.addRow("", self._shadow_cb)

        custom_group.setLayout(custom_form)
        layout.addWidget(custom_group)

        # Face preview
        preview_group = QGroupBox("Face Preview")
        preview_layout = QHBoxLayout()
        preview_label = QLabel("Mood:")
        preview_label.setFixedWidth(40)
        preview_layout.addWidget(preview_label)
        self._face_combo = QComboBox()
        self._face_combo.addItems([f.capitalize() for f in FACES])
        preview_layout.addWidget(self._face_combo)
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        layout.addStretch()

        # Connect signals
        self._size_slider.valueChanged.connect(self._on_size)
        self._opacity_slider.valueChanged.connect(self._on_opacity)
        self._on_top.toggled.connect(self._on_always_on_top)
        self._face_combo.currentIndexChanged.connect(self._on_face)

        return tab

    # ------------------------------------------------------------------
    # Tab: Permissions
    # ------------------------------------------------------------------

    def _build_permissions_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        perms = self._config.get("permissions", {})

        group = QGroupBox("Feature Permissions")
        form = QFormLayout()
        form.setSpacing(10)

        self._perm_checks: dict[str, QCheckBox] = {}
        perm_labels = {
            "microphone": "Microphone access",
            "tts": "Text-to-speech",
            "browser_control": "Open URLs / apps",
            "system_monitor": "System monitoring",
            "minigames": "Minigames",
        }

        for key, label in perm_labels.items():
            cb = QCheckBox(label)
            cb.setChecked(perms.get(key, True))
            cb.toggled.connect(lambda checked, k=key: self._on_permission(k, checked))
            form.addRow("", cb)
            self._perm_checks[key] = cb

        group.setLayout(form)
        layout.addWidget(group)

        # Voice settings
        voice_group = QGroupBox("Voice")
        voice_form = QFormLayout()
        voice_form.setSpacing(10)

        voice = self._config.get("voice", {})

        self._tts_enabled = QCheckBox("Enable TTS responses")
        self._tts_enabled.setChecked(voice.get("tts_enabled", True))
        self._tts_enabled.toggled.connect(lambda c: self._on_voice_setting("tts_enabled", c))
        voice_form.addRow("", self._tts_enabled)

        self._whisper_combo = QComboBox()
        self._whisper_combo.addItems(["groq", "local", "off"])
        current_mode = voice.get("whisper_mode", "groq")
        idx = self._whisper_combo.findText(current_mode)
        if idx >= 0:
            self._whisper_combo.setCurrentIndex(idx)
        self._whisper_combo.currentTextChanged.connect(
            lambda t: self._on_voice_setting("whisper_mode", t))
        voice_form.addRow("Transcription:", self._whisper_combo)

        voice_group.setLayout(voice_form)
        layout.addWidget(voice_group)

        # Hotkey settings
        hotkey_group = QGroupBox("Hotkeys")
        hotkey_form = QFormLayout()
        hotkey_form.setSpacing(10)

        voice = self._config.get("voice", {})

        self._ptt_combo = QComboBox()
        ptt_options = ["ctrl_right", "ctrl_left", "alt_right", "f9", "f10", "f11", "f12"]
        self._ptt_combo.addItems(ptt_options)
        current_ptt = voice.get("push_to_talk_key", "ctrl_right")
        idx = self._ptt_combo.findText(current_ptt)
        if idx >= 0:
            self._ptt_combo.setCurrentIndex(idx)
        self._ptt_combo.currentTextChanged.connect(
            lambda t: self._on_voice_setting("push_to_talk_key", t))
        hotkey_form.addRow("Push-to-Talk:", self._ptt_combo)

        self._always_listen_cb = QCheckBox("Always listening (no hotkey needed)")
        self._always_listen_cb.setChecked(voice.get("always_listening", False))
        self._always_listen_cb.toggled.connect(
            lambda c: self._on_voice_setting("always_listening", c))
        hotkey_form.addRow("", self._always_listen_cb)

        hotkey_group.setLayout(hotkey_form)
        layout.addWidget(hotkey_group)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Personality
    # ------------------------------------------------------------------

    def _build_personality_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        personality = self._config.get("personality", {})

        group = QGroupBox("Personality Traits")
        form = QFormLayout()
        form.setSpacing(10)

        self._personality_sliders: dict[str, tuple[QSlider, QLabel]] = {}
        trait_labels = {
            "curiosity_baseline": "Curiosity",
            "boredom_threshold": "Boredom Threshold",
            "attention_seeking": "Attention Seeking",
            "reaction_intensity": "Reaction Intensity",
            "sleep_resistance": "Sleep Resistance",
            "chattiness": "Chattiness",
        }

        for key, label in trait_labels.items():
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(personality.get(key, 0.5) * 100))
            val_label = QLabel(f"{slider.value()}%")
            val_label.setFixedWidth(40)
            row = QHBoxLayout()
            row.addWidget(slider)
            row.addWidget(val_label)
            form.addRow(f"{label}:", row)
            slider.valueChanged.connect(
                lambda v, k=key, lbl=val_label: self._on_personality(k, v, lbl))
            self._personality_sliders[key] = (slider, val_label)

        group.setLayout(form)
        layout.addWidget(group)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: API Keys  (stored locally, never in the repo)
    # ------------------------------------------------------------------

    def _build_apikeys_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel(
            "API keys are stored locally on your computer\n"
            "(%APPDATA%/LittleFish/secrets.json).\n"
            "They are NEVER uploaded to GitHub."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #95a5a6; font-size: 11px; margin-bottom: 6px;")
        layout.addWidget(info)

        # Groq keys
        groq_group = QGroupBox("Groq API Keys")
        groq_layout = QVBoxLayout()
        groq_layout.setSpacing(6)

        secrets = load_secrets()
        existing_keys = secrets.get("groq_keys", [])

        self._groq_key_edits: list[QLineEdit] = []
        for i in range(4):
            row = QHBoxLayout()
            label = QLabel(f"Key {i + 1}:")
            label.setFixedWidth(45)
            edit = QLineEdit()
            edit.setPlaceholderText("gsk_...")
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            if i < len(existing_keys) and existing_keys[i]:
                edit.setText(existing_keys[i])
            self._groq_key_edits.append(edit)
            show_btn = QPushButton("Show")
            show_btn.setFixedWidth(50)
            show_btn.setCheckable(True)
            show_btn.toggled.connect(lambda checked, e=edit, b=show_btn: (
                e.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password),
                b.setText("Hide" if checked else "Show"),
            ))
            row.addWidget(label)
            row.addWidget(edit)
            row.addWidget(show_btn)
            groq_layout.addLayout(row)

        groq_group.setLayout(groq_layout)
        layout.addWidget(groq_group)

        # GitHub token
        gh_group = QGroupBox("GitHub Token (optional — for private repo updates)")
        gh_layout = QVBoxLayout()
        self._gh_token_edit = QLineEdit()
        self._gh_token_edit.setPlaceholderText("ghp_... or github_pat_...")
        self._gh_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        gh_token = secrets.get("github_token", "")
        if gh_token:
            self._gh_token_edit.setText(gh_token)
        gh_layout.addWidget(self._gh_token_edit)
        gh_group.setLayout(gh_layout)
        layout.addWidget(gh_group)

        # Save button
        save_btn = QPushButton("Save API Keys")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; "
            "font-weight: bold; padding: 8px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
        )
        save_btn.clicked.connect(self._on_save_apikeys)
        layout.addWidget(save_btn)

        self._apikeys_status = QLabel("")
        self._apikeys_status.setStyleSheet("color: #2ecc71; font-size: 11px;")
        layout.addWidget(self._apikeys_status)

        layout.addStretch()
        return tab

    def _on_save_apikeys(self):
        secrets = load_secrets()
        keys = [e.text().strip() for e in self._groq_key_edits if e.text().strip()]
        secrets["groq_keys"] = keys
        token = self._gh_token_edit.text().strip()
        if token:
            secrets["github_token"] = token
        else:
            secrets.pop("github_token", None)
        save_secrets(secrets)
        self._apikeys_status.setText(f"Saved! {len(keys)} Groq key(s) stored locally.")

    # ------------------------------------------------------------------
    # Tab: System
    # ------------------------------------------------------------------

    def _build_system_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        group = QGroupBox("Startup")
        form = QFormLayout()
        form.setSpacing(10)

        self._autostart_cb = QCheckBox("Launch on Windows startup")
        self._autostart_cb.setChecked(_get_autostart())
        self._autostart_cb.toggled.connect(self._on_autostart)
        form.addRow("", self._autostart_cb)

        group.setLayout(form)
        layout.addWidget(group)

        # Info
        info_group = QGroupBox("About")
        info_layout = QVBoxLayout()
        info_layout.addWidget(QLabel("Little Fish — your desktop companion"))
        info_layout.addWidget(QLabel("Built with PyQt6 + Groq AI"))
        frozen = getattr(sys, "frozen", False)
        info_layout.addWidget(QLabel(f"Mode: {'Packaged' if frozen else 'Development'}"))
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Reset to defaults
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._on_reset_defaults)
        layout.addWidget(reset_btn)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Intelligence
    # ------------------------------------------------------------------

    def _build_intelligence_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        intelligence = self._config.get("intelligence", {})

        group = QGroupBox("Smart Features")
        form = QFormLayout()
        form.setSpacing(10)

        self._intel_checks: dict[str, QCheckBox] = {}
        intel_labels = {
            "companion_mode": "Companion mode (follows cursor)",
            "clipboard_reactions": "Clipboard reactions (code/URL/text)",
            "app_awareness": "App awareness (react to programs)",
            "todo_list": "Todo list (voice-managed tasks)",
            "morning_briefing": "Morning briefing (daily summary)",
            "jokes": "Jokes & fun facts (periodic)",
            "autonomous_behavior": "Autonomous behavior (idle actions)",
        }

        for key, label in intel_labels.items():
            cb = QCheckBox(label)
            cb.setChecked(intelligence.get(key, False))
            cb.toggled.connect(lambda checked, k=key: self._on_intelligence(k, checked))
            form.addRow("", cb)
            self._intel_checks[key] = cb

        group.setLayout(form)
        layout.addWidget(group)

        # Info box
        info_group = QGroupBox("How It Works")
        info_layout = QVBoxLayout()
        info_layout.addWidget(QLabel("Companion: Fish drifts toward your cursor"))
        info_layout.addWidget(QLabel("Clipboard: Reacts when you copy code/URLs"))
        info_layout.addWidget(QLabel("Apps: Notices Discord, Spotify, games..."))
        info_layout.addWidget(QLabel("Todo: Say 'add todo ...' or 'show todos'"))
        info_layout.addWidget(QLabel("Briefing: Morning summary at day start"))
        info_layout.addWidget(QLabel("Jokes: Random facts & jokes periodically"))
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_size(self, value: int):
        self._size_label.setText(f"{value} px")
        self._config.setdefault("appearance", {})["size"] = value
        self._fish.apply_config()
        self._fish._save_config()

    def _on_opacity(self, value: int):
        self._opacity_label.setText(f"{value}%")
        self._config.setdefault("appearance", {})["opacity"] = value / 100.0
        self._fish.apply_config()
        self._fish._save_config()

    def _on_always_on_top(self, checked: bool):
        self._config.setdefault("appearance", {})["always_on_top"] = checked
        self._fish.apply_config()
        self._fish._save_config()

    def _on_face(self, index: int):
        if 0 <= index < len(FACES):
            self._fish.animator.set_face(FACES[index])

    def _on_pick_color(self):
        cur = self._config.get("appearance", {}).get("body_color", "#7EC8E3")
        color = QColorDialog.getColor(QColor(cur), self, "Pick Body Color")
        if color.isValid():
            hex_color = color.name()
            self._color_btn.setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #5BA8C8; "
                f"border-radius: 4px; min-height: 24px;")
            # Clear skin preset when picking a custom color
            self._config.setdefault("appearance", {})["skin_preset"] = ""
            self._skin_combo.blockSignals(True)
            self._skin_combo.setCurrentIndex(0)  # "(custom)"
            self._skin_combo.blockSignals(False)
            self._on_appearance_setting("body_color", hex_color)

    def _on_appearance_setting(self, key: str, value):
        self._config.setdefault("appearance", {})[key] = value
        self._fish.apply_config()
        self._fish._save_config()

    def _on_permission(self, key: str, checked: bool):
        self._config.setdefault("permissions", {})[key] = checked
        self._fish._save_config()

    def _on_voice_setting(self, key: str, value):
        self._config.setdefault("voice", {})[key] = value
        self._fish._save_config()

    def _on_intelligence(self, key: str, checked: bool):
        self._config.setdefault("intelligence", {})[key] = checked
        self._fish.apply_config()
        self._fish._save_config()

    def _on_skin_preset(self, text: str):
        if text == "(custom)":
            self._on_appearance_setting("skin_preset", "")
        else:
            # Also update body_color to match the preset so it persists
            from widget.renderer import FishRenderer
            hex_color = FishRenderer.SKIN_PRESETS.get(text, "")
            if hex_color:
                self._config.setdefault("appearance", {})["body_color"] = hex_color
                self._color_btn.setStyleSheet(
                    f"background-color: {hex_color}; border: 1px solid #5BA8C8; "
                    f"border-radius: 4px; min-height: 24px;")
            self._on_appearance_setting("skin_preset", text)

    def _on_autostart(self, checked: bool):
        _set_autostart(checked)

    def _on_personality(self, key: str, value: int, label: QLabel):
        label.setText(f"{value}%")
        self._config.setdefault("personality", {})[key] = value / 100.0
        self._fish._save_config()
        # Apply to live personality if emotion engine supports it
        if hasattr(self._fish, 'emotions') and hasattr(self._fish.emotions, 'personality'):
            self._fish.emotions.personality[key] = value / 100.0

    def _on_reset_defaults(self):
        defaults = {
            "appearance": {"size": 80, "opacity": 1.0, "always_on_top": True,
                          "body_color": "#7EC8E3", "eye_style": "default",
                          "mouth_style": "default", "custom_name": "",
                          "dark_border": False, "glow_enabled": False,
                          "skin_preset": "", "hat": "", "tail_style": "",
                          "sparkle_eyes": False, "shadow": False},
            "personality": {
                "curiosity_baseline": 0.6, "boredom_threshold": 0.7,
                "attention_seeking": 0.5, "reaction_intensity": 0.8,
                "sleep_resistance": 0.3, "chattiness": 0.4,
            },
            "permissions": {
                "microphone": True, "tts": True, "browser_control": True,
                "system_monitor": True, "minigames": True,
            },
            "voice": {
                "tts_enabled": True, "whisper_mode": "groq",
                "push_to_talk_key": "ctrl_right", "always_listening": False,
            },
            "intelligence": {
                "companion_mode": False, "clipboard_reactions": False,
                "app_awareness": False, "todo_list": False,
                "morning_briefing": False, "jokes": False,
                "autonomous_behavior": True,
            },
        }
        for section, vals in defaults.items():
            self._config.setdefault(section, {}).update(vals)
        self._fish._save_config()
        self._fish.apply_config()

        # Refresh sliders and checkboxes
        self._size_slider.setValue(80)
        self._opacity_slider.setValue(100)
        self._on_top.setChecked(True)
        self._color_btn.setStyleSheet(
            "background-color: #7EC8E3; border: 1px solid #5BA8C8; "
            "border-radius: 4px; min-height: 24px;")
        self._eye_combo.setCurrentText("default")
        self._mouth_combo.setCurrentText("default")
        self._name_edit.setText("")
        self._dark_border_cb.setChecked(False)
        self._glow_cb.setChecked(False)
        self._skin_combo.setCurrentIndex(0)
        self._hat_combo.setCurrentIndex(0)
        self._tail_combo.setCurrentIndex(0)
        self._sparkle_cb.setChecked(False)
        self._shadow_cb.setChecked(False)
        for key, (slider, _) in self._personality_sliders.items():
            slider.setValue(int(defaults["personality"][key] * 100))
        for key, cb in self._perm_checks.items():
            cb.setChecked(defaults["permissions"].get(key, True))
        for key, cb in self._intel_checks.items():
            cb.setChecked(False)
        self._tts_enabled.setChecked(True)
        self._whisper_combo.setCurrentText("groq")
        self._ptt_combo.setCurrentText("ctrl_right")
        self._always_listen_cb.setChecked(False)


# ---------------------------------------------------------------------------
# Standalone settings dialog (used by launcher when fish is not running)
# ---------------------------------------------------------------------------

from config import CONFIG_PATH as _CONFIG_PATH

CONFIG_PATH = _CONFIG_PATH


class _FakeWidget:
    """Minimal stand-in for fish_widget so SettingsDialog handlers work."""

    def __init__(self, config: dict):
        self._config = config

    def apply_config(self):
        pass

    def _save_config(self):
        try:
            CONFIG_PATH.write_text(
                json.dumps(self._config, indent=2), encoding="utf-8"
            )
        except OSError:
            pass


class StandaloneSettingsDialog(QDialog):
    """Wraps SettingsDialog for use when the fish process is not running."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Little Fish — Settings (offline)")
        self.setFixedSize(420, 700)
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.setStyleSheet(STYLE)

        self._config = config
        self._fake = _FakeWidget(config)

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        inner = SettingsDialog(config, self._fake)
        inner.setWindowFlags(Qt.WindowType.Widget)
        layout.addWidget(inner)

