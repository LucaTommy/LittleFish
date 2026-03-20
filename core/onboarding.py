"""
Onboarding flow for Little Fish.
Runs on first launch (or when invoked from launcher settings).
Collects: age, usage type, chronotype, talkativeness, fish name.
Saves to UserProfile and settings.

Uses PyQt6 for a clean, minimal wizard-style UI.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QRadioButton, QButtonGroup, QWidget, QStackedWidget,
    QSpinBox, QFrame, QSpacerItem, QSizePolicy,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette


# ── Styling ──────────────────────────────────────────────────────────

ONBOARDING_STYLE = """
QDialog {
    background-color: #1a1a2e;
}
QLabel {
    color: #e0e0e0;
    font-size: 13px;
}
QLabel#title {
    color: #7EC8E3;
    font-size: 22px;
    font-weight: bold;
}
QLabel#subtitle {
    color: #a0a0a0;
    font-size: 11px;
}
QLabel#question {
    color: #ffffff;
    font-size: 16px;
    font-weight: bold;
}
QRadioButton {
    color: #d0d0d0;
    font-size: 13px;
    spacing: 8px;
    padding: 6px;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
}
QRadioButton::indicator:checked {
    background-color: #7EC8E3;
    border: 2px solid #5BA8C8;
    border-radius: 8px;
}
QRadioButton::indicator:unchecked {
    background-color: #2a2a3e;
    border: 2px solid #555;
    border-radius: 8px;
}
QLineEdit {
    background-color: #2a2a3e;
    color: #ffffff;
    border: 2px solid #555;
    border-radius: 6px;
    padding: 8px;
    font-size: 14px;
}
QLineEdit:focus {
    border-color: #7EC8E3;
}
QSpinBox {
    background-color: #2a2a3e;
    color: #ffffff;
    border: 2px solid #555;
    border-radius: 6px;
    padding: 8px;
    font-size: 14px;
}
QSpinBox:focus {
    border-color: #7EC8E3;
}
QPushButton#next {
    background-color: #7EC8E3;
    color: #1a1a2e;
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton#next:hover {
    background-color: #5BA8C8;
}
QPushButton#next:disabled {
    background-color: #3a3a4e;
    color: #666;
}
QPushButton#back {
    background-color: transparent;
    color: #888;
    border: 1px solid #555;
    border-radius: 6px;
    padding: 10px 18px;
    font-size: 13px;
}
QPushButton#back:hover {
    color: #ccc;
    border-color: #888;
}
QPushButton#skip {
    background-color: transparent;
    color: #666;
    border: none;
    font-size: 11px;
}
QPushButton#skip:hover {
    color: #999;
}
"""


class OnboardingDialog(QDialog):
    """First-launch onboarding wizard."""

    onboarding_complete = pyqtSignal(dict)  # emits the profile data

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setFixedSize(480, 420)
        self.setStyleSheet(ONBOARDING_STYLE)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._answers = {
            "age": 20,
            "usage": "mixed",
            "chronotype": "normal",
            "talkativeness": "normal",
            "fish_name": "Little Fish",
        }

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 25, 30, 20)

        # Stack of pages
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack)

        # Build each page
        self._stack.addWidget(self._build_welcome_page())      # 0
        self._stack.addWidget(self._build_age_page())           # 1
        self._stack.addWidget(self._build_usage_page())         # 2
        self._stack.addWidget(self._build_chronotype_page())    # 3
        self._stack.addWidget(self._build_talkativeness_page()) # 4
        self._stack.addWidget(self._build_name_page())          # 5
        self._stack.addWidget(self._build_done_page())          # 6

        # Navigation
        nav_layout = QHBoxLayout()

        self._back_btn = QPushButton("Back")
        self._back_btn.setObjectName("back")
        self._back_btn.clicked.connect(self._go_back)
        nav_layout.addWidget(self._back_btn)

        nav_layout.addStretch()

        self._skip_btn = QPushButton("Skip setup")
        self._skip_btn.setObjectName("skip")
        self._skip_btn.clicked.connect(self._skip)
        nav_layout.addWidget(self._skip_btn)

        self._next_btn = QPushButton("Next")
        self._next_btn.setObjectName("next")
        self._next_btn.clicked.connect(self._go_next)
        nav_layout.addWidget(self._next_btn)

        main_layout.addLayout(nav_layout)

        self._update_nav()

    # ── Page builders ─────────────────────────────────────────────

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addStretch()

        title = QLabel("Hey.")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(10)

        sub = QLabel("I'm your new desktop companion.\nLet me learn a few things about you\nso I can be less... generic.")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        layout.addSpacing(8)

        note = QLabel("(This takes 30 seconds. You can change it all later.)")
        note.setObjectName("subtitle")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)

        layout.addStretch()
        return page

    def _build_age_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addStretch()

        q = QLabel("How old are you?")
        q.setObjectName("question")
        layout.addWidget(q)

        sub = QLabel("This changes my humor, references, and energy level.\nNot stored anywhere except locally.")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        layout.addSpacing(15)

        self._age_spin = QSpinBox()
        self._age_spin.setRange(10, 99)
        self._age_spin.setValue(20)
        self._age_spin.setFixedWidth(120)
        self._age_spin.valueChanged.connect(lambda v: self._answers.update({"age": v}))
        layout.addWidget(self._age_spin)

        layout.addStretch()
        return page

    def _build_usage_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addStretch()

        q = QLabel("What do you mostly use your computer for?")
        q.setObjectName("question")
        q.setWordWrap(True)
        layout.addWidget(q)

        sub = QLabel("I'll pay attention to the right things.")
        sub.setObjectName("subtitle")
        layout.addWidget(sub)

        layout.addSpacing(10)

        self._usage_group = QButtonGroup(page)
        options = [
            ("Work / Productivity", "work"),
            ("Gaming", "gaming"),
            ("Creative stuff (design, video, music)", "creative"),
            ("Mostly browsing", "browsing"),
            ("A mix of everything", "mixed"),
        ]
        for text, value in options:
            rb = QRadioButton(text)
            rb.toggled.connect(lambda checked, v=value: checked and self._answers.update({"usage": v}))
            self._usage_group.addButton(rb)
            layout.addWidget(rb)
            if value == "mixed":
                rb.setChecked(True)

        layout.addStretch()
        return page

    def _build_chronotype_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addStretch()

        q = QLabel("When are you most alive?")
        q.setObjectName("question")
        layout.addWidget(q)

        sub = QLabel("I'll match your energy schedule.")
        sub.setObjectName("subtitle")
        layout.addWidget(sub)

        layout.addSpacing(10)

        self._chrono_group = QButtonGroup(page)
        options = [
            ("Early bird — I'm up and running by 7am", "early_bird"),
            ("Normal — peak hours are 9-5ish", "normal"),
            ("Night owl — I come alive after dark", "night_owl"),
        ]
        for text, value in options:
            rb = QRadioButton(text)
            rb.toggled.connect(lambda checked, v=value: checked and self._answers.update({"chronotype": v}))
            self._chrono_group.addButton(rb)
            layout.addWidget(rb)
            if value == "normal":
                rb.setChecked(True)

        layout.addStretch()
        return page

    def _build_talkativeness_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addStretch()

        q = QLabel("How much should I talk?")
        q.setObjectName("question")
        layout.addWidget(q)

        sub = QLabel("I can be chatty, or I can shut up and just exist.")
        sub.setObjectName("subtitle")
        layout.addWidget(sub)

        layout.addSpacing(10)

        self._talk_group = QButtonGroup(page)
        options = [
            ("Quiet — just exist, speak when spoken to", "quiet"),
            ("Normal — pop up sometimes, not too much", "normal"),
            ("Chatty — talk to me, I want the company", "chatty"),
        ]
        for text, value in options:
            rb = QRadioButton(text)
            rb.toggled.connect(lambda checked, v=value: checked and self._answers.update({"talkativeness": v}))
            self._talk_group.addButton(rb)
            layout.addWidget(rb)
            if value == "normal":
                rb.setChecked(True)

        layout.addStretch()
        return page

    def _build_name_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addStretch()

        q = QLabel("What should I call myself?")
        q.setObjectName("question")
        layout.addWidget(q)

        sub = QLabel("You can rename me, or keep it classic.")
        sub.setObjectName("subtitle")
        layout.addWidget(sub)

        layout.addSpacing(15)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Little Fish")
        self._name_input.setMaxLength(30)
        self._name_input.setFixedWidth(250)
        self._name_input.textChanged.connect(
            lambda t: self._answers.update({"fish_name": t.strip() or "Little Fish"})
        )
        layout.addWidget(self._name_input)

        layout.addStretch()
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addStretch()

        title = QLabel("Got it.")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(10)

        self._done_label = QLabel("")
        self._done_label.setObjectName("subtitle")
        self._done_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_label.setWordWrap(True)
        layout.addWidget(self._done_label)

        layout.addStretch()
        return page

    # ── Navigation ────────────────────────────────────────────────

    def _go_next(self):
        current = self._stack.currentIndex()
        total = self._stack.count() - 1

        if current == total:
            # Done — save and close
            self.onboarding_complete.emit(self._answers)
            self.accept()
            return

        if current == total - 1:
            # About to show done page — update summary
            name = self._answers.get("fish_name", "Little Fish")
            self._done_label.setText(
                f"I'm {name} now.\n"
                f"I'll adapt to how you work and when you're awake.\n\n"
                f"Let's go."
            )
            self._next_btn.setText("Start")

        self._stack.setCurrentIndex(current + 1)
        self._update_nav()

    def _go_back(self):
        current = self._stack.currentIndex()
        if current > 0:
            self._stack.setCurrentIndex(current - 1)
            self._next_btn.setText("Next")
            self._update_nav()

    def _skip(self):
        """Skip onboarding with defaults."""
        self.onboarding_complete.emit(self._answers)
        self.accept()

    def _update_nav(self):
        current = self._stack.currentIndex()
        total = self._stack.count() - 1
        self._back_btn.setVisible(current > 0)
        self._skip_btn.setVisible(current < total)

        if current == total:
            self._next_btn.setText("Start")
        else:
            self._next_btn.setText("Next")


def run_onboarding(parent=None) -> dict | None:
    """
    Show the onboarding dialog. Returns profile dict if completed, None if dismissed.
    """
    result = {}

    dialog = OnboardingDialog(parent)

    def on_complete(data):
        nonlocal result
        result = data

    dialog.onboarding_complete.connect(on_complete)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        return result
    return None
