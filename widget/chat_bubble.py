"""
Pixel-art chat bubble widget for Little Fish.
A frameless, transparent popup that appears above the fish with a pixelated look.
Text renders in a pixel font style, auto-wraps, and fades out after a delay.
"""

from PyQt6.QtCore import Qt, QTimer, QPoint, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen
from PyQt6.QtWidgets import QWidget


# Pixel palette — matches the fish theme
BUBBLE_BG = QColor("#2C3E50")
BUBBLE_BORDER = QColor("#5BA8C8")
BUBBLE_TEXT = QColor("#ECF0F1")
BUBBLE_TAIL = QColor("#2C3E50")
BUBBLE_TAIL_BORDER = QColor("#5BA8C8")

# Sizing
PADDING = 10
MAX_WIDTH = 220
TAIL_SIZE = 6
CORNER_RADIUS = 2       # pixel-art: very small radius
BORDER_WIDTH = 2

# Timing
DISPLAY_MS_PER_CHAR = 80    # how long to show, scales with text length
DISPLAY_MIN_MS = 2500
DISPLAY_MAX_MS = 8000
FADE_MS = 400


class ChatBubble(QWidget):
    """Pixel-art speech bubble that floats above the fish."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._text = ""
        self._lines: list[str] = []
        self._bubble_rect = QRect()
        self._opacity = 1.0

        # Font — small, monospaced to feel pixel-y
        self._font = QFont("Consolas", 9)
        self._font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self._font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)

        # Auto-hide timer
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade)

        # Fade animation
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_remaining = 0.0

        # Message queue — messages that arrive while already showing are held here
        self._queue: list[tuple[str, QPoint]] = []
        self._showing = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_message(self, text: str, anchor: QPoint):
        """
        Show a chat bubble with the given text, anchored above the given point.
        If already visible, queues the message to display after the current one.
        anchor = the top-center of the fish widget in global coords.
        """
        if self._showing:
            self._queue.append((text, anchor))
            return
        self._show_now(text, anchor)

    def _show_now(self, text: str, anchor: QPoint):
        """Internal: immediately render and display a bubble."""
        self._showing = True
        self._text = text
        self._opacity = 1.0
        self._fade_timer.stop()

        # Word-wrap text
        fm = QFontMetrics(self._font)
        self._lines = self._wrap_text(text, fm, MAX_WIDTH - PADDING * 2)

        # Calculate bubble size
        line_h = fm.height()
        text_w = max(fm.horizontalAdvance(ln) for ln in self._lines) if self._lines else 40
        text_h = line_h * len(self._lines)

        bw = text_w + PADDING * 2
        bh = text_h + PADDING * 2

        total_w = bw + BORDER_WIDTH * 2
        total_h = bh + BORDER_WIDTH * 2 + TAIL_SIZE

        self.setFixedSize(total_w, total_h)

        # Position above anchor (fish top-center)
        x = anchor.x() - total_w // 2
        y = anchor.y() - total_h - 4

        # Keep on screen
        screen = QWidget().screen()
        if screen:
            sg = screen.availableGeometry()
            x = max(sg.left() + 2, min(x, sg.right() - total_w - 2))
            y = max(sg.top() + 2, y)

        self.move(x, y)

        self._bubble_rect = QRect(BORDER_WIDTH, BORDER_WIDTH, bw, bh)

        # Show and start hide timer
        self.show()
        self.raise_()

        duration = max(DISPLAY_MIN_MS, min(len(text) * DISPLAY_MS_PER_CHAR, DISPLAY_MAX_MS))
        self._hide_timer.start(duration)

    def dismiss(self):
        """Immediately hide the bubble and clear the pending queue."""
        self._hide_timer.stop()
        self._fade_timer.stop()
        self._queue.clear()
        self._showing = False
        self.hide()

    def update_anchor(self, anchor: QPoint):
        """Reposition an already-visible bubble to track the fish."""
        if not self._showing:
            return
        total_w = self.width()
        total_h = self.height()
        x = anchor.x() - total_w // 2
        y = anchor.y() - total_h - 4
        # Keep on screen
        screen = self.screen()
        if screen:
            sg = screen.availableGeometry()
            x = max(sg.left() + 2, min(x, sg.right() - total_w - 2))
            y = max(sg.top() + 2, y)
        self.move(x, y)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)

        # Clear
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        p.setOpacity(self._opacity)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        r = self._bubble_rect

        # --- Border (drawn slightly larger) ---
        border_rect = r.adjusted(-BORDER_WIDTH, -BORDER_WIDTH, BORDER_WIDTH, BORDER_WIDTH)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BUBBLE_BORDER)
        p.drawRoundedRect(border_rect, CORNER_RADIUS + 1, CORNER_RADIUS + 1)

        # --- Fill ---
        p.setBrush(BUBBLE_BG)
        p.drawRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)

        # --- Tail (small triangle at bottom-center) ---
        cx = self.width() // 2
        ty = r.bottom() + BORDER_WIDTH

        # Tail border pixels
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BUBBLE_BORDER)
        for i in range(TAIL_SIZE + 1):
            hw = TAIL_SIZE - i  # half-width narrows as we go down
            if hw >= 0:
                p.fillRect(cx - hw - 1, ty + i, hw * 2 + 3, 1, BUBBLE_BORDER)
        # Tail fill
        for i in range(TAIL_SIZE):
            hw = TAIL_SIZE - i - 1
            if hw >= 0:
                p.fillRect(cx - hw, ty + i, hw * 2 + 1, 1, BUBBLE_BG)

        # --- Text ---
        p.setPen(QPen(BUBBLE_TEXT))
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        line_h = fm.height()
        tx = r.left() + PADDING
        ty_text = r.top() + PADDING + fm.ascent()

        for i, line in enumerate(self._lines):
            p.drawText(tx, ty_text + i * line_h, line)

        p.end()

    # ------------------------------------------------------------------
    # Text wrapping
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_text(text: str, fm: QFontMetrics, max_w: int) -> list[str]:
        """Simple word-wrap."""
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip() if current else word
            if fm.horizontalAdvance(test) <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    # ------------------------------------------------------------------
    # Fade out
    # ------------------------------------------------------------------

    def _start_fade(self):
        self._fade_remaining = FADE_MS
        self._fade_timer.start()

    def _fade_step(self):
        self._fade_remaining -= 16
        if self._fade_remaining <= 0:
            self._fade_timer.stop()
            self.hide()
            self._opacity = 1.0
            self._showing = False
            # Show next queued message if any
            if self._queue:
                text, anchor = self._queue.pop(0)
                self._show_now(text, anchor)
        else:
            self._opacity = max(0.0, self._fade_remaining / FADE_MS)
            self.update()
