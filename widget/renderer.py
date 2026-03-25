"""
QPainter pixel art renderer for Little Fish.
Renders at low internal resolution (32x32), then scaled up with nearest-neighbor.
No antialiasing — every shape is crisp pixel art.
"""

from PyQt6.QtCore import QRect, QRectF, Qt, QPointF
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPen, QBrush, QPainterPath, QImage

from widget.animator import Animator


# ---------------------------------------------------------------------------
# Internal pixel resolution
# ---------------------------------------------------------------------------

PIXEL_CANVAS = 32    # total canvas including padding
PIXEL_BODY = 24      # the fish body square
PIXEL_PAD = 4        # padding on each side: (32 - 24) / 2


# ---------------------------------------------------------------------------
# Default colour palette
# ---------------------------------------------------------------------------

BODY_BASE = QColor("#7EC8E3")
BODY_LIGHT = QColor("#A8D8EA")
BODY_BORDER = QColor("#5BA8C8")
BODY_SHADOW = QColor("#4A9BB8")

EYE_WHITE = QColor("#FFFFFF")
EYE_OUTLINE = QColor("#2C3E50")
PUPIL_COLOR = QColor("#1A1A2E")
MOUTH_COLOR = QColor("#2C3E50")
STAR_COLOR = QColor("#FFD700")

# Alternate eye styles: "default", "round", "dot", "anime", "angry"
# Alternate mouth styles: "default", "cat", "zigzag", "tiny"

# ---------------------------------------------------------------------------
# Geometry — all coordinates in internal 32x32 canvas space
# Body occupies (4,4) to (27,27) inclusive
# ---------------------------------------------------------------------------

B = PIXEL_PAD  # body origin x and y

# Eye rects: (x, y, w, h)
L_EYE = QRect(B + 5, B + 7, 4, 5)
R_EYE = QRect(B + 15, B + 7, 4, 5)

# Default pupil top-left of 2x2
L_PUPIL_X, L_PUPIL_Y = B + 6, B + 9
R_PUPIL_X, R_PUPIL_Y = B + 16, B + 9

# Mouth baseline
MOUTH_Y = B + 17
MOUTH_CX = PIXEL_CANVAS // 2   # horizontal center = 16


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class FishRenderer:
    """Renders Little Fish at internal pixel resolution."""

    def __init__(self):
        self._pixmap = QPixmap(PIXEL_CANVAS, PIXEL_CANVAS)
        self._gaze_dx: float = 0.0
        self._gaze_dy: float = 0.0
        self._is_talking: bool = False
        self._talk_frame: int = 0  # alternates 0/1 for open/close mouth
        self._clock_eyes: bool = False

        # Customisable appearance
        self._body_color: QColor = BODY_BASE
        self._body_light: QColor = BODY_LIGHT
        self._body_border: QColor = BODY_BORDER
        self._body_shadow: QColor = BODY_SHADOW
        self._eye_style: str = "default"   # default, round, dot, anime, angry
        self._mouth_style: str = "default" # default, cat, zigzag, tiny
        self._dark_border: bool = False
        self._glow_enabled: bool = False
        self._rage_tint: float = 0.0  # 0.0 = no tint, 1.0 = full red
        self._sparkle_eyes: bool = False
        self._shadow_enabled: bool = False
        self._hat: str = ""  # "", "top_hat", "beanie", "crown", "propeller"
        self._tail_style: str = ""  # "", "fan", "spike", "ribbon"
        self._skin_preset: str = ""  # "", "ocean", "sunset", "forest", "midnight", "candy"
        self._custom_name: str = ""
        self._show_name: bool = True
        self._hobby_tint = None  # QColor or None — set during hobby scenes
        self._suppress_prop = False  # True when hobby scene renders its own prop
        self._desaturation_amount: float = 0.0  # 0.0 = full color, 1.0 = full grayscale
        self._union_break: bool = False      # Feature 2: sleep mask over eyes
        self._silent_treatment: bool = False  # Feature 4: whiteboard prop
        self._surfing: bool = False          # Window Surfing: dangling legs

    def set_body_color(self, hex_color: str):
        """Set the fish body color from a hex string, auto-deriving variants."""
        base = QColor(hex_color)
        if not base.isValid():
            return
        self._body_color = base
        h, s, l, _ = base.getHslF()
        self._body_light = QColor.fromHslF(h, max(0, s - 0.1), min(1, l + 0.15))
        self._body_border = QColor.fromHslF(h, min(1, s + 0.05), max(0, l - 0.1))
        self._body_shadow = QColor.fromHslF(h, min(1, s + 0.05), max(0, l - 0.15))

    SKIN_PRESETS = {
        "ocean":    "#7EC8E3",
        "sunset":   "#E8835A",
        "forest":   "#6BBF6A",
        "midnight": "#7070B0",
        "candy":    "#E88BCB",
    }

    def apply_skin_preset(self, preset: str):
        """Apply a named skin preset."""
        hex_color = self.SKIN_PRESETS.get(preset)
        if hex_color:
            self.set_body_color(hex_color)

    def set_gaze(self, dx: float, dy: float):
        """Set gaze direction: dx/dy in range [-1.0, 1.0]."""
        self._gaze_dx = max(-1.0, min(1.0, dx))
        self._gaze_dy = max(-1.0, min(1.0, dy))

    def set_eye_offset(self, dx: int, dy: int):
        """Convenience: set gaze from pixel offset (-3..3) → normalized."""
        self.set_gaze(dx / 3.0, dy / 3.0)

    def set_talking(self, talking: bool):
        """Toggle talking mouth animation."""
        if talking and not self._is_talking:
            self._talk_frame = 0
        self._is_talking = talking

    def advance_talk_frame(self):
        """Call periodically (~150ms) to toggle mouth open/close."""
        self._talk_frame = 1 - self._talk_frame

    def render_pixmap(self, animator, seasonal_event: str | None = None) -> QPixmap:
        """Render one frame at PIXEL_CANVAS resolution. Returns the pixmap."""
        self._pixmap.fill(QColor(0, 0, 0, 0))
        p = QPainter(self._pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Shadow below body
        if self._shadow_enabled:
            self._draw_shadow(p)

        # Tail behind body
        if self._tail_style:
            self._draw_tail(p, self._tail_style)

        self._draw_body(p)

        # Dangling legs when surfing on window borders
        if self._surfing:
            self._draw_surfing_legs(p)

        _, face, _ = animator.get_face_blend()
        blink = animator.blink.progress

        # Sparkle eyes override excited face with permanent stars
        if self._sparkle_eyes and face != "excited":
            self._eyes_star(p, blink)
            self._draw_mouth(p, "_smile")
        else:
            self._draw_face(p, face, blink)

        # Hat on top of head
        if self._hat:
            self._draw_hat(p, self._hat)

        # Seasonal costume overlay (only if no custom hat)
        if seasonal_event and not self._hat:
            self._draw_costume(p, seasonal_event)

        # Custom name below fish
        if self._custom_name and self._show_name:
            self._draw_name(p, self._custom_name)

        # Animation prop overlay (coffee cup, book, umbrella, etc.)
        if hasattr(animator, 'active_prop') and animator.active_prop is not None:
            if not self._suppress_prop:
                self._draw_prop(p, animator.active_prop)

        # Union break: sleep mask over eyes
        if self._union_break:
            self._draw_sleep_mask(p)

        # Silent treatment: whiteboard prop
        if self._silent_treatment:
            self._draw_whiteboard(p)

        # Particles (drawn after face, around body)
        if hasattr(animator, 'particles'):
            self._draw_particles(p, animator.particles)

        # Rage tint overlay
        if self._rage_tint > 0:
            a = int(80 * self._rage_tint)
            p.fillRect(0, 0, PIXEL_CANVAS, PIXEL_CANVAS, QColor(255, 30, 30, a))

        # Hobby mood tint overlay — skip; tint is conveyed by scene props
        # (was drawing a visible square around the fish)

        p.end()

        # Grayscale desaturation overlay (sad/lonely)
        if self._desaturation_amount > 0.01:
            self._apply_desaturation()

        return self._pixmap

    # ------------------------------------------------------------------
    # Grayscale desaturation
    # ------------------------------------------------------------------

    def _apply_desaturation(self):
        """Blend the current pixmap toward grayscale by _desaturation_amount."""
        amt = max(0.0, min(1.0, self._desaturation_amount))
        img = self._pixmap.toImage()
        gray = img.convertToFormat(QImage.Format.Format_Grayscale8)
        gray = gray.convertToFormat(img.format())
        # Composite: paint the grayscale image over the color one with
        # opacity equal to the desaturation amount.
        result = QImage(img)
        gp = QPainter(result)
        gp.setOpacity(amt)
        gp.drawImage(0, 0, gray)
        gp.end()
        self._pixmap = QPixmap.fromImage(result)

    # ------------------------------------------------------------------
    # Union break: sleep mask
    # ------------------------------------------------------------------

    def _draw_sleep_mask(self, p: QPainter):
        """Draw a tiny sleep mask (two black rectangles) over the eye positions."""
        mask_color = QColor(30, 30, 40)
        strap_color = QColor(50, 50, 60)
        # Strap across the head
        p.fillRect(B + 3, B + 8, PIXEL_BODY - 6, 1, strap_color)
        # Left eye mask
        p.fillRect(L_EYE.x() - 1, L_EYE.y(), L_EYE.width() + 2, L_EYE.height(), mask_color)
        # Right eye mask
        p.fillRect(R_EYE.x() - 1, R_EYE.y(), R_EYE.width() + 2, R_EYE.height(), mask_color)

    # ------------------------------------------------------------------
    # Silent treatment: whiteboard
    # ------------------------------------------------------------------

    def _draw_whiteboard(self, p: QPainter):
        """Draw a tiny whiteboard held in front of the fish body."""
        # Position: slightly left of center, in front of body
        wx = B + 2
        wy = B + PIXEL_BODY - 8
        ww, wh = 8, 6
        # Black border
        p.fillRect(wx - 1, wy - 1, ww + 2, wh + 2, QColor(30, 30, 30))
        # White fill
        p.fillRect(wx, wy, ww, wh, QColor(240, 240, 240))

    # ------------------------------------------------------------------
    # Window Surfing: dangling legs
    # ------------------------------------------------------------------

    def _draw_surfing_legs(self, p: QPainter):
        """Draw dangling legs below body when surfing on window borders."""
        import math as _math
        import time as _time

        sway = int(_math.sin(_time.time() * 2.0) * 1)  # slight sway

        leg_color = self._body_border
        shoe_color = QColor(60, 60, 70)

        ly = B + PIXEL_BODY  # bottom of body
        # Left leg (1px wide, 3px + 1px shoe)
        lx = B + 7 + sway
        p.fillRect(lx, ly, 1, 3, leg_color)
        p.fillRect(lx, ly + 3, 1, 1, shoe_color)
        # Right leg
        rx = B + 16 - sway
        p.fillRect(rx, ly, 1, 3, leg_color)
        p.fillRect(rx, ly + 3, 1, 1, shoe_color)

    # ------------------------------------------------------------------
    # Body
    # ------------------------------------------------------------------

    def _draw_body(self, p: QPainter):
        bx, by = B, B
        bw, bh = PIXEL_BODY, PIXEL_BODY

        # Glow effect
        if self._glow_enabled:
            glow = QColor(self._body_color)
            glow.setAlpha(60)
            p.fillRect(bx - 1, by - 1, bw + 2, bh + 2, glow)

        border = self._body_border
        if self._dark_border:
            border = QColor("#1A1A2E")

        # Outer border with pixel-rounded corners
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(border))
        p.drawRoundedRect(bx, by, bw, bh, 3, 3)

        # Inner fill
        inner = QRect(bx + 1, by + 1, bw - 2, bh - 2)
        p.setBrush(QBrush(self._body_color))
        p.drawRoundedRect(inner, 2, 2)

        # Top highlight (bevel)
        p.setPen(QPen(self._body_light, 1))
        p.drawLine(bx + 3, by + 1, bx + bw - 4, by + 1)
        # Left highlight
        p.drawLine(bx + 1, by + 3, bx + 1, by + bh - 4)

        # Bottom shadow
        p.setPen(QPen(self._body_shadow, 1))
        p.drawLine(bx + 3, by + bh - 2, bx + bw - 4, by + bh - 2)
        # Right shadow
        p.drawLine(bx + bw - 2, by + 3, bx + bw - 2, by + bh - 4)

    # ------------------------------------------------------------------
    # Shadow
    # ------------------------------------------------------------------

    def _draw_shadow(self, p: QPainter):
        """Draw a translucent shadow ellipse below the fish body."""
        c = QColor(0, 0, 0, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(c))
        p.drawEllipse(B + 3, B + PIXEL_BODY + 1, PIXEL_BODY - 6, 4)

    # ------------------------------------------------------------------
    # Tail
    # ------------------------------------------------------------------

    def _draw_tail(self, p: QPainter, style: str):
        """Draw a tail extending from the right side of the body."""
        bx = B + PIXEL_BODY  # right edge of body
        by = B + PIXEL_BODY // 2  # vertical center
        c = self._body_color
        dark = self._body_border
        if style == "fan":
            # Fan-shaped tail
            p.fillRect(bx, by - 3, 2, 7, c)
            p.fillRect(bx + 2, by - 4, 1, 9, c)
            p.fillRect(bx + 3, by - 5, 1, 11, dark)
        elif style == "spike":
            # Pointed spike tail
            p.fillRect(bx, by - 1, 1, 3, c)
            p.fillRect(bx + 1, by - 1, 1, 2, c)
            p.fillRect(bx + 2, by, 1, 1, dark)
            p.fillRect(bx, by - 3, 1, 1, dark)
            p.fillRect(bx + 1, by - 2, 1, 1, dark)
            p.fillRect(bx, by + 3, 1, 1, dark)
            p.fillRect(bx + 1, by + 2, 1, 1, dark)
        elif style == "ribbon":
            # Flowing ribbon tail
            p.fillRect(bx, by - 1, 1, 3, c)
            p.fillRect(bx + 1, by, 1, 2, c)
            p.fillRect(bx + 2, by + 1, 1, 2, c)
            p.fillRect(bx + 3, by, 1, 2, c)
            p.fillRect(bx + 4, by - 1, 1, 2, dark)

    # ------------------------------------------------------------------
    # Hat
    # ------------------------------------------------------------------

    def _draw_hat(self, p: QPainter, hat: str):
        """Draw a persistent accessory hat on the fish."""
        if hat == "top_hat":
            c = QColor(30, 30, 40)
            band = QColor(160, 40, 40)
            p.fillRect(B + 4, B - 1, 16, 2, c)    # brim
            p.fillRect(B + 6, B - 5, 12, 4, c)     # crown
            p.fillRect(B + 6, B - 2, 12, 1, band)   # band
        elif hat == "beanie":
            c = QColor(200, 60, 60)
            p.fillRect(B + 5, B, 14, 2, c)
            p.fillRect(B + 6, B - 1, 12, 1, c)
            p.fillRect(B + 7, B - 2, 10, 1, c)
            p.fillRect(B + 8, B - 3, 8, 1, c)
            # Fold line
            p.fillRect(B + 5, B + 1, 14, 1, QColor(170, 40, 40))
        elif hat == "crown":
            gold = QColor(255, 215, 0)
            dark_gold = QColor(200, 170, 0)
            p.fillRect(B + 5, B, 14, 2, gold)
            # Crown points
            p.fillRect(B + 5, B - 1, 2, 1, gold)
            p.fillRect(B + 10, B - 2, 4, 2, gold)
            p.fillRect(B + 17, B - 1, 2, 1, gold)
            # Gems
            p.fillRect(B + 11, B, 2, 1, QColor(200, 40, 40))
            p.fillRect(B + 6, B, 1, 1, dark_gold)
        elif hat == "propeller":
            c = QColor(100, 180, 255)
            cap = QColor(255, 200, 60)
            p.fillRect(B + 6, B, 12, 1, c)
            p.fillRect(B + 7, B - 1, 10, 1, c)
            # Propeller blades
            p.fillRect(B + 4, B - 2, 4, 1, QColor(255, 100, 100))
            p.fillRect(B + 16, B - 2, 4, 1, QColor(100, 100, 255))
            # Hub
            p.fillRect(B + 11, B - 2, 2, 1, cap)
        elif hat == "cowboy":
            c = QColor(160, 120, 60)
            dark = QColor(120, 85, 40)
            p.fillRect(B + 2, B, 20, 1, c)        # wide brim
            p.fillRect(B + 3, B - 1, 18, 1, dark)  # brim shadow
            p.fillRect(B + 7, B - 4, 10, 3, c)     # crown
            p.fillRect(B + 8, B - 5, 8, 1, c)      # top
            p.fillRect(B + 7, B - 2, 10, 1, dark)   # band
        elif hat == "wizard":
            c = QColor(80, 60, 140)
            star = QColor(255, 215, 0)
            p.fillRect(B + 5, B, 14, 2, c)          # base
            p.fillRect(B + 7, B - 2, 10, 2, c)      # mid
            p.fillRect(B + 9, B - 4, 6, 2, c)       # upper
            p.fillRect(B + 10, B - 6, 4, 2, c)      # top
            p.fillRect(B + 11, B - 7, 2, 1, c)      # tip
            p.fillRect(B + 8, B - 1, 2, 1, star)    # star
        elif hat == "beret":
            c = QColor(50, 50, 60)
            p.fillRect(B + 4, B, 16, 1, c)          # band
            p.fillRect(B + 3, B - 1, 16, 1, c)      # puff left
            p.fillRect(B + 4, B - 2, 14, 1, c)      # puff mid
            p.fillRect(B + 6, B - 3, 10, 1, c)      # puff top
            p.fillRect(B + 11, B - 3, 1, 1, QColor(80, 80, 90))  # nub
        elif hat == "pirate":
            c = QColor(30, 30, 30)
            skull = QColor(230, 230, 230)
            p.fillRect(B + 4, B, 16, 1, c)          # band
            p.fillRect(B + 5, B - 1, 14, 1, c)
            p.fillRect(B + 6, B - 2, 12, 1, c)
            p.fillRect(B + 7, B - 3, 10, 1, c)
            p.fillRect(B + 8, B - 4, 8, 1, c)
            p.fillRect(B + 11, B - 1, 2, 1, skull)  # skull
            p.fillRect(B + 10, B, 1, 1, skull)       # crossbone
            p.fillRect(B + 13, B, 1, 1, skull)       # crossbone
        elif hat == "flower":
            stem = QColor(80, 160, 60)
            petal = QColor(255, 120, 160)
            center = QColor(255, 200, 60)
            p.fillRect(B + 12, B - 2, 1, 3, stem)   # stem
            p.fillRect(B + 11, B - 4, 1, 2, petal)   # petals
            p.fillRect(B + 13, B - 4, 1, 2, petal)
            p.fillRect(B + 10, B - 3, 1, 1, petal)
            p.fillRect(B + 14, B - 3, 1, 1, petal)
            p.fillRect(B + 12, B - 5, 1, 1, petal)
            p.fillRect(B + 12, B - 3, 1, 1, center)  # center
        elif hat == "headphones":
            c = QColor(60, 60, 70)
            pad = QColor(40, 40, 50)
            p.fillRect(B + 6, B - 2, 12, 1, c)      # band top
            p.fillRect(B + 5, B - 1, 2, 1, c)        # left arm
            p.fillRect(B + 17, B - 1, 2, 1, c)       # right arm
            p.fillRect(B + 4, B, 3, 3, pad)           # left cup
            p.fillRect(B + 17, B, 3, 3, pad)          # right cup
        elif hat == "halo":
            gold = QColor(255, 215, 0, 200)
            p.fillRect(B + 6, B - 3, 12, 1, gold)
            p.fillRect(B + 5, B - 2, 1, 1, gold)
            p.fillRect(B + 18, B - 2, 1, 1, gold)
            p.fillRect(B + 5, B - 4, 1, 1, gold)
            p.fillRect(B + 18, B - 4, 1, 1, gold)
            p.fillRect(B + 6, B - 5, 12, 1, gold)
        elif hat == "bow":
            c = QColor(230, 80, 120)
            dark = QColor(180, 50, 80)
            p.fillRect(B + 5, B - 1, 4, 2, c)        # left ribbon
            p.fillRect(B + 15, B - 1, 4, 2, c)       # right ribbon
            p.fillRect(B + 9, B - 1, 6, 2, dark)     # center knot
            p.fillRect(B + 6, B - 2, 2, 1, c)        # left flare
            p.fillRect(B + 16, B - 2, 2, 1, c)       # right flare

    # ------------------------------------------------------------------
    # Name display
    # ------------------------------------------------------------------

    def _draw_name(self, p: QPainter, name: str):
        """Draw the custom name below the fish in tiny pixel text."""
        from PyQt6.QtGui import QFont
        p.setPen(QPen(QColor(230, 230, 255, 200)))
        font = QFont("Consolas", 3)
        font.setPixelSize(4)
        p.setFont(font)
        # Center below body
        text_width = len(name) * 3
        tx = max(0, PIXEL_CANVAS // 2 - text_width // 2)
        p.drawText(tx, PIXEL_CANVAS - 1, name[:10])

    # ------------------------------------------------------------------
    # Face dispatch
    # ------------------------------------------------------------------

    def _draw_face(self, p: QPainter, state: str, blink: float):
        # Clock eyes override
        if self._clock_eyes:
            self._eyes_clock(p, blink)
            self._draw_mouth(p, "_smile")
            return

        # If talking, override mouth regardless of face state
        if self._is_talking:
            fn = {
                "happy":      self._face_happy,
                "bored":      self._face_bored,
                "curious":    self._face_curious,
                "sleepy":     self._face_sleepy,
                "excited":    self._face_excited,
                "worried":    self._face_worried,
                "focused":    self._face_focused,
                "frustrated": self._face_frustrated,
                "content":    self._face_content,
            }.get(state, self._face_happy)
            fn(p, blink)
            self._mouth_talking(p)
        else:
            fn = {
                "happy":      self._face_happy,
                "bored":      self._face_bored,
                "curious":    self._face_curious,
                "sleepy":     self._face_sleepy,
                "excited":    self._face_excited,
                "worried":    self._face_worried,
                "focused":    self._face_focused,
                "frustrated": self._face_frustrated,
                "content":    self._face_content,
            }.get(state, self._face_happy)
            fn(p, blink)

    def _draw_eyes(self, p: QPainter, blink: float, **kwargs):
        """Dispatch eyes based on current eye style."""
        style_fn = {
            "round": self._eyes_round,
            "dot":   self._eyes_dot,
            "anime": self._eyes_anime,
            "angry": self._eyes_angry,
        }.get(self._eye_style)
        if style_fn:
            style_fn(p, blink, **kwargs)
        else:
            self._eyes(p, blink, **kwargs)

    def _draw_mouth(self, p: QPainter, default: str):
        """Dispatch mouth based on current mouth style, falling back to default."""
        style_fn = {
            "cat":    self._mouth_cat,
            "zigzag": self._mouth_zigzag,
            "tiny":   self._mouth_tiny,
        }.get(self._mouth_style)
        if style_fn:
            style_fn(p)
        else:
            # Use the default mouth for this face state
            {
                "_smile": self._mouth_smile,
                "_flat":  self._mouth_flat,
                "_flat_narrow": lambda p: self._mouth_flat(p, width=4),
                "_flat_wide":   lambda p: self._mouth_flat(p, width=5),
                "_o":     self._mouth_o,
                "_wide":  self._mouth_wide,
                "_wavy":  self._mouth_wavy,
            }.get(default, self._mouth_smile)(p)

    # ------------------------------------------------------------------
    # Face states
    # ------------------------------------------------------------------

    def _face_happy(self, p: QPainter, blink: float):
        self._draw_eyes(p, blink)
        self._draw_mouth(p, "_smile")

    def _face_bored(self, p: QPainter, blink: float):
        self._draw_eyes(p, max(blink, 0.50))
        self._draw_mouth(p, "_flat")

    def _face_curious(self, p: QPainter, blink: float):
        self._draw_eyes(p, blink, grow=1)
        self._draw_mouth(p, "_o")

    def _face_sleepy(self, p: QPainter, blink: float):
        self._draw_eyes(p, max(blink, 0.82))
        self._draw_mouth(p, "_flat_narrow")

    def _face_excited(self, p: QPainter, blink: float):
        self._eyes_star(p, blink)
        self._draw_mouth(p, "_wide")

    def _face_worried(self, p: QPainter, blink: float):
        self._draw_eyes(p, blink)
        self._brows_worried(p)
        self._draw_mouth(p, "_wavy")

    def _face_focused(self, p: QPainter, blink: float):
        self._draw_eyes(p, blink)
        self._brows_focused(p)
        self._draw_mouth(p, "_flat_wide")

    def _face_frustrated(self, p: QPainter, blink: float):
        """Angry-ish narrowed eyes with angled brows + frown."""
        self._eyes_angry(p, blink)
        self._mouth_frown(p)

    def _face_content(self, p: QPainter, blink: float):
        """Relaxed half-closed eyes + gentle smile."""
        self._draw_eyes(p, max(blink, 0.35))
        self._draw_mouth(p, "_smile")

    # ------------------------------------------------------------------
    # Eyes
    # ------------------------------------------------------------------

    def _eyes(self, p: QPainter, blink: float, grow: int = 0, shrink_h: int = 0):
        """Draw both eyes with blink, gaze offset, and optional size adjustments."""
        # Whole-eye shift based on gaze direction
        eye_shift_x = int(self._gaze_dx * 2)
        eye_shift_y = int(self._gaze_dy * 1.5)
        # Additional pupil offset within the eye
        pupil_extra_x = 1 if self._gaze_dx > 0.2 else (-1 if self._gaze_dx < -0.2 else 0)
        pupil_extra_y = 1 if self._gaze_dy > 0.2 else (-1 if self._gaze_dy < -0.2 else 0)

        for eye, (px, py) in [(L_EYE, (L_PUPIL_X, L_PUPIL_Y)),
                               (R_EYE, (R_PUPIL_X, R_PUPIL_Y))]:
            ew = eye.width() + grow
            eh = eye.height() + grow - shrink_h
            vis_h = max(1, int(eh * (1.0 - blink)))

            # Center vertically on eye position, applying gaze shift
            cy = eye.y() + eye.height() // 2 + eye_shift_y
            ey = cy - vis_h // 2
            ex = eye.x() - grow // 2 + eye_shift_x

            # Outline (fill whole rect)
            p.fillRect(ex, ey, ew, vis_h, EYE_OUTLINE)
            # White interior
            if vis_h > 2 and ew > 2:
                p.fillRect(ex + 1, ey + 1, ew - 2, vis_h - 2, EYE_WHITE)

            # Pupil with gaze offset
            if vis_h >= 3:
                ppx = px - grow // 2 + eye_shift_x + pupil_extra_x
                ppy = max(ey + 1, min(py + eye_shift_y + pupil_extra_y, ey + vis_h - 3))
                # Clamp horizontally within eye white
                ppx = max(ex + 1, min(ppx, ex + ew - 3))
                p.fillRect(ppx, ppy, 2, 2, PUPIL_COLOR)

    def _eyes_star(self, p: QPainter, blink: float):
        """Sparkle eyes for excited state."""
        if blink > 0.5:
            self._eyes(p, blink)
            return

        eye_shift_x = int(self._gaze_dx * 2)
        eye_shift_y = int(self._gaze_dy * 1.5)

        for eye in [L_EYE, R_EYE]:
            cx = eye.x() + eye.width() // 2 + eye_shift_x
            cy = eye.y() + eye.height() // 2 + eye_shift_y
            # Plus shape
            p.fillRect(cx - 2, cy, 5, 1, STAR_COLOR)
            p.fillRect(cx, cy - 2, 1, 5, STAR_COLOR)
            # Corner accents
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                p.fillRect(cx + dx, cy + dy, 1, 1, STAR_COLOR)

    def _eyes_clock(self, p: QPainter, blink: float):
        """Clock symbol eyes (used for new-hour blink)."""
        if blink > 0.5:
            self._eyes(p, blink)
            return

        eye_shift_x = int(self._gaze_dx * 2)
        eye_shift_y = int(self._gaze_dy * 1.5)

        for eye in [L_EYE, R_EYE]:
            cx = eye.x() + eye.width() // 2 + eye_shift_x
            cy = eye.y() + eye.height() // 2 + eye_shift_y
            # Clock circle outline
            c = QColor("#5BA8C8")
            p.fillRect(cx - 1, cy - 2, 3, 1, c)
            p.fillRect(cx - 2, cy - 1, 1, 3, c)
            p.fillRect(cx + 2, cy - 1, 1, 3, c)
            p.fillRect(cx - 1, cy + 2, 3, 1, c)
            # Clock hands
            p.fillRect(cx, cy, 1, 1, PUPIL_COLOR)
            p.fillRect(cx, cy - 1, 1, 1, PUPIL_COLOR)  # hour hand up
            p.fillRect(cx + 1, cy, 1, 1, PUPIL_COLOR)   # minute hand right

    def _eyes_round(self, p: QPainter, blink: float, grow: int = 0, shrink_h: int = 0):
        """Round 3x3 eyes with single-pixel pupil."""
        eye_shift_x = int(self._gaze_dx * 2)
        eye_shift_y = int(self._gaze_dy * 1.5)
        for eye, (px, py) in [(L_EYE, (L_PUPIL_X, L_PUPIL_Y)),
                               (R_EYE, (R_PUPIL_X, R_PUPIL_Y))]:
            cx = eye.x() + eye.width() // 2 + eye_shift_x
            cy = eye.y() + eye.height() // 2 + eye_shift_y
            vis_h = max(1, int(3 * (1.0 - blink)))
            ey = cy - vis_h // 2
            # Circle outline
            p.fillRect(cx - 1, ey, 3, vis_h, EYE_OUTLINE)
            if vis_h > 2:
                p.fillRect(cx - 1, ey + 1, 3, vis_h - 2, EYE_WHITE)
                # Single-pixel pupil
                pupil_dx = 1 if self._gaze_dx > 0.3 else (-1 if self._gaze_dx < -0.3 else 0)
                p.fillRect(cx + pupil_dx, cy, 1, 1, PUPIL_COLOR)

    def _eyes_dot(self, p: QPainter, blink: float, grow: int = 0, shrink_h: int = 0):
        """Simple 2x2 dot eyes."""
        eye_shift_x = int(self._gaze_dx * 2)
        eye_shift_y = int(self._gaze_dy * 1.5)
        if blink > 0.7:
            # Blink → thin line
            for eye in [L_EYE, R_EYE]:
                cx = eye.x() + eye.width() // 2 + eye_shift_x
                cy = eye.y() + eye.height() // 2 + eye_shift_y
                p.fillRect(cx - 1, cy, 2, 1, PUPIL_COLOR)
            return
        for eye in [L_EYE, R_EYE]:
            cx = eye.x() + eye.width() // 2 + eye_shift_x
            cy = eye.y() + eye.height() // 2 + eye_shift_y
            p.fillRect(cx - 1, cy - 1, 2, 2, PUPIL_COLOR)

    def _eyes_anime(self, p: QPainter, blink: float, grow: int = 0, shrink_h: int = 0):
        """Larger anime-style eyes with highlight."""
        eye_shift_x = int(self._gaze_dx * 2)
        eye_shift_y = int(self._gaze_dy * 1.5)
        for eye, (px, py) in [(L_EYE, (L_PUPIL_X, L_PUPIL_Y)),
                               (R_EYE, (R_PUPIL_X, R_PUPIL_Y))]:
            ew, eh = 5, 6
            vis_h = max(1, int(eh * (1.0 - blink)))
            cx = eye.x() + eye.width() // 2 + eye_shift_x
            cy = eye.y() + eye.height() // 2 + eye_shift_y
            ex = cx - ew // 2
            ey = cy - vis_h // 2
            p.fillRect(ex, ey, ew, vis_h, EYE_OUTLINE)
            if vis_h > 2 and ew > 2:
                p.fillRect(ex + 1, ey + 1, ew - 2, vis_h - 2, EYE_WHITE)
            if vis_h >= 4:
                # Large pupil
                ppx = cx - 1 + (1 if self._gaze_dx > 0.2 else (-1 if self._gaze_dx < -0.2 else 0))
                ppy = cy + (1 if self._gaze_dy > 0.2 else (-1 if self._gaze_dy < -0.2 else 0))
                ppx = max(ex + 1, min(ppx, ex + ew - 3))
                ppy = max(ey + 1, min(ppy, ey + vis_h - 3))
                p.fillRect(ppx, ppy, 2, 2, PUPIL_COLOR)
                # Highlight
                p.fillRect(ppx, ppy, 1, 1, QColor(255, 255, 255, 180))

    def _eyes_angry(self, p: QPainter, blink: float, grow: int = 0, shrink_h: int = 0):
        """Narrow eyes with angled brows."""
        self._eyes(p, max(blink, 0.4), shrink_h=2)
        # Angry brows — angled downward toward center
        lx = L_EYE.x()
        ly = L_EYE.y() - 2
        p.fillRect(lx - 1, ly, 1, 1, MOUTH_COLOR)
        p.fillRect(lx, ly + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(lx + 1, ly + 1, 1, 1, MOUTH_COLOR)
        rx = R_EYE.x() + R_EYE.width() - 2
        ry = R_EYE.y() - 2
        p.fillRect(rx, ry + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(rx + 1, ry + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(rx + 2, ry, 1, 1, MOUTH_COLOR)

    # ------------------------------------------------------------------
    # Mouth
    # ------------------------------------------------------------------

    def _mouth_smile(self, p: QPainter):
        """Upward pixel curve."""
        cx = MOUTH_CX
        p.fillRect(cx - 3, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx,     MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 1, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 2, MOUTH_Y, 1, 1, MOUTH_COLOR)

    def _mouth_flat(self, p: QPainter, width: int = 6):
        """Flat horizontal pixel line."""
        cx = MOUTH_CX
        p.fillRect(cx - width // 2, MOUTH_Y, width, 1, MOUTH_COLOR)

    def _mouth_o(self, p: QPainter):
        """Small hollow O for curious."""
        cx = MOUTH_CX
        # 3x3 hollow square
        p.fillRect(cx - 1, MOUTH_Y, 3, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y + 2, 3, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 1, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)

    def _mouth_wide(self, p: QPainter):
        """Wide smile for excited."""
        cx = MOUTH_CX
        p.fillRect(cx - 4, MOUTH_Y - 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 3, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx,     MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 1, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 2, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 3, MOUTH_Y - 1, 1, 1, MOUTH_COLOR)

    def _mouth_wavy(self, p: QPainter):
        """Wavy pixel line for worried."""
        cx = MOUTH_CX
        p.fillRect(cx - 3, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx,     MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 1, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)

    def _mouth_frown(self, p: QPainter):
        """Downward pixel curve — inverted smile for frustrated/angry."""
        cx = MOUTH_CX
        p.fillRect(cx - 3, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 2, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx,     MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 1, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)

    def _mouth_cat(self, p: QPainter):
        """Cat-like W-shaped mouth."""
        cx = MOUTH_CX
        p.fillRect(cx - 3, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 1, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)

    def _mouth_zigzag(self, p: QPainter):
        """Zigzag mouth line."""
        cx = MOUTH_CX
        p.fillRect(cx - 3, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 2, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx - 1, MOUTH_Y, 1, 1, MOUTH_COLOR)
        p.fillRect(cx, MOUTH_Y + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(cx + 1, MOUTH_Y, 1, 1, MOUTH_COLOR)

    def _mouth_tiny(self, p: QPainter):
        """Single pixel mouth."""
        p.fillRect(MOUTH_CX, MOUTH_Y, 1, 1, MOUTH_COLOR)

    def _brows_worried(self, p: QPainter):
        """Angled inner-up pixel brows."""
        # Left brow: rises toward center
        lx = L_EYE.x()
        ly = L_EYE.y() - 2
        p.fillRect(lx - 1, ly + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(lx,     ly,     1, 1, MOUTH_COLOR)
        p.fillRect(lx + 1, ly,     1, 1, MOUTH_COLOR)

        # Right brow: rises toward center (mirror)
        rx = R_EYE.x() + R_EYE.width() - 2
        ry = R_EYE.y() - 2
        p.fillRect(rx,     ry,     1, 1, MOUTH_COLOR)
        p.fillRect(rx + 1, ry,     1, 1, MOUTH_COLOR)
        p.fillRect(rx + 2, ry + 1, 1, 1, MOUTH_COLOR)

    def _brows_focused(self, p: QPainter):
        """Flat/slightly lowered brows showing concentration."""
        # Left brow: slightly angled down toward center
        lx = L_EYE.x()
        ly = L_EYE.y() - 2
        p.fillRect(lx - 1, ly,     1, 1, MOUTH_COLOR)
        p.fillRect(lx,     ly,     1, 1, MOUTH_COLOR)
        p.fillRect(lx + 1, ly,     1, 1, MOUTH_COLOR)
        p.fillRect(lx + 2, ly + 1, 1, 1, MOUTH_COLOR)

        # Right brow: mirror (angled down toward center)
        rx = R_EYE.x() + R_EYE.width() - 3
        ry = R_EYE.y() - 2
        p.fillRect(rx - 1, ry + 1, 1, 1, MOUTH_COLOR)
        p.fillRect(rx,     ry,     1, 1, MOUTH_COLOR)
        p.fillRect(rx + 1, ry,     1, 1, MOUTH_COLOR)
        p.fillRect(rx + 2, ry,     1, 1, MOUTH_COLOR)

    def _mouth_talking(self, p: QPainter):
        """Alternating open/close rect for talking."""
        cx = MOUTH_CX
        # Clear mouth area first (overdraw body color)
        p.fillRect(cx - 4, MOUTH_Y - 1, 9, 4, self._body_color)
        if self._talk_frame == 0:
            # Open mouth — small rect
            p.fillRect(cx - 2, MOUTH_Y, 5, 3, MOUTH_COLOR)
            p.fillRect(cx - 1, MOUTH_Y + 1, 3, 1, QColor("#C0392B"))  # tongue hint
        else:
            # Closed mouth — flat line
            p.fillRect(cx - 2, MOUTH_Y + 1, 5, 1, MOUTH_COLOR)

    # ------------------------------------------------------------------
    # Seasonal costume overlays
    # ------------------------------------------------------------------

    def _draw_costume(self, p: QPainter, event: str):
        """Draw a seasonal costume overlay on top of the fish body."""
        if event in ("Christmas", "Christmas Eve"):
            # Santa hat — red triangle with white trim on top of head
            hat_color = QColor(200, 30, 30)
            trim_color = QColor(255, 255, 255)
            # Hat body (trapezoid-ish)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(hat_color))
            p.fillRect(B + 4, B - 1, 16, 1, hat_color)
            p.fillRect(B + 5, B - 2, 14, 1, hat_color)
            p.fillRect(B + 6, B - 3, 12, 1, hat_color)
            p.fillRect(B + 7, B - 4, 10, 1, hat_color)
            p.fillRect(B + 8, B - 5, 8, 1, hat_color)
            p.fillRect(B + 9, B - 6, 6, 1, hat_color)
            p.fillRect(B + 10, B - 7, 4, 1, hat_color)
            # White trim at base
            p.fillRect(B + 3, B, 18, 2, trim_color)
            # White pompom at tip
            p.fillRect(B + 10, B - 8, 3, 2, trim_color)

        elif event == "Halloween":
            # Witch hat — dark purple triangle
            hat_color = QColor(60, 20, 80)
            brim_color = QColor(40, 10, 60)
            p.setPen(Qt.PenStyle.NoPen)
            # Hat cone
            p.fillRect(B + 6, B - 1, 12, 1, hat_color)
            p.fillRect(B + 7, B - 2, 10, 1, hat_color)
            p.fillRect(B + 8, B - 3, 8, 1, hat_color)
            p.fillRect(B + 9, B - 4, 6, 1, hat_color)
            p.fillRect(B + 10, B - 5, 4, 1, hat_color)
            p.fillRect(B + 11, B - 6, 2, 1, hat_color)
            # Wide brim
            p.fillRect(B + 2, B, 20, 2, brim_color)

        elif event in ("New Year", "New Year's Eve"):
            # Party hat — gold/yellow cone
            hat_color = QColor(255, 215, 0)
            p.setPen(Qt.PenStyle.NoPen)
            p.fillRect(B + 7, B - 1, 10, 1, hat_color)
            p.fillRect(B + 8, B - 2, 8, 1, hat_color)
            p.fillRect(B + 9, B - 3, 6, 1, hat_color)
            p.fillRect(B + 10, B - 4, 4, 1, hat_color)
            p.fillRect(B + 11, B - 5, 2, 1, hat_color)
            # Star on top
            p.fillRect(B + 11, B - 7, 2, 1, QColor(255, 255, 200))
            p.fillRect(B + 10, B - 6, 4, 1, QColor(255, 255, 200))
            p.fillRect(B + 11, B - 5, 2, 1, QColor(255, 255, 200))

        elif event == "Valentine's Day":
            # Small bow on head
            bow_color = QColor(255, 100, 130)
            p.setPen(Qt.PenStyle.NoPen)
            p.fillRect(B + 3, B, 3, 2, bow_color)
            p.fillRect(B + 4, B - 1, 1, 1, bow_color)
            p.fillRect(B + 7, B, 3, 2, bow_color)
            p.fillRect(B + 8, B - 1, 1, 1, bow_color)
            # Center knot
            p.fillRect(B + 6, B, 1, 2, QColor(200, 60, 90))

        elif event == "Birthday":
            # Birthday hat — colorful cone
            p.setPen(Qt.PenStyle.NoPen)
            colors = [QColor(255, 100, 100), QColor(100, 200, 255), QColor(255, 220, 100)]
            for i, row_y in enumerate(range(B - 1, B - 6, -1)):
                c = colors[i % len(colors)]
                w = 12 - i * 2
                x_start = B + 6 + i
                p.fillRect(x_start, row_y, w, 1, c)
            # Star on top
            p.fillRect(B + 11, B - 7, 2, 2, QColor(255, 255, 100))

    # ------------------------------------------------------------------
    # Particles
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Animation props
    # ------------------------------------------------------------------

    def _draw_prop(self, p: QPainter, prop):
        """Draw an animation prop overlaid on/near the fish."""
        from core.animation_library import AnimProp

        if prop == AnimProp.COFFEE_CUP:
            # Coffee mug held near left side — visible cup, handle, cream, steam
            cup_dark = QColor(160, 100, 45)
            cup_main = QColor(190, 130, 70)
            cup_hi   = QColor(210, 160, 100)
            cream    = QColor(245, 230, 200)
            steam    = QColor(220, 220, 230, 130)
            x, y = B - 3, B + 11
            # Cup body 5×6
            p.fillRect(x, y, 5, 6, cup_main)
            p.fillRect(x, y, 5, 1, cup_dark)              # rim
            p.fillRect(x, y + 5, 5, 1, cup_dark)          # base
            p.fillRect(x + 4, y, 1, 6, cup_dark)          # right edge
            p.fillRect(x + 1, y + 1, 1, 4, cup_hi)       # highlight
            # Handle
            p.fillRect(x + 5, y + 1, 1, 1, cup_dark)
            p.fillRect(x + 6, y + 1, 1, 3, cup_dark)
            p.fillRect(x + 5, y + 3, 1, 1, cup_dark)
            # Cream surface
            p.fillRect(x + 1, y + 1, 3, 1, cream)
            # Steam wisps
            p.fillRect(x + 1, y - 1, 1, 1, steam)
            p.fillRect(x + 2, y - 2, 1, 1, steam)
            p.fillRect(x + 3, y - 1, 1, 1, steam)
            p.fillRect(x + 1, y - 3, 1, 1, QColor(220, 220, 230, 80))

        elif prop == AnimProp.TINY_BOOK:
            # Open book held below — two pages, spine, text lines
            cover_l = QColor(90, 130, 190)
            cover_r = QColor(110, 150, 210)
            page    = QColor(245, 240, 225)
            spine   = QColor(60, 90, 150)
            text    = QColor(140, 130, 110, 160)
            x, y = B + 2, B + 19
            # Covers
            p.fillRect(x, y, 5, 6, cover_l)
            p.fillRect(x + 6, y, 5, 6, cover_r)
            # Pages
            p.fillRect(x + 1, y + 1, 4, 4, page)
            p.fillRect(x + 6, y + 1, 4, 4, page)
            # Spine
            p.fillRect(x + 5, y, 1, 6, spine)
            # Tiny text lines
            p.fillRect(x + 1, y + 2, 3, 1, text)
            p.fillRect(x + 1, y + 4, 2, 1, text)
            p.fillRect(x + 7, y + 2, 3, 1, text)
            p.fillRect(x + 7, y + 4, 2, 1, text)

        elif prop == AnimProp.BLANKET:
            # Cozy blanket draped over lower half with pattern
            blanket  = QColor(130, 110, 190, 210)
            edge     = QColor(100, 80, 160, 230)
            fold     = QColor(150, 130, 210, 180)
            pattern  = QColor(170, 150, 220, 150)
            p.fillRect(B - 2, B + 13, PIXEL_BODY + 4, 12, blanket)
            p.fillRect(B - 2, B + 13, PIXEL_BODY + 4, 1, edge)   # top edge
            p.fillRect(B - 2, B + 24, PIXEL_BODY + 4, 1, edge)   # bottom edge
            # Fold creases
            p.fillRect(B + 2, B + 16, 7, 1, fold)
            p.fillRect(B + 14, B + 18, 6, 1, fold)
            p.fillRect(B + 5, B + 21, 8, 1, fold)
            # Diamond pattern
            p.fillRect(B + 10, B + 15, 1, 1, pattern)
            p.fillRect(B + 9, B + 16, 1, 1, pattern)
            p.fillRect(B + 11, B + 16, 1, 1, pattern)
            p.fillRect(B + 10, B + 17, 1, 1, pattern)

        elif prop == AnimProp.UMBRELLA:
            # Umbrella held above — curved canopy with ribs and handle
            canopy    = QColor(60, 140, 210)
            dark      = QColor(40, 100, 170)
            highlight = QColor(90, 170, 240)
            handle    = QColor(130, 95, 55)
            # Canopy arc (wider, more dome-like)
            p.fillRect(B + 3, B - 6, 18, 1, dark)
            p.fillRect(B + 1, B - 5, 22, 1, canopy)
            p.fillRect(B + 0, B - 4, 24, 1, canopy)
            p.fillRect(B + 1, B - 3, 22, 1, canopy)
            p.fillRect(B + 3, B - 2, 18, 1, dark)
            # Rib lines
            p.fillRect(B + 6, B - 5, 1, 3, dark)
            p.fillRect(B + 12, B - 6, 1, 4, dark)
            p.fillRect(B + 18, B - 5, 1, 3, dark)
            # Highlight on canopy
            p.fillRect(B + 8, B - 5, 3, 1, highlight)
            # Handle (shaft + curve)
            p.fillRect(B + 12, B - 1, 1, 5, handle)
            p.fillRect(B + 11, B + 3, 1, 1, handle)       # hook start
            p.fillRect(B + 10, B + 4, 1, 1, handle)       # hook end

        elif prop == AnimProp.SUNGLASSES:
            # Cool aviator sunglasses on face
            frame     = QColor(25, 25, 30)
            lens_dark = QColor(30, 30, 50, 220)
            lens_mid  = QColor(50, 50, 80, 200)
            highlight = QColor(120, 120, 150, 140)
            ly = B + 8
            # Left lens (bigger, 6×4)
            p.fillRect(B + 4, ly, 7, 4, frame)
            p.fillRect(B + 5, ly + 1, 5, 2, lens_dark)
            p.fillRect(B + 5, ly + 1, 2, 1, highlight)    # glare
            p.fillRect(B + 8, ly + 2, 2, 1, lens_mid)     # gradient
            # Right lens
            p.fillRect(B + 13, ly, 7, 4, frame)
            p.fillRect(B + 14, ly + 1, 5, 2, lens_dark)
            p.fillRect(B + 14, ly + 1, 2, 1, highlight)
            p.fillRect(B + 17, ly + 2, 2, 1, lens_mid)
            # Bridge
            p.fillRect(B + 11, ly + 1, 2, 1, frame)
            # Temple arms
            p.fillRect(B + 3, ly + 1, 1, 1, frame)
            p.fillRect(B + 20, ly + 1, 1, 1, frame)

        elif prop == AnimProp.TINY_WEIGHTS:
            # Dumbbell held above — chunky plates with bar
            bar       = QColor(140, 140, 150)
            bar_hi    = QColor(170, 170, 180)
            plate     = QColor(70, 70, 80)
            plate_hi  = QColor(100, 100, 110)
            x, y = B + 2, B - 4
            # Bar
            p.fillRect(x + 4, y + 2, 12, 1, bar)
            p.fillRect(x + 4, y + 2, 12, 1, bar_hi)
            # Left weight plates (stacked)
            p.fillRect(x, y, 2, 5, plate)
            p.fillRect(x + 2, y + 1, 2, 3, plate)
            p.fillRect(x + 1, y + 1, 1, 3, plate_hi)     # highlight
            # Right weight plates
            p.fillRect(x + 16, y + 1, 2, 3, plate)
            p.fillRect(x + 18, y, 2, 5, plate)
            p.fillRect(x + 17, y + 1, 1, 3, plate_hi)

        elif prop == AnimProp.SNACK:
            # Cookie held near left — round with chips and crumbs
            cookie   = QColor(215, 175, 105)
            cookie_d = QColor(190, 150, 80)
            chip     = QColor(120, 80, 35)
            chip_l   = QColor(90, 55, 25)
            x, y = B - 4, B + 13
            # Cookie body (rounder shape)
            p.fillRect(x + 1, y, 4, 1, cookie_d)
            p.fillRect(x, y + 1, 6, 3, cookie)
            p.fillRect(x + 1, y + 4, 4, 1, cookie_d)
            # Highlight
            p.fillRect(x + 1, y + 1, 2, 1, QColor(230, 195, 130))
            # Chocolate chips
            p.fillRect(x + 2, y + 1, 1, 1, chip)
            p.fillRect(x + 4, y + 2, 1, 1, chip_l)
            p.fillRect(x + 1, y + 3, 1, 1, chip)
            p.fillRect(x + 3, y + 3, 1, 1, chip_l)

        elif prop == AnimProp.SCARF:
            # Warm scarf wrapped around neck area with stripes
            scarf   = QColor(200, 65, 65, 210)
            stripe1 = QColor(225, 120, 120, 190)
            stripe2 = QColor(170, 45, 45, 220)
            fringe  = QColor(200, 65, 65, 170)
            y = B + 17
            # Wrap around body
            p.fillRect(B + 1, y, 22, 4, scarf)
            # Stripes
            p.fillRect(B + 1, y + 1, 22, 1, stripe1)
            p.fillRect(B + 1, y + 3, 22, 1, stripe2)
            # Dangling end
            p.fillRect(B + PIXEL_BODY - 1, y + 4, 3, 5, scarf)
            p.fillRect(B + PIXEL_BODY - 1, y + 5, 3, 1, stripe1)
            p.fillRect(B + PIXEL_BODY - 1, y + 7, 3, 1, stripe2)
            # Fringe at bottom
            p.fillRect(B + PIXEL_BODY - 1, y + 9, 1, 1, fringe)
            p.fillRect(B + PIXEL_BODY + 1, y + 9, 1, 1, fringe)

        elif prop == AnimProp.PARTY_HORN:
            # Party horn / noisemaker sticking out to the right
            mouth     = QColor(240, 180, 60)
            stripe1   = QColor(220, 50, 170)
            stripe2   = QColor(60, 180, 220)
            tip_color = QColor(255, 80, 80)
            x, y = B + PIXEL_BODY - 1, B + 14
            # Body segments (striped tube)
            p.fillRect(x, y, 2, 3, mouth)
            p.fillRect(x + 2, y, 2, 3, stripe1)
            p.fillRect(x + 4, y, 2, 3, stripe2)
            p.fillRect(x + 6, y, 2, 3, stripe1)
            # Flared end
            p.fillRect(x + 8, y - 1, 2, 5, tip_color)
            p.fillRect(x + 10, y - 1, 1, 1, tip_color)
            p.fillRect(x + 10, y + 3, 1, 1, tip_color)

        elif prop == AnimProp.GIFT_BOX:
            # Wrapped gift box with bow — held on left side
            box      = QColor(220, 55, 55)
            box_dark = QColor(185, 40, 40)
            ribbon   = QColor(255, 215, 0)
            rib_dark = QColor(215, 175, 0)
            bow      = QColor(255, 230, 50)
            x, y = B - 5, B + 14
            # Box body
            p.fillRect(x, y + 1, 8, 6, box)
            p.fillRect(x, y + 6, 8, 1, box_dark)          # shadow bottom
            p.fillRect(x + 7, y + 1, 1, 6, box_dark)      # shadow right
            p.fillRect(x + 1, y + 2, 2, 2, QColor(240, 80, 80))  # highlight
            # Ribbon cross
            p.fillRect(x, y + 3, 8, 1, ribbon)
            p.fillRect(x + 4, y + 1, 1, 6, ribbon)
            p.fillRect(x, y + 4, 8, 1, rib_dark)
            # Bow on top
            p.fillRect(x + 2, y, 2, 1, bow)
            p.fillRect(x + 5, y, 2, 1, bow)
            p.fillRect(x + 4, y - 1, 1, 2, ribbon)        # bow center
            p.fillRect(x + 3, y - 1, 1, 1, bow)
            p.fillRect(x + 5, y - 1, 1, 1, bow)

        elif prop == AnimProp.TELESCOPE:
            # Telescope / spyglass pointing up-right
            tube      = QColor(150, 125, 80)
            tube_dark = QColor(120, 100, 60)
            tube_hi   = QColor(175, 155, 110)
            lens_c    = QColor(170, 200, 240)
            lens_hi   = QColor(210, 230, 255)
            cap       = QColor(100, 80, 50)
            x, y = B + PIXEL_BODY - 3, B + 2
            # Main tube
            p.fillRect(x, y + 2, 3, 2, cap)               # eyepiece
            p.fillRect(x + 3, y + 1, 5, 3, tube)
            p.fillRect(x + 3, y + 1, 5, 1, tube_hi)       # highlight
            p.fillRect(x + 3, y + 3, 5, 1, tube_dark)     # shadow
            # Front section (wider)
            p.fillRect(x + 8, y, 3, 5, tube)
            p.fillRect(x + 8, y, 3, 1, tube_hi)
            p.fillRect(x + 8, y + 4, 3, 1, tube_dark)
            # Lens
            p.fillRect(x + 11, y + 1, 1, 3, lens_c)
            p.fillRect(x + 11, y + 1, 1, 1, lens_hi)      # glare

        elif prop == AnimProp.EASEL:
            # Painting easel with canvas — sits to the left of the fish
            wood      = QColor(160, 120, 70)
            wood_dark = QColor(130, 95, 50)
            canvas_c  = QColor(245, 240, 225)
            canvas_e  = QColor(200, 190, 160)
            # Paint dabs on canvas
            red_p     = QColor(200, 60, 60)
            blue_p    = QColor(60, 100, 200)
            green_p   = QColor(60, 170, 80)
            yellow_p  = QColor(240, 200, 50)
            x, y = B - 8, B + 2
            # Easel legs (A-frame)
            p.fillRect(x + 1, y + 12, 1, 6, wood_dark)    # left leg
            p.fillRect(x + 9, y + 12, 1, 6, wood_dark)    # right leg
            p.fillRect(x + 5, y + 13, 1, 5, wood_dark)    # back leg
            # Cross bar
            p.fillRect(x + 2, y + 12, 7, 1, wood)
            # Canvas frame
            p.fillRect(x, y, 11, 12, canvas_e)
            p.fillRect(x + 1, y + 1, 9, 10, canvas_c)
            # Painting on canvas — abstract landscape
            p.fillRect(x + 1, y + 1, 9, 4, QColor(135, 190, 240))   # sky
            p.fillRect(x + 1, y + 5, 9, 3, QColor(100, 180, 80))    # hills
            p.fillRect(x + 1, y + 8, 9, 3, QColor(80, 150, 65))     # foreground
            # Sun
            p.fillRect(x + 7, y + 2, 2, 2, yellow_p)
            # Paint dabs (artistic splashes)
            p.fillRect(x + 2, y + 3, 2, 1, red_p)
            p.fillRect(x + 5, y + 6, 1, 1, blue_p)
            p.fillRect(x + 3, y + 9, 2, 1, green_p)
            # Easel top edge
            p.fillRect(x, y, 11, 1, wood)

        elif prop == AnimProp.HANDHELD_GAME:
            # Handheld game console held in front
            body_c    = QColor(55, 55, 70)
            body_hi   = QColor(75, 75, 90)
            screen_c  = QColor(100, 200, 120)
            screen_dk = QColor(70, 160, 90)
            btn_a     = QColor(200, 60, 60)
            btn_b     = QColor(60, 100, 200)
            dpad      = QColor(40, 40, 50)
            x, y = B + 4, B + 18
            # Console body
            p.fillRect(x, y, 16, 9, body_c)
            p.fillRect(x + 1, y, 14, 1, body_hi)          # top highlight
            p.fillRect(x + 1, y + 1, 1, 7, body_hi)       # left highlight
            # Rounded corners (cut)
            p.fillRect(x, y, 1, 1, QColor(0, 0, 0, 0))
            p.fillRect(x + 15, y, 1, 1, QColor(0, 0, 0, 0))
            # Screen
            p.fillRect(x + 4, y + 1, 8, 5, screen_dk)
            p.fillRect(x + 5, y + 2, 6, 3, screen_c)
            # Little game sprite on screen
            p.fillRect(x + 7, y + 3, 2, 2, QColor(255, 255, 255))
            # D-pad
            p.fillRect(x + 1, y + 4, 3, 1, dpad)
            p.fillRect(x + 2, y + 3, 1, 3, dpad)
            # Buttons
            p.fillRect(x + 13, y + 3, 2, 2, btn_a)
            p.fillRect(x + 12, y + 5, 2, 2, btn_b)

        elif prop == AnimProp.POTTED_PLANT:
            # Cute potted plant to the left of fish
            pot       = QColor(180, 100, 60)
            pot_dark  = QColor(150, 75, 40)
            pot_hi    = QColor(200, 130, 85)
            soil      = QColor(90, 65, 40)
            stem      = QColor(60, 140, 50)
            leaf1     = QColor(70, 180, 60)
            leaf2     = QColor(50, 150, 45)
            flower    = QColor(240, 100, 140)
            flower_c  = QColor(255, 220, 80)
            x, y = B - 7, B + 10
            # Pot body (tapered)
            p.fillRect(x + 1, y + 6, 8, 1, pot)           # rim
            p.fillRect(x + 1, y + 6, 8, 1, pot_hi)        # rim highlight
            p.fillRect(x + 2, y + 7, 6, 4, pot)
            p.fillRect(x + 3, y + 11, 4, 1, pot_dark)     # base
            p.fillRect(x + 2, y + 7, 1, 4, pot_hi)        # left highlight
            p.fillRect(x + 7, y + 7, 1, 4, pot_dark)      # right shadow
            # Soil
            p.fillRect(x + 2, y + 6, 6, 1, soil)
            # Stems
            p.fillRect(x + 5, y + 2, 1, 4, stem)          # main stem
            p.fillRect(x + 3, y + 3, 1, 3, stem)          # left branch
            p.fillRect(x + 7, y + 4, 1, 2, stem)          # right branch
            # Leaves
            p.fillRect(x + 2, y + 2, 2, 2, leaf1)
            p.fillRect(x + 1, y + 3, 1, 1, leaf2)
            p.fillRect(x + 6, y + 3, 2, 2, leaf1)
            p.fillRect(x + 8, y + 4, 1, 1, leaf2)
            p.fillRect(x + 4, y + 1, 3, 2, leaf1)
            # Flower on top
            p.fillRect(x + 4, y, 3, 1, flower)
            p.fillRect(x + 5, y - 1, 1, 1, flower)
            p.fillRect(x + 5, y, 1, 1, flower_c)          # center

        elif prop == AnimProp.JOURNAL:
            # Open journal/diary with writing — held below
            cover     = QColor(140, 80, 50)
            cover_dk  = QColor(110, 60, 35)
            page      = QColor(250, 245, 230)
            page_line = QColor(180, 200, 220, 160)
            text_c    = QColor(50, 50, 80, 170)
            spine     = QColor(100, 55, 30)
            bookmark  = QColor(200, 60, 60)
            x, y = B + 1, B + 19
            # Covers
            p.fillRect(x, y, 6, 8, cover)
            p.fillRect(x + 7, y, 6, 8, QColor(150, 90, 55))
            p.fillRect(x, y + 7, 6, 1, cover_dk)
            p.fillRect(x + 7, y + 7, 6, 1, cover_dk)
            # Pages
            p.fillRect(x + 1, y + 1, 5, 6, page)
            p.fillRect(x + 7, y + 1, 5, 6, page)
            # Spine
            p.fillRect(x + 6, y, 1, 8, spine)
            # Ruled lines
            p.fillRect(x + 1, y + 2, 4, 1, page_line)
            p.fillRect(x + 1, y + 4, 4, 1, page_line)
            p.fillRect(x + 1, y + 6, 3, 1, page_line)
            p.fillRect(x + 8, y + 2, 4, 1, page_line)
            p.fillRect(x + 8, y + 4, 4, 1, page_line)
            p.fillRect(x + 8, y + 6, 3, 1, page_line)
            # Handwriting scribbles
            p.fillRect(x + 1, y + 2, 3, 1, text_c)
            p.fillRect(x + 1, y + 4, 2, 1, text_c)
            p.fillRect(x + 8, y + 2, 3, 1, text_c)
            p.fillRect(x + 8, y + 4, 4, 1, text_c)
            # Bookmark ribbon
            p.fillRect(x + 5, y, 1, 2, bookmark)

        elif prop == AnimProp.TINY_PIANO:
            # Small piano/keyboard below the fish
            body_c    = QColor(40, 35, 30)
            body_hi   = QColor(60, 55, 50)
            white_key = QColor(245, 245, 240)
            white_dk  = QColor(220, 220, 215)
            black_key = QColor(25, 25, 30)
            x, y = B + 1, B + 22
            # Piano body
            p.fillRect(x, y, 22, 7, body_c)
            p.fillRect(x + 1, y, 20, 1, body_hi)          # top edge highlight
            # White keys (7 keys)
            for i in range(7):
                kx = x + 2 + i * 3
                p.fillRect(kx, y + 1, 2, 5, white_key)
                p.fillRect(kx, y + 5, 2, 1, white_dk)     # shadow
            # Black keys (5, skipping 3rd and 7th positions)
            black_pos = [0, 1, 3, 4, 5]
            for i in black_pos:
                kx = x + 3 + i * 3
                p.fillRect(kx, y + 1, 2, 3, black_key)

    def _draw_particles(self, p: QPainter, particles: list):
        """Draw particle effects around the fish."""
        for ptcl in particles:
            kind = ptcl.get("kind", "")
            x = int(ptcl.get("x", 0))
            y = int(ptcl.get("y", 0))
            alpha = int(ptcl.get("alpha", 255))

            if kind == "zzz":
                c = QColor(180, 180, 220, alpha)
                # Tiny 'z' shape
                p.fillRect(x, y, 3, 1, c)
                p.fillRect(x + 2, y + 1, 1, 1, c)
                p.fillRect(x + 1, y + 2, 1, 1, c)
                p.fillRect(x, y + 3, 3, 1, c)

            elif kind == "sparkle":
                c = QColor(255, 215, 0, alpha)
                # Plus shape
                p.fillRect(x, y - 1, 1, 3, c)
                p.fillRect(x - 1, y, 3, 1, c)

            elif kind == "sweat":
                c = QColor(100, 180, 220, alpha)
                # Small drop
                p.fillRect(x, y, 1, 1, c)
                p.fillRect(x, y + 1, 1, 1, c)
                p.fillRect(x - 1, y + 2, 3, 1, c)

            elif kind == "heart":
                c = QColor(220, 60, 80, alpha)
                # 5x5 pixel heart
                p.fillRect(x, y, 2, 1, c)
                p.fillRect(x + 3, y, 2, 1, c)
                p.fillRect(x - 1, y + 1, 3, 1, c)
                p.fillRect(x + 3, y + 1, 3, 1, c)
                p.fillRect(x - 1, y + 2, 7, 1, c)
                p.fillRect(x, y + 3, 5, 1, c)
                p.fillRect(x + 1, y + 4, 3, 1, c)
                p.fillRect(x + 2, y + 5, 1, 1, c)

            elif kind == "question":
                c = QColor(200, 200, 255, alpha)
                # Pixel '?'
                p.fillRect(x, y, 3, 1, c)
                p.fillRect(x + 2, y + 1, 1, 1, c)
                p.fillRect(x + 1, y + 2, 1, 1, c)
                p.fillRect(x + 1, y + 3, 1, 1, c)
                p.fillRect(x + 1, y + 5, 1, 1, c)

            elif kind == "exclamation":
                c = QColor(255, 200, 60, alpha)
                # Pixel '!'
                p.fillRect(x + 1, y, 1, 3, c)
                p.fillRect(x + 1, y + 4, 1, 1, c)

            elif kind == "music":
                c = QColor(180, 130, 255, alpha)
                # Pixel music note
                p.fillRect(x + 2, y, 1, 4, c)
                p.fillRect(x, y + 3, 3, 1, c)
                p.fillRect(x, y + 2, 1, 1, c)

            elif kind == "confetti":
                colors = [QColor(255, 100, 100, alpha), QColor(100, 255, 100, alpha),
                          QColor(100, 100, 255, alpha), QColor(255, 255, 100, alpha)]
                c = colors[hash(id(ptcl)) % len(colors)]
                p.fillRect(x, y, 2, 2, c)

            elif kind == "star":
                c = QColor(255, 215, 0, alpha)
                p.fillRect(x, y - 1, 1, 3, c)
                p.fillRect(x - 1, y, 3, 1, c)
                for ddx, ddy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                    p.fillRect(x + ddx, y + ddy, 1, 1, c)

            elif kind == "stars":
                c = QColor(255, 255, 150, alpha)
                # Small plus shapes at slightly different offsets
                p.fillRect(x, y, 1, 1, c)
                p.fillRect(x - 1, y, 3, 1, c)
                p.fillRect(x, y - 1, 1, 3, c)

            elif kind == "spiral":
                c = QColor(200, 180, 255, alpha)
                # Tiny spiral approximation
                p.fillRect(x, y, 2, 1, c)
                p.fillRect(x + 1, y + 1, 1, 1, c)
                p.fillRect(x, y + 2, 2, 1, c)
                p.fillRect(x - 1, y + 1, 1, 1, c)

            elif kind == "snow":
                c = QColor(230, 240, 255, alpha)
                # Small snowflake
                p.fillRect(x, y, 1, 1, c)
                p.fillRect(x - 1, y, 1, 1, QColor(200, 220, 255, alpha // 2))
                p.fillRect(x + 1, y, 1, 1, QColor(200, 220, 255, alpha // 2))
                p.fillRect(x, y - 1, 1, 1, QColor(200, 220, 255, alpha // 2))

            elif kind == "leaf":
                c = QColor(200, 120, 50, alpha)
                # Small leaf shape
                p.fillRect(x, y, 2, 1, c)
                p.fillRect(x + 1, y + 1, 1, 1, c)
                p.fillRect(x - 1, y + 1, 1, 1, QColor(180, 100, 30, alpha))

            elif kind == "spark":
                c = QColor(255, 220, 50, alpha)
                # Tiny bright dot
                p.fillRect(x, y, 1, 1, c)
                p.fillRect(x + 1, y, 1, 1, QColor(255, 180, 30, alpha // 2))

            elif kind == "antenna_down":
                c = QColor(200, 60, 60, alpha)
                # Small antenna with drooping signal
                p.fillRect(x, y, 1, 4, c)
                p.fillRect(x - 1, y, 1, 1, c)
                p.fillRect(x + 1, y, 1, 1, c)
                # Broken signal lines
                p.fillRect(x + 2, y + 1, 1, 1, QColor(150, 50, 50, alpha // 2))
                p.fillRect(x - 2, y + 1, 1, 1, QColor(150, 50, 50, alpha // 2))

            elif kind == "rain":
                c = QColor(100, 160, 220, alpha)
                # Thin vertical raindrop streak
                p.fillRect(x, y, 1, 3, c)
                p.fillRect(x, y + 3, 1, 1, QColor(80, 140, 200, alpha // 2))

            elif kind == "firework":
                colors = [QColor(255, 80, 80, alpha), QColor(255, 200, 50, alpha),
                          QColor(80, 200, 255, alpha), QColor(200, 80, 255, alpha),
                          QColor(80, 255, 80, alpha)]
                c = colors[hash(id(ptcl)) % len(colors)]
                # Starburst dot with trailing pixel
                p.fillRect(x, y, 2, 2, c)
                p.fillRect(x + 1, y + 1, 1, 1, QColor(255, 255, 200, alpha // 2))

            elif kind == "dust":
                c = QColor(180, 160, 130, alpha)
                # Small poof cloud
                p.fillRect(x, y, 2, 1, c)
                p.fillRect(x - 1, y + 1, 3, 1, QColor(160, 140, 110, alpha // 2))

            elif kind == "sleep_bubble":
                frac = ptcl.get("life", 1.0) / ptcl.get("max_life", 1.0)
                # Bubble grows as it rises then pops
                c = QColor(200, 220, 255, alpha)
                if frac > 0.2:
                    sz = 2 if frac > 0.6 else 3
                    p.fillRect(x, y, sz, sz, c)
                    # Highlight
                    p.fillRect(x, y, 1, 1, QColor(240, 245, 255, alpha))
                else:
                    # Pop: small burst
                    p.fillRect(x - 1, y, 1, 1, c)
                    p.fillRect(x + 2, y, 1, 1, c)
                    p.fillRect(x, y - 1, 1, 1, c)
                    p.fillRect(x, y + 2, 1, 1, c)

            elif kind == "lightning":
                # Brief bright flash overlay
                c = QColor(255, 255, 255, alpha)
                p.fillRect(0, 0, PIXEL_CANVAS, PIXEL_CANVAS, QColor(255, 255, 255, alpha // 3))
                # Zigzag bolt
                p.fillRect(x - 1, y, 2, 2, c)
                p.fillRect(x, y + 2, 2, 2, c)
                p.fillRect(x - 1, y + 4, 2, 2, c)
                p.fillRect(x, y + 6, 2, 3, c)

            elif kind == "emote_coffee":
                c = QColor(180, 120, 60, alpha)
                # Tiny coffee cup
                p.fillRect(x, y + 1, 3, 3, c)
                p.fillRect(x + 3, y + 2, 1, 1, QColor(140, 90, 40, alpha))
                # Steam
                p.fillRect(x + 1, y, 1, 1, QColor(200, 200, 200, alpha // 2))

            elif kind == "emote_book":
                c = QColor(100, 140, 200, alpha)
                # Tiny open book
                p.fillRect(x, y, 2, 3, c)
                p.fillRect(x + 2, y, 2, 3, QColor(120, 160, 220, alpha))
                # Spine
                p.fillRect(x + 2, y, 1, 3, QColor(70, 100, 160, alpha))

            elif kind == "emote_music":
                c = QColor(220, 100, 220, alpha)
                # Double music note
                p.fillRect(x, y, 1, 4, c)
                p.fillRect(x + 3, y, 1, 4, c)
                p.fillRect(x, y, 4, 1, c)
                p.fillRect(x - 1, y + 3, 2, 1, c)
                p.fillRect(x + 2, y + 3, 2, 1, c)


# ---------------------------------------------------------------------------
# Hobby scene renderer — visual scenes for hobby animations
# ---------------------------------------------------------------------------

class HobbySceneRenderer:
    """Renders full visual scenes for hobby animations (painting, etc.)."""

    PAINT_COLORS = [
        QColor(231, 76, 60),    # red
        QColor(230, 126, 34),   # orange
        QColor(241, 196, 15),   # yellow
        QColor(46, 204, 113),   # green
        QColor(52, 152, 219),   # blue
        QColor(155, 89, 182),   # purple
        QColor(26, 188, 156),   # teal
    ]

    MOOD_TINTS = {
        "focused":    QColor(255, 107, 53, 38),   # warm orange 15%
        "frustrated": QColor(231, 76, 60, 26),    # red 10%
        "worried":    QColor(231, 76, 60, 20),    # light red 8%
        "happy":      QColor(247, 220, 111, 38),  # golden 15%
        "excited":    QColor(247, 220, 111, 38),
        "content":    QColor(247, 220, 111, 38),
        "curious":    QColor(255, 200, 80, 30),   # amber 12%
    }

    def __init__(self):
        self._active = False
        self._opacity = 0.0
        self._fading_in = False
        self._fading_out = False
        self._fish_face = "focused"

        # Painting state
        self._strokes: list[dict] = []
        self._splatters: list[dict] = []
        self._sparkles: list[dict] = []
        self._brush_x = 0.0
        self._brush_y = 0.0
        self._brush_target_x = 0.0
        self._brush_target_y = 0.0
        self._brush_color = QColor(231, 76, 60)
        self._brush_initialized = False
        self._finished = False

        # Computed layout (set first render)
        self._canvas_x = 0.0
        self._canvas_y = 0.0
        self._canvas_w = 60.0
        self._canvas_h = 70.0

    # -- Properties --------------------------------------------------------

    @property
    def is_visible(self):
        """True when the scene should render (active or fading)."""
        return self._active or self._opacity > 0

    @property
    def is_active(self):
        """True when accepting strokes / affecting gaze."""
        return self._active

    # -- Lifecycle ---------------------------------------------------------

    def start(self):
        self._active = True
        self._opacity = 0.0
        self._fading_in = True
        self._fading_out = False
        self._strokes = []
        self._splatters = []
        self._sparkles = []
        self._finished = False
        self._brush_initialized = False
        self._fish_face = "focused"

    def stop(self):
        """Natural end — add sparkles, then fade out."""
        self._finished = True
        self._add_sparkles()
        # Brush rests beside easel
        self._brush_target_x = self._canvas_x + self._canvas_w + 8
        self._brush_target_y = self._canvas_y + self._canvas_h + 5
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def interrupt(self):
        """Click interrupt — immediate fade with partial canvas."""
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def set_face(self, face: str):
        self._fish_face = face

    def get_tint(self):
        """Return the mood tint QColor for the FishRenderer, or None."""
        if not self._active:
            return None
        return self.MOOD_TINTS.get(self._fish_face)

    # -- Stroke management -------------------------------------------------

    def add_brush_stroke(self):
        """Add a random paint stroke to the canvas."""
        import random
        cx, cy = self._canvas_x, self._canvas_y
        cw, ch = self._canvas_w, self._canvas_h
        if cw <= 0 or ch <= 0:
            return

        color = random.choice(self.PAINT_COLORS)
        margin = 4
        x1 = random.uniform(cx + margin, cx + cw - margin)
        y1 = random.uniform(cy + margin, cy + ch - margin)
        x2 = random.uniform(cx + margin, cx + cw - margin)
        y2 = random.uniform(cy + margin, cy + ch - margin)
        cpx = random.uniform(cx + 2, cx + cw - 2)
        cpy = random.uniform(cy + 2, cy + ch - 2)
        width = random.uniform(3.0, 8.0)
        opacity = random.randint(180, 255)

        self._strokes.append({
            'x1': x1, 'y1': y1, 'cpx': cpx, 'cpy': cpy,
            'x2': x2, 'y2': y2, 'color': color, 'width': width,
            'opacity': opacity,
        })

        # Paint splatters on the floor below the easel
        for _ in range(random.randint(2, 4)):
            sx = random.uniform(cx - 8, cx + cw + 8)
            sy = cy + ch + random.uniform(18, 40)
            w = random.uniform(4.0, 10.0)
            h = random.uniform(2.0, 5.0)
            if random.random() < 0.5:
                w, h = h, w  # some tall, some wide
            self._splatters.append({
                'x': sx, 'y': sy,
                'w': w, 'h': h,
                'color': color,
            })

        # Move brush to stroke endpoint
        self._brush_target_x = x2
        self._brush_target_y = y2
        self._brush_color = QColor(color)

    def _add_sparkles(self):
        import random
        cx, cy = self._canvas_x, self._canvas_y
        cw, ch = self._canvas_w, self._canvas_h
        for _ in range(random.randint(4, 6)):
            self._sparkles.append({
                'x': random.uniform(cx + 5, cx + cw - 5),
                'y': random.uniform(cy + 5, cy + ch - 5),
                'size': random.uniform(4.0, 8.0),
                'alpha': 1.0,
                'decay': random.uniform(0.3, 0.5),
                'phase': random.uniform(0, 6.28),
            })

    # -- Frame update ------------------------------------------------------

    def update(self, dt: float):
        import math
        # Fade in
        if self._fading_in:
            self._opacity = min(1.0, self._opacity + dt / 0.5)
            if self._opacity >= 1.0:
                self._fading_in = False
        # Fade out
        elif self._fading_out:
            self._opacity = max(0.0, self._opacity - dt / 0.8)
            if self._opacity <= 0.0:
                self._fading_out = False

        # Smooth brush interpolation
        speed = min(dt * 10.0, 1.0)
        self._brush_x += (self._brush_target_x - self._brush_x) * speed
        self._brush_y += (self._brush_target_y - self._brush_y) * speed

        # Update sparkles
        for sp in self._sparkles:
            sp['alpha'] -= dt * sp['decay']
            sp['phase'] += dt * 4.0
        self._sparkles = [sp for sp in self._sparkles if sp['alpha'] > 0]

    # -- Render (called from fish_widget paintEvent) -----------------------

    def render(self, p: QPainter, fish_cx: float, fish_cy: float,
               display_size: float):
        """Render the painting scene. p is the widget-level QPainter."""
        if self._opacity <= 0:
            return

        ds = display_size
        s = ds / 80.0  # scale factor

        # --- Compute layout ---
        fish_left = fish_cx - ds / 2.0
        gap = ds * 0.35
        cw, ch = 45 * s, 55 * s
        canvas_right = fish_left - gap
        canvas_x = canvas_right - cw
        canvas_y = fish_cy - ch / 2.0 - 3 * s

        self._canvas_x = canvas_x
        self._canvas_y = canvas_y
        self._canvas_w = cw
        self._canvas_h = ch

        # Initialize brush to rest position on first render
        if not self._brush_initialized:
            self._brush_x = canvas_x + cw + 4 * s
            self._brush_y = canvas_y + ch / 2.0
            self._brush_target_x = self._brush_x
            self._brush_target_y = self._brush_y
            self._brush_initialized = True

        p.save()
        p.setOpacity(self._opacity)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # === Easel legs ===
        leg_color = QColor(92, 58, 30)
        pen = QPen(leg_color, 2.5 * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        leg_bottom = canvas_y + ch + 18 * s
        # Left leg
        p.drawLine(QPointF(canvas_x + 8 * s, canvas_y + ch),
                   QPointF(canvas_x - 4 * s, leg_bottom))
        # Right leg
        p.drawLine(QPointF(canvas_x + cw - 8 * s, canvas_y + ch),
                   QPointF(canvas_x + cw + 4 * s, leg_bottom))
        # Cross brace
        p.drawLine(QPointF(canvas_x + 2 * s, canvas_y + ch + 9 * s),
                   QPointF(canvas_x + cw - 2 * s, canvas_y + ch + 9 * s))
        # Rear support leg (thinner)
        pen.setWidthF(1.5 * s)
        p.setPen(pen)
        p.drawLine(QPointF(canvas_x + cw / 2, canvas_y + ch),
                   QPointF(canvas_x + cw / 2 + 10 * s, leg_bottom + 4 * s))

        # === Canvas frame (3D angled — face toward fish on right) ===
        frame_color = QColor(139, 105, 20)   # #8B6914
        frame_side  = QColor(105, 78, 15)    # darker side edge
        canvas_bg = QColor(255, 248, 231)    # #FFF8E7

        # Side edge (depth) on the left — shows canvas thickness
        depth = 4.0 * s
        side_path = QPainterPath()
        side_path.moveTo(canvas_x, canvas_y)
        side_path.lineTo(canvas_x - depth, canvas_y + 3 * s)
        side_path.lineTo(canvas_x - depth, canvas_y + ch - 3 * s)
        side_path.lineTo(canvas_x, canvas_y + ch)
        side_path.closeSubpath()
        p.setPen(QPen(frame_side, 1.0))
        p.setBrush(QBrush(frame_side))
        p.drawPath(side_path)

        # Main canvas surface
        p.setPen(QPen(frame_color, 2.0))
        p.setBrush(QBrush(canvas_bg))
        p.drawRect(QRectF(canvas_x, canvas_y, cw, ch))

        # Highlight on right edge (light hits from the fish's side)
        p.setPen(QPen(QColor(180, 150, 60, 120), 1.5))
        p.drawLine(QPointF(canvas_x + cw, canvas_y + 2),
                   QPointF(canvas_x + cw, canvas_y + ch - 2))

        # === Paint strokes on canvas (clipped) ===
        p.save()
        p.setClipRect(QRectF(canvas_x + 1, canvas_y + 1, cw - 2, ch - 2))
        for s in self._strokes:
            c = QColor(s['color'])
            c.setAlpha(s['opacity'])
            pen = QPen(c, s['width'])
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(s['x1'], s['y1'])
            path.quadTo(s['cpx'], s['cpy'], s['x2'], s['y2'])
            p.drawPath(path)
        p.restore()

        # === Paint splatters on the floor ===
        p.setPen(Qt.PenStyle.NoPen)
        for sp in self._splatters:
            c = QColor(sp['color'])
            c.setAlpha(220)
            p.setBrush(QBrush(c))
            w, h = sp['w'], sp['h']
            p.drawEllipse(QRectF(sp['x'] - w / 2.0, sp['y'] - h / 2.0,
                                 w, h))

        # === Brush ===
        bx, by = self._brush_x, self._brush_y
        # Handle
        handle_color = QColor(139, 105, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(handle_color))
        p.drawRect(QRectF(bx - 1, by - 18, 3, 16))
        # Ferrule (metal band)
        p.setBrush(QBrush(QColor(180, 180, 180)))
        p.drawRect(QRectF(bx - 2, by - 3, 5, 3))
        # Bristle tip
        p.setBrush(QBrush(self._brush_color))
        p.drawEllipse(QRectF(bx - 3, by - 1, 7, 5))

        # === Sparkles (finished painting reveal) ===
        import math
        for sp in self._sparkles:
            alpha = max(0, sp['alpha'])
            # Twinkle effect
            twinkle = 0.5 + 0.5 * math.sin(sp['phase'])
            a = int(255 * alpha * twinkle)
            if a <= 0:
                continue
            c = QColor(255, 255, 220, a)
            x, y, sz = sp['x'], sp['y'], sp['size']
            half = sz / 2.0
            p.setPen(QPen(c, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # 4-point star
            p.drawLine(QPointF(x, y - half), QPointF(x, y + half))
            p.drawLine(QPointF(x - half, y), QPointF(x + half, y))
            d = half * 0.55
            p.drawLine(QPointF(x - d, y - d), QPointF(x + d, y + d))
            p.drawLine(QPointF(x + d, y - d), QPointF(x - d, y + d))

        p.restore()


# ---------------------------------------------------------------------------
# Gaming scene — monitor, controller, pixel game on screen
# ---------------------------------------------------------------------------

class GamingScene:
    """Renders a gaming setup: monitor on stand to the right, controller held."""

    MOOD_TINTS = {
        "focused":    QColor(100, 140, 255, 30),
        "frustrated": QColor(231, 76, 60, 30),
        "worried":    QColor(231, 76, 60, 20),
        "happy":      QColor(247, 220, 111, 35),
        "excited":    QColor(247, 220, 111, 40),
        "content":    QColor(200, 220, 255, 25),
        "curious":    QColor(180, 200, 255, 25),
    }

    def __init__(self):
        self._active = False
        self._opacity = 0.0
        self._fading_in = False
        self._fading_out = False
        self._fish_face = "focused"

        # Monitor layout (set on first render)
        self._mon_x = 0.0
        self._mon_y = 0.0
        self._mon_w = 70.0
        self._mon_h = 50.0

        # Screen game state
        self._game_sq1_x = 0.3
        self._game_sq1_y = 0.5
        self._game_sq2_x = 0.7
        self._game_sq2_y = 0.4
        self._game_sq1_dx = 0.6
        self._game_sq1_dy = 0.4
        self._game_sq2_dx = -0.5
        self._game_sq2_dy = 0.6
        self._game_timer = 0.0

        # Button press flash
        self._btn_flash: list[dict] = []  # {index, alpha}

        # Confetti particles
        self._confetti: list[dict] = []

        # Screen flash (win)
        self._screen_flash = 0.0
        # Screen red tint (frustration)
        self._screen_red = 0.0

        self._finished = False

    # -- Properties --------------------------------------------------------

    @property
    def is_visible(self):
        return self._active or self._opacity > 0

    @property
    def is_active(self):
        return self._active

    # -- Lifecycle ---------------------------------------------------------

    def start(self):
        self._active = True
        self._opacity = 0.0
        self._fading_in = True
        self._fading_out = False
        self._btn_flash = []
        self._confetti = []
        self._screen_flash = 0.0
        self._screen_red = 0.0
        self._finished = False
        self._fish_face = "focused"
        self._game_timer = 0.0

    def stop(self):
        self._finished = True
        # Win flash + confetti
        if self._fish_face in ("excited", "happy"):
            self._screen_flash = 1.0
            self._spawn_confetti()
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def interrupt(self):
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def set_face(self, face: str):
        self._fish_face = face
        if face in ("frustrated", "worried"):
            self._screen_red = min(1.0, self._screen_red + 0.4)
        elif face in ("excited", "happy"):
            self._screen_flash = min(1.0, self._screen_flash + 0.5)

    def get_tint(self):
        if not self._active:
            return None
        return self.MOOD_TINTS.get(self._fish_face)

    # -- Interaction -------------------------------------------------------

    def add_button_press(self):
        import random
        idx = random.randint(0, 3)
        self._btn_flash.append({'index': idx, 'alpha': 1.0})

    def _spawn_confetti(self):
        import random
        mx, my = self._mon_x, self._mon_y
        mw = self._mon_w
        for _ in range(12):
            self._confetti.append({
                'x': random.uniform(mx + 5, mx + mw - 5),
                'y': my - 5,
                'vy': random.uniform(30, 80),
                'vx': random.uniform(-15, 15),
                'color': random.choice([
                    QColor(231, 76, 60), QColor(46, 204, 113),
                    QColor(52, 152, 219), QColor(241, 196, 15),
                    QColor(155, 89, 182), QColor(230, 126, 34),
                ]),
                'size': random.uniform(3, 6),
                'alpha': 1.0,
            })

    # -- Frame update ------------------------------------------------------

    def update(self, dt: float):
        if self._fading_in:
            self._opacity = min(1.0, self._opacity + dt / 0.5)
            if self._opacity >= 1.0:
                self._fading_in = False
        elif self._fading_out:
            self._opacity = max(0.0, self._opacity - dt / 0.8)
            if self._opacity <= 0.0:
                self._fading_out = False

        # Game squares bounce around
        self._game_timer += dt
        speed = 0.8
        self._game_sq1_x += self._game_sq1_dx * dt * speed
        self._game_sq1_y += self._game_sq1_dy * dt * speed
        self._game_sq2_x += self._game_sq2_dx * dt * speed
        self._game_sq2_y += self._game_sq2_dy * dt * speed
        for attr_x, attr_dx in [('_game_sq1_x', '_game_sq1_dx'),
                                 ('_game_sq2_x', '_game_sq2_dx')]:
            v = getattr(self, attr_x)
            if v < 0.05 or v > 0.95:
                setattr(self, attr_dx, -getattr(self, attr_dx))
                setattr(self, attr_x, max(0.05, min(0.95, v)))
        for attr_y, attr_dy in [('_game_sq1_y', '_game_sq1_dy'),
                                 ('_game_sq2_y', '_game_sq2_dy')]:
            v = getattr(self, attr_y)
            if v < 0.05 or v > 0.95:
                setattr(self, attr_dy, -getattr(self, attr_dy))
                setattr(self, attr_y, max(0.05, min(0.95, v)))

        # Button flash decay
        for bf in self._btn_flash:
            bf['alpha'] -= dt * 4.0
        self._btn_flash = [bf for bf in self._btn_flash if bf['alpha'] > 0]

        # Confetti fall
        for c in self._confetti:
            c['y'] += c['vy'] * dt
            c['x'] += c['vx'] * dt
            c['alpha'] -= dt * 0.5
        self._confetti = [c for c in self._confetti if c['alpha'] > 0]

        # Screen flash / red decay
        self._screen_flash = max(0.0, self._screen_flash - dt * 2.0)
        self._screen_red = max(0.0, self._screen_red - dt * 0.8)

    # -- Render ------------------------------------------------------------

    def render(self, p: QPainter, fish_cx: float, fish_cy: float,
               display_size: float):
        if self._opacity <= 0:
            return

        ds = display_size
        s = ds / 80.0

        # Monitor is to the RIGHT of the fish
        fish_right = fish_cx + ds / 2.0
        gap = ds * 0.08
        mw, mh = 105 * s, 80 * s
        mx = fish_right + gap
        my = fish_cy - mh / 2.0 - 3 * s

        self._mon_x = mx
        self._mon_y = my
        self._mon_w = mw
        self._mon_h = mh

        p.save()
        p.setOpacity(self._opacity)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # === Screen glow (behind monitor) ===
        glow_color = QColor(100, 180, 255, 40)
        if self._fish_face in ("frustrated", "worried"):
            glow_color = QColor(255, 100, 80, 35)
        elif self._fish_face in ("excited", "happy"):
            glow_color = QColor(255, 240, 100, 45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow_color))
        glow_pad = 6 * s
        p.drawRoundedRect(QRectF(mx - glow_pad, my - glow_pad,
                                  mw + glow_pad * 2, mh + glow_pad * 2),
                          4 * s, 4 * s)

        # === Monitor stand ===
        stand_color = QColor(60, 60, 65)
        p.setPen(Qt.PenStyle.NoPen)
        # Neck
        p.setBrush(QBrush(stand_color))
        neck_w, neck_h = 6 * s, 10 * s
        p.drawRect(QRectF(mx + mw / 2 - neck_w / 2, my + mh,
                          neck_w, neck_h))
        # Base
        base_w = 22 * s
        p.drawRoundedRect(QRectF(mx + mw / 2 - base_w / 2,
                                  my + mh + neck_h,
                                  base_w, 3 * s), 2, 2)

        # === Monitor bezel ===
        bezel_color = QColor(35, 35, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bezel_color))
        p.drawRoundedRect(QRectF(mx, my, mw, mh), 3 * s, 3 * s)

        # === Screen ===
        scr_pad = 3 * s
        scr_x = mx + scr_pad
        scr_y = my + scr_pad
        scr_w = mw - scr_pad * 2
        scr_h = mh - scr_pad * 2 - 1 * s
        screen_bg = QColor(15, 20, 35)
        p.setBrush(QBrush(screen_bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(scr_x, scr_y, scr_w, scr_h))

        # === Pixel game on screen ===
        sq_sz = 7 * s
        s1x = scr_x + self._game_sq1_x * (scr_w - sq_sz)
        s1y = scr_y + self._game_sq1_y * (scr_h - sq_sz)
        p.setBrush(QBrush(QColor(80, 160, 255)))
        p.drawRect(QRectF(s1x, s1y, sq_sz, sq_sz))
        s2x = scr_x + self._game_sq2_x * (scr_w - sq_sz)
        s2y = scr_y + self._game_sq2_y * (scr_h - sq_sz)
        p.setBrush(QBrush(QColor(255, 80, 80)))
        p.drawRect(QRectF(s2x, s2y, sq_sz, sq_sz))

        # Screen red tint (frustration)
        if self._screen_red > 0:
            a = int(60 * self._screen_red)
            p.setBrush(QBrush(QColor(255, 40, 40, a)))
            p.drawRect(QRectF(scr_x, scr_y, scr_w, scr_h))

        # Screen flash (win)
        if self._screen_flash > 0:
            a = int(200 * self._screen_flash)
            p.setBrush(QBrush(QColor(255, 255, 255, a)))
            p.drawRect(QRectF(scr_x, scr_y, scr_w, scr_h))

        # === Controller (in front of fish) ===
        ctrl_cx = fish_cx
        ctrl_cy = fish_cy + ds * 0.35
        ctrl_w, ctrl_h = 24 * s, 14 * s

        # Body
        ctrl_color = QColor(50, 50, 60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(ctrl_color))
        p.drawRoundedRect(QRectF(ctrl_cx - ctrl_w / 2, ctrl_cy,
                                  ctrl_w, ctrl_h), 3 * s, 3 * s)
        # Left grip
        p.drawRoundedRect(QRectF(ctrl_cx - ctrl_w / 2 - 2 * s,
                                  ctrl_cy + 3 * s, 4 * s, ctrl_h - 2 * s), 2 * s, 2 * s)
        # Right grip
        p.drawRoundedRect(QRectF(ctrl_cx + ctrl_w / 2 - 2 * s,
                                  ctrl_cy + 3 * s, 4 * s, ctrl_h - 2 * s), 2 * s, 2 * s)

        # D-pad (left side)
        dpad_cx = ctrl_cx - 4 * s
        dpad_cy = ctrl_cy + ctrl_h / 2
        dpad_c = QColor(35, 35, 42)
        p.setBrush(QBrush(dpad_c))
        p.drawRect(QRectF(dpad_cx - 1 * s, dpad_cy - 3 * s, 2 * s, 6 * s))
        p.drawRect(QRectF(dpad_cx - 3 * s, dpad_cy - 1 * s, 6 * s, 2 * s))

        # ABXY buttons (right side) — 4 buttons in diamond
        btn_cx = ctrl_cx + 4 * s
        btn_cy = ctrl_cy + ctrl_h / 2
        btn_r = 1.5 * s
        btn_positions = [
            (btn_cx, btn_cy - 2.5 * s),
            (btn_cx - 2.5 * s, btn_cy),
            (btn_cx + 2.5 * s, btn_cy),
            (btn_cx, btn_cy + 2.5 * s),
        ]
        btn_colors_default = [
            QColor(220, 200, 50),   # Y - yellow
            QColor(60, 120, 220),   # X - blue
            QColor(220, 60, 60),    # B - red
            QColor(60, 200, 80),    # A - green
        ]
        for i, (bx, by) in enumerate(btn_positions):
            # Check for active flash
            flash_a = 0.0
            for bf in self._btn_flash:
                if bf['index'] == i:
                    flash_a = max(flash_a, bf['alpha'])
            base = btn_colors_default[i]
            if flash_a > 0:
                bright = QColor(255, 255, 255,
                                int(180 * flash_a))
                p.setBrush(QBrush(bright))
            else:
                p.setBrush(QBrush(base))
            p.drawEllipse(QRectF(bx - btn_r, by - btn_r,
                                  btn_r * 2, btn_r * 2))

        # === Confetti ===
        for c in self._confetti:
            col = QColor(c['color'])
            col.setAlpha(int(255 * max(0, c['alpha'])))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            half = c['size'] / 2.0
            p.drawRect(QRectF(c['x'] - half, c['y'] - half,
                              c['size'], c['size']))

        p.restore()


# ---------------------------------------------------------------------------
# Gardening scene — ground-level soil, growing plants, watering can
# ---------------------------------------------------------------------------

class GardeningScene:
    """Renders a gardening scene: soil patch below fish, plants grow, watering."""

    MOOD_TINTS = {
        "focused":    QColor(100, 200, 100, 25),
        "content":    QColor(140, 220, 100, 30),
        "happy":      QColor(180, 240, 100, 35),
        "curious":    QColor(150, 200, 120, 25),
        "worried":    QColor(200, 180, 80, 20),
        "frustrated": QColor(180, 140, 60, 20),
        "excited":    QColor(200, 240, 80, 35),
    }

    def __init__(self):
        self._active = False
        self._opacity = 0.0
        self._fading_in = False
        self._fading_out = False
        self._fish_face = "content"

        # Soil patch layout (set on first render)
        self._soil_x = 0.0
        self._soil_y = 0.0
        self._soil_w = 100.0
        self._soil_h = 18.0

        # Plants — up to 3, each has growth stage 0-4
        self._plants: list[dict] = []
        self._plant_count = 0

        # Watering state
        self._watering = False
        self._water_timer = 0.0
        self._droplets: list[dict] = []
        self._soil_wet = 0.0  # 0.0 = dry, 1.0 = fully wet

        # End-of-scene glow
        self._end_glow = 0.0
        self._finished = False

    @property
    def is_visible(self):
        return self._active or self._opacity > 0

    @property
    def is_active(self):
        return self._active

    def start(self):
        import random
        self._active = True
        self._opacity = 0.0
        self._fading_in = True
        self._fading_out = False
        self._finished = False
        self._fish_face = "content"
        self._soil_wet = 0.0
        self._end_glow = 0.0
        self._droplets = []
        self._watering = False
        self._water_timer = 0.0
        # Initialize 1-3 plants at stage 0
        self._plant_count = random.randint(1, 3)
        self._plants = []
        for i in range(self._plant_count):
            self._plants.append({
                'offset': (i - (self._plant_count - 1) / 2.0) * 25,
                'stage': 0,
                'flower_color': random.choice([
                    QColor(231, 76, 60), QColor(241, 196, 15),
                    QColor(155, 89, 182), QColor(230, 126, 34),
                    QColor(52, 152, 219),
                ]),
            })

    def stop(self):
        self._finished = True
        self._end_glow = 1.0
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def interrupt(self):
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def set_face(self, face: str):
        self._fish_face = face

    def get_tint(self):
        if not self._active:
            return None
        return self.MOOD_TINTS.get(self._fish_face)

    def add_growth_stage(self):
        """Advance the next plant by one growth stage."""
        for plant in self._plants:
            if plant['stage'] < 4:
                plant['stage'] += 1
                return

    def show_watering(self):
        """Trigger watering can animation with droplets."""
        import random
        self._watering = True
        self._water_timer = 1.5
        self._soil_wet = min(1.0, self._soil_wet + 0.3)
        sx, sy = self._soil_x, self._soil_y
        sw = self._soil_w
        for _ in range(6):
            self._droplets.append({
                'x': random.uniform(sx + 15, sx + sw - 15),
                'y': sy - 25,
                'vy': random.uniform(40, 70),
                'alpha': 1.0,
                'ground_y': sy,
            })

    def update(self, dt: float):
        if self._fading_in:
            self._opacity = min(1.0, self._opacity + dt / 0.5)
            if self._opacity >= 1.0:
                self._fading_in = False
        elif self._fading_out:
            self._opacity = max(0.0, self._opacity - dt / 0.8)
            if self._opacity <= 0.0:
                self._fading_out = False

        # Watering timer
        if self._watering:
            self._water_timer -= dt
            if self._water_timer <= 0:
                self._watering = False

        # Droplets fall
        for d in self._droplets:
            d['y'] += d['vy'] * dt
            if d['y'] >= d['ground_y']:
                d['alpha'] -= dt * 3.0
            else:
                d['alpha'] -= dt * 0.3
        self._droplets = [d for d in self._droplets if d['alpha'] > 0]

        # Soil dries slowly
        self._soil_wet = max(0.0, self._soil_wet - dt * 0.05)

        # End glow decay
        self._end_glow = max(0.0, self._end_glow - dt * 0.3)

    def render(self, p: QPainter, fish_cx: float, fish_cy: float,
               display_size: float):
        if self._opacity <= 0:
            return

        ds = display_size
        s = ds / 80.0

        # Scene is below fish, centered
        soil_w = 110 * s
        soil_h = 14 * s
        soil_cx = fish_cx
        soil_y = fish_cy + ds * 0.32
        soil_x = soil_cx - soil_w / 2.0

        self._soil_x = soil_x
        self._soil_y = soil_y
        self._soil_w = soil_w
        self._soil_h = soil_h

        p.save()
        p.setOpacity(self._opacity)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # === Grass strip on top of soil ===
        grass_h = 4 * s
        grass_c = QColor(80, 180, 50)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grass_c))
        p.drawRoundedRect(QRectF(soil_x - 2 * s, soil_y - grass_h,
                                  soil_w + 4 * s, grass_h + 2 * s), 3 * s, 2 * s)
        # Grass tufts
        tuft_c = QColor(60, 150, 40)
        import random as _rng
        _rng.seed(99)
        for _ in range(14):
            tx = soil_x + _rng.uniform(4 * s, soil_w - 4 * s)
            tw = _rng.uniform(2.5 * s, 4 * s)
            th = _rng.uniform(3 * s, 6 * s)
            p.setBrush(QBrush(tuft_c))
            p.drawEllipse(QRectF(tx - tw / 2, soil_y - grass_h - th * 0.6,
                                  tw, th))
        _rng.seed()

        # === Soil patch ===
        dry_color = QColor(101, 67, 33)
        wet_color = QColor(70, 45, 20)
        w = self._soil_wet
        sr = int(dry_color.red() * (1 - w) + wet_color.red() * w)
        sg = int(dry_color.green() * (1 - w) + wet_color.green() * w)
        sb = int(dry_color.blue() * (1 - w) + wet_color.blue() * w)
        soil_c = QColor(sr, sg, sb)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(soil_c))
        p.drawRoundedRect(QRectF(soil_x, soil_y, soil_w, soil_h), 4 * s, 3 * s)
        # Soil texture — small darker dots
        import random as _rng
        _rng.seed(42)  # deterministic texture
        for _ in range(10):
            tx = soil_x + _rng.uniform(3 * s, soil_w - 3 * s)
            ty = soil_y + _rng.uniform(2 * s, soil_h - 2 * s)
            p.setBrush(QBrush(QColor(60, 38, 18, 80)))
            p.drawEllipse(QRectF(tx - s, ty - 0.5 * s, 2 * s, s))
        _rng.seed()  # restore randomness

        # === Plants ===
        for plant in self._plants:
            px = soil_cx + plant['offset'] * s
            py = soil_y  # top of soil
            stage = plant['stage']
            fc = plant['flower_color']

            stem_c = QColor(60, 160, 50)
            leaf_c = QColor(80, 200, 60)

            if stage == 0:
                # Tiny sprout
                p.setBrush(QBrush(stem_c))
                p.drawRect(QRectF(px - 0.5 * s, py - 5 * s, 1.5 * s, 5 * s))
                p.setBrush(QBrush(leaf_c))
                p.drawEllipse(QRectF(px - 3 * s, py - 6 * s, 3 * s, 2.5 * s))
                p.drawEllipse(QRectF(px, py - 6 * s, 3 * s, 2.5 * s))
            elif stage == 1:
                # Small sprout — taller with leaves
                p.setPen(QPen(stem_c, 1.5 * s))
                p.drawLine(QPointF(px, py), QPointF(px, py - 14 * s))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(leaf_c))
                p.drawEllipse(QRectF(px - 5 * s, py - 12 * s, 5 * s, 4 * s))
                p.drawEllipse(QRectF(px, py - 12 * s, 5 * s, 4 * s))
            elif stage == 2:
                # Medium plant
                p.setPen(QPen(stem_c, 2.0 * s))
                p.drawLine(QPointF(px, py), QPointF(px, py - 22 * s))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(leaf_c))
                p.drawEllipse(QRectF(px - 6 * s, py - 15 * s, 6 * s, 4 * s))
                p.drawEllipse(QRectF(px, py - 19 * s, 6 * s, 4 * s))
                p.drawEllipse(QRectF(px - 5 * s, py - 22 * s, 5 * s, 3 * s))
            elif stage == 3:
                # Tall plant — bud forming
                p.setPen(QPen(stem_c, 2.0 * s))
                p.drawLine(QPointF(px, py), QPointF(px, py - 28 * s))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(leaf_c))
                p.drawEllipse(QRectF(px - 6 * s, py - 17 * s, 6 * s, 4 * s))
                p.drawEllipse(QRectF(px, py - 22 * s, 6 * s, 4 * s))
                p.drawEllipse(QRectF(px - 5 * s, py - 26 * s, 5 * s, 3 * s))
                # Bud
                p.setBrush(QBrush(QColor(fc.red(), fc.green(), fc.blue(), 150)))
                p.drawEllipse(QRectF(px - 4 * s, py - 33 * s, 8 * s, 6 * s))
            else:
                # Full flower
                p.setPen(QPen(stem_c, 2.0 * s))
                p.drawLine(QPointF(px, py), QPointF(px, py - 32 * s))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(leaf_c))
                p.drawEllipse(QRectF(px - 7 * s, py - 19 * s, 7 * s, 5 * s))
                p.drawEllipse(QRectF(px, py - 24 * s, 7 * s, 5 * s))
                # Flower petals
                p.setBrush(QBrush(fc))
                for angle in range(0, 360, 72):
                    import math
                    rad = math.radians(angle)
                    petal_x = px + math.cos(rad) * 6 * s
                    petal_y = py - 36 * s + math.sin(rad) * 6 * s
                    p.drawEllipse(QRectF(petal_x - 3 * s, petal_y - 3 * s,
                                         6 * s, 6 * s))
                # Center
                p.setBrush(QBrush(QColor(255, 220, 80)))
                p.drawEllipse(QRectF(px - 2.5 * s, py - 38 * s, 5 * s, 5 * s))

        # === Watering can (when active) ===
        if self._watering:
            wc_x = soil_x + soil_w + 3 * s
            wc_y = soil_y - 15 * s
            can_c = QColor(100, 140, 180)
            can_dk = QColor(70, 105, 140)
            p.setPen(Qt.PenStyle.NoPen)
            # Body
            p.setBrush(QBrush(can_c))
            p.drawRoundedRect(QRectF(wc_x, wc_y, 12 * s, 10 * s), 2, 2)
            # Spout
            p.setPen(QPen(can_dk, 1.2 * s))
            p.drawLine(QPointF(wc_x, wc_y + 2 * s),
                       QPointF(wc_x - 7 * s, wc_y + 6 * s))
            # Handle
            p.drawLine(QPointF(wc_x + 10 * s, wc_y),
                       QPointF(wc_x + 10 * s, wc_y - 4 * s))
            p.drawLine(QPointF(wc_x + 10 * s, wc_y - 4 * s),
                       QPointF(wc_x + 5 * s, wc_y - 4 * s))
            p.setPen(Qt.PenStyle.NoPen)

        # === Water droplets ===
        for d in self._droplets:
            a = int(220 * max(0, d['alpha']))
            if a <= 0:
                continue
            p.setBrush(QBrush(QColor(100, 170, 255, a)))
            p.setPen(Qt.PenStyle.NoPen)
            # Teardrop shape
            path = QPainterPath()
            dx, dy = d['x'], d['y']
            path.moveTo(dx, dy - 3)
            path.quadTo(dx + 2, dy, dx, dy + 2)
            path.quadTo(dx - 2, dy, dx, dy - 3)
            p.drawPath(path)

        # === End-of-scene green glow ===
        if self._end_glow > 0:
            a = int(50 * self._end_glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(100, 255, 100, a)))
            # Glow around the plants
            p.drawRoundedRect(QRectF(soil_x - 8 * s, soil_y - 35 * s,
                                      soil_w + 16 * s, 40 * s), 8 * s, 8 * s)

        p.restore()


# ---------------------------------------------------------------------------
# Journaling scene — desk with open journal, writing appears progressively
# ---------------------------------------------------------------------------

class JournalingScene:
    """Renders a journaling scene: desk, open journal, progressive writing."""

    MOOD_TINTS = {
        "focused":    QColor(200, 170, 120, 30),
        "content":    QColor(220, 200, 140, 25),
        "happy":      QColor(247, 220, 111, 30),
        "curious":    QColor(200, 180, 130, 25),
        "worried":    QColor(180, 120, 100, 30),
        "frustrated": QColor(180, 100, 80, 25),
        "excited":    QColor(247, 220, 111, 35),
    }

    def __init__(self):
        self._active = False
        self._opacity = 0.0
        self._fading_in = False
        self._fading_out = False
        self._fish_face = "content"

        # Journal layout (set on first render)
        self._jrnl_x = 0.0
        self._jrnl_y = 0.0
        self._jrnl_w = 80.0
        self._jrnl_h = 55.0

        # Writing lines on right page
        self._lines: list[dict] = []
        self._max_lines = 8

        # Ink color (shifts with mood)
        self._ink_color = QColor(30, 30, 50)

        # Thinking state
        self._looking_up = False
        self._thought_bubble_alpha = 0.0

        # Journal closing animation
        self._closing = False
        self._close_progress = 0.0  # 0=open, 1=closed

        # End heart
        self._end_heart_alpha = 0.0
        self._finished = False

    @property
    def is_visible(self):
        return self._active or self._opacity > 0

    @property
    def is_active(self):
        return self._active

    def start(self):
        self._active = True
        self._opacity = 0.0
        self._fading_in = True
        self._fading_out = False
        self._finished = False
        self._fish_face = "content"
        self._lines = []
        self._ink_color = QColor(30, 30, 50)
        self._looking_up = False
        self._thought_bubble_alpha = 0.0
        self._closing = False
        self._close_progress = 0.0
        self._end_heart_alpha = 0.0

    def stop(self):
        self._finished = True
        self._closing = True
        self._end_heart_alpha = 1.0
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def interrupt(self):
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def set_face(self, face: str):
        self._fish_face = face
        if face in ("worried", "focused"):
            self._ink_color = QColor(50, 25, 20)  # warmer/darker
        else:
            self._ink_color = QColor(30, 30, 50)

    def get_tint(self):
        if not self._active:
            return None
        return self.MOOD_TINTS.get(self._fish_face)

    def set_looking_up(self, up: bool):
        self._looking_up = up

    def add_writing_line(self):
        """Add a handwritten line to the right page."""
        import random
        if len(self._lines) >= self._max_lines:
            return
        jx = self._jrnl_x
        jw = self._jrnl_w
        jy = self._jrnl_y

        # Right page starts at center
        page_left = jx + jw / 2 + 4
        page_right = jx + jw - 6
        line_y = jy + 10 + len(self._lines) * 5.5

        # Generate wavy line segments
        segments = []
        x = page_left
        while x < page_right - 3:
            seg_len = random.uniform(3, 8)
            wave = random.uniform(-1.0, 1.0)
            segments.append({'x': x, 'y': line_y + wave,
                             'len': min(seg_len, page_right - x)})
            x += seg_len + random.uniform(0.5, 2.0)
            if random.random() < 0.15:
                break  # variable line length

        self._lines.append({
            'segments': segments,
            'color': QColor(self._ink_color),
        })

    def close_journal(self):
        self._closing = True

    def update(self, dt: float):
        if self._fading_in:
            self._opacity = min(1.0, self._opacity + dt / 0.5)
            if self._opacity >= 1.0:
                self._fading_in = False
        elif self._fading_out:
            self._opacity = max(0.0, self._opacity - dt / 0.8)
            if self._opacity <= 0.0:
                self._fading_out = False

        # Thought bubble
        if self._looking_up:
            self._thought_bubble_alpha = min(1.0,
                                              self._thought_bubble_alpha + dt * 2.0)
        else:
            self._thought_bubble_alpha = max(0.0,
                                              self._thought_bubble_alpha - dt * 3.0)

        # Journal closing
        if self._closing:
            self._close_progress = min(1.0, self._close_progress + dt * 1.2)

        # End heart fade
        if self._end_heart_alpha > 0 and self._close_progress >= 0.8:
            self._end_heart_alpha = max(0.0, self._end_heart_alpha - dt * 0.4)

    def render(self, p: QPainter, fish_cx: float, fish_cy: float,
               display_size: float):
        if self._opacity <= 0:
            return

        ds = display_size
        s = ds / 80.0

        # Journal to the LEFT of fish, large and readable
        jw, jh = 95 * s, 70 * s
        fish_left = fish_cx - ds / 2.0
        jx = fish_left - ds * 0.1 - jw
        jy = fish_cy - jh * 0.3

        self._jrnl_x = jx
        self._jrnl_y = jy
        self._jrnl_w = jw
        self._jrnl_h = jh

        p.save()
        p.setOpacity(self._opacity)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cp = self._close_progress

        # === Desk surface ===
        desk_c = QColor(160, 120, 70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(desk_c))
        p.drawRoundedRect(QRectF(jx - 10 * s, jy + jh - 3 * s,
                                  jw + 20 * s, 8 * s), 2 * s, 2 * s)

        if cp < 0.9:
            # === Open journal ===
            # Left page
            left_w = jw / 2.0 * (1.0 - cp * 0.5)
            p.setBrush(QBrush(QColor(255, 252, 240)))
            p.setPen(QPen(QColor(180, 170, 140), 1.0))
            p.drawRect(QRectF(jx, jy, left_w, jh))

            # Right page
            right_x = jx + jw / 2.0
            right_w = jw / 2.0 * (1.0 - cp * 0.5)
            p.setBrush(QBrush(QColor(255, 253, 245)))
            p.drawRect(QRectF(right_x, jy, right_w, jh))

            # Spine
            p.setPen(QPen(QColor(139, 105, 20), 2.0))
            spine_x = jx + jw / 2.0
            p.drawLine(QPointF(spine_x, jy), QPointF(spine_x, jy + jh))

            # Ruled lines on left page
            p.setPen(QPen(QColor(180, 200, 220, 80), 0.5))
            line_count = max(3, int(jh / (4 * s)))
            for i in range(line_count):
                ly = jy + 7 * s + i * 4 * s
                if ly > jy + jh - 3 * s:
                    break
                p.drawLine(QPointF(jx + 3 * s, ly), QPointF(jx + left_w - 2 * s, ly))

            # Written lines on right page
            for line in self._lines:
                for seg in line['segments']:
                    c = QColor(line['color'])
                    pen = QPen(c, 1.2)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    p.setPen(pen)
                    p.drawLine(QPointF(seg['x'], seg['y']),
                               QPointF(seg['x'] + seg['len'], seg['y']))
        else:
            # === Closed journal ===
            p.setBrush(QBrush(QColor(139, 90, 43)))
            p.setPen(QPen(QColor(100, 65, 25), 1.2 * s))
            closed_h = jh * 0.15
            p.drawRoundedRect(QRectF(jx + 4 * s, jy + jh - closed_h - 2 * s,
                                      jw - 8 * s, closed_h), 2, 2)
            # Page edges visible
            p.setPen(QPen(QColor(240, 235, 220), 0.6 * s))
            p.drawLine(QPointF(jx + 5 * s, jy + jh - 1.5 * s),
                       QPointF(jx + jw - 5 * s, jy + jh - 1.5 * s))

        # === Thought bubble (when looking up) ===
        if self._thought_bubble_alpha > 0:
            ta = int(200 * self._thought_bubble_alpha)
            bub_x = jx + jw / 2.0
            bub_y = jy - 14 * s
            # Bubble
            p.setPen(QPen(QColor(120, 120, 140, ta), 0.8 * s))
            p.setBrush(QBrush(QColor(255, 255, 255, ta)))
            p.drawEllipse(QRectF(bub_x - 9 * s, bub_y - 7 * s, 18 * s, 12 * s))
            # Connector dots
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, ta)))
            p.drawEllipse(QRectF(bub_x - 1.5 * s, bub_y + 6 * s, 3 * s, 3 * s))
            p.drawEllipse(QRectF(bub_x + 0.5 * s, bub_y + 9 * s, 2 * s, 2 * s))
            # Ellipsis
            p.setPen(QPen(QColor(100, 100, 120, ta), 1.2 * s))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for dx in [-4, 0, 4]:
                p.drawEllipse(QRectF(bub_x + dx * s - 0.8 * s, bub_y - 1.5 * s,
                                     1.5 * s, 1.5 * s))

        # === End heart ===
        if self._end_heart_alpha > 0 and self._close_progress >= 0.8:
            ha = int(200 * self._end_heart_alpha)
            hx = jx + jw / 2.0
            hy = jy - 10 - (1.0 - self._end_heart_alpha) * 20
            heart_c = QColor(220, 80, 80, ha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(heart_c))
            path = QPainterPath()
            path.moveTo(hx, hy + 4)
            path.cubicTo(hx - 5, hy - 2, hx - 8, hy + 4, hx, hy + 8)
            path.cubicTo(hx + 8, hy + 4, hx + 5, hy - 2, hx, hy + 4)
            p.drawPath(path)

        p.restore()


# ---------------------------------------------------------------------------
# Piano scene — upright piano with keys, music notes, sheet music
# ---------------------------------------------------------------------------

class PianoScene:
    """Renders a piano scene: upright piano to the left, key presses, notes."""

    # Mood → key highlight color
    MOOD_KEY_COLORS = {
        "worried":    QColor(120, 150, 200, 160),   # muted blue (hesitant)
        "frustrated": QColor(120, 150, 200, 160),
        "focused":    QColor(120, 150, 200, 180),
        "content":    QColor(240, 200, 80, 180),     # warm gold (flowing)
        "happy":      QColor(240, 200, 80, 200),
        "excited":    QColor(240, 200, 80, 220),
        "curious":    QColor(180, 160, 220, 160),     # soft lavender
    }

    MOOD_TINTS = {
        "focused":    QColor(180, 160, 220, 25),
        "content":    QColor(240, 200, 80, 25),
        "happy":      QColor(247, 220, 111, 30),
        "worried":    QColor(120, 150, 200, 20),
        "frustrated": QColor(180, 100, 80, 20),
        "excited":    QColor(247, 220, 111, 35),
        "curious":    QColor(180, 160, 220, 20),
    }

    def __init__(self):
        self._active = False
        self._opacity = 0.0
        self._fading_in = False
        self._fading_out = False
        self._fish_face = "worried"

        # Piano layout (set on first render)
        self._piano_x = 0.0
        self._piano_y = 0.0
        self._piano_w = 90.0
        self._piano_h = 70.0

        # 14 keys: 10 white, 4 black (standard octave + extra)
        # White key indices: 0-9, Black key indices mapped to positions
        self._key_states: list[float] = [0.0] * 14  # press alpha per key
        self._key_presses: list[dict] = []  # {index, alpha}

        # Music notes floating up from keys
        self._notes: list[dict] = []

        # Sheet music — notes appear progressively
        self._sheet_notes: list[dict] = []
        self._phase = "hesitant"  # hesitant → flowing → peak

        # Final ripple
        self._ripple_active = False
        self._ripple_index = 0
        self._ripple_timer = 0.0
        self._ripple_keys: list[float] = [0.0] * 10  # white keys only

        # End heart
        self._end_heart_alpha = 0.0
        self._finished = False

    @property
    def is_visible(self):
        return self._active or self._opacity > 0

    @property
    def is_active(self):
        return self._active

    def start(self):
        self._active = True
        self._opacity = 0.0
        self._fading_in = True
        self._fading_out = False
        self._finished = False
        self._fish_face = "worried"
        self._key_presses = []
        self._notes = []
        self._sheet_notes = []
        self._phase = "hesitant"
        self._ripple_active = False
        self._ripple_index = 0
        self._ripple_timer = 0.0
        self._ripple_keys = [0.0] * 10
        self._end_heart_alpha = 0.0

    def stop(self):
        self._finished = True
        self._ripple_active = True
        self._ripple_index = 0
        self._ripple_timer = 0.0
        self._end_heart_alpha = 1.0
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def interrupt(self):
        self._fading_out = True
        self._fading_in = False
        self._active = False

    def set_face(self, face: str):
        self._fish_face = face
        if face in ("content", "happy", "excited"):
            self._phase = "flowing"
        elif face == "focused":
            self._phase = "flowing"

    def get_tint(self):
        if not self._active:
            return None
        return self.MOOD_TINTS.get(self._fish_face)

    def press_key(self, index: int):
        """Press a piano key — highlights it and spawns a floating note."""
        import random
        index = index % 10  # clamp to white keys
        self._key_presses.append({'index': index, 'alpha': 1.0})

        # Floating music note from this key
        pw = self._piano_w
        kx_start = self._piano_x + pw * 0.07
        key_w = (pw - pw * 0.14) / 10.0
        kx = kx_start + index * key_w + key_w / 2
        ky = self._piano_y + self._piano_h * 0.55
        self._notes.append({
            'x': kx + random.uniform(-2, 2),
            'y': ky,
            'vy': -random.uniform(15, 30),
            'vx': random.uniform(-4, 4),
            'alpha': 1.0,
            'size': random.uniform(4, 6),
        })

        # Add note to sheet music if in flowing phase
        if self._phase == "flowing":
            self._sheet_notes.append({
                'x_offset': len(self._sheet_notes) * 4.5 + random.uniform(-0.5, 0.5),
                'y_line': random.randint(0, 4),
            })

    def update(self, dt: float):
        if self._fading_in:
            self._opacity = min(1.0, self._opacity + dt / 0.5)
            if self._opacity >= 1.0:
                self._fading_in = False
        elif self._fading_out:
            self._opacity = max(0.0, self._opacity - dt / 0.8)
            if self._opacity <= 0.0:
                self._fading_out = False

        # Key press decay
        for kp in self._key_presses:
            kp['alpha'] -= dt * 3.0
        self._key_presses = [kp for kp in self._key_presses if kp['alpha'] > 0]

        # Floating notes
        for n in self._notes:
            n['y'] += n['vy'] * dt
            n['x'] += n['vx'] * dt
            n['alpha'] -= dt * 0.8
        self._notes = [n for n in self._notes if n['alpha'] > 0]

        # Final ripple — sequential key highlights
        if self._ripple_active:
            self._ripple_timer += dt
            if self._ripple_timer >= 0.08:
                self._ripple_timer = 0.0
                if self._ripple_index < 10:
                    self._ripple_keys[self._ripple_index] = 1.0
                    self._ripple_index += 1
            for i in range(10):
                self._ripple_keys[i] = max(0.0, self._ripple_keys[i] - dt * 1.5)
            if self._ripple_index >= 10 and max(self._ripple_keys) <= 0:
                self._ripple_active = False

        # End heart float up
        if self._end_heart_alpha > 0 and not self._ripple_active:
            self._end_heart_alpha = max(0.0, self._end_heart_alpha - dt * 0.3)

    def render(self, p: QPainter, fish_cx: float, fish_cy: float,
               display_size: float):
        if self._opacity <= 0:
            return

        ds = display_size
        s = ds / 80.0

        # Piano to the LEFT of the fish, large and prominent
        pw, ph = 140 * s, 75 * s
        fish_left = fish_cx - ds / 2.0
        gap = ds * 0.08
        px = fish_left - gap - pw
        py = fish_cy - ph * 0.4

        self._piano_x = px
        self._piano_y = py
        self._piano_w = pw
        self._piano_h = ph

        p.save()
        p.setOpacity(self._opacity)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # === Piano body (upright) ===
        body_c = QColor(50, 30, 15)
        body_hi = QColor(70, 45, 25)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(body_c))
        p.drawRoundedRect(QRectF(px, py, pw, ph), 2 * s, 2 * s)
        # Top edge highlight
        p.setBrush(QBrush(body_hi))
        p.drawRect(QRectF(px + 2 * s, py + s, pw - 4 * s, 2 * s))

        # === Music stand (above keys) ===
        stand_y = py + 6 * s
        stand_h = 13 * s
        stand_c = QColor(60, 38, 20)
        p.setBrush(QBrush(stand_c))
        p.drawRect(QRectF(px + 6 * s, stand_y, pw - 12 * s, stand_h))
        # Sheet of music — horizontal lines
        p.setPen(QPen(QColor(180, 170, 150, 120), 0.4 * s))
        for i in range(5):
            sy = stand_y + 3 * s + i * 2 * s
            p.drawLine(QPointF(px + 9 * s, sy), QPointF(px + pw - 9 * s, sy))
        # Notes on sheet (appear during flowing phase)
        p.setPen(Qt.PenStyle.NoPen)
        for sn in self._sheet_notes:
            nx = px + 10 * s + sn['x_offset'] * s
            if nx > px + pw - 10 * s:
                continue
            ny = stand_y + 3 * s + sn['y_line'] * 2 * s
            p.setBrush(QBrush(QColor(30, 30, 30, 180)))
            p.drawEllipse(QRectF(nx - s, ny - 0.8 * s, 2 * s, 1.5 * s))

        # === Keyboard area ===
        kb_y = py + ph * 0.45
        kb_h = ph * 0.45
        white_w = (pw - 8 * s) / 10.0
        key_x_start = px + 4 * s

        # White keys
        mood_color = self.MOOD_KEY_COLORS.get(self._fish_face,
                                               QColor(200, 200, 200, 120))
        for i in range(10):
            kx = key_x_start + i * white_w
            ky = kb_y

            # Check if key is pressed
            press_alpha = 0.0
            for kp in self._key_presses:
                if kp['index'] == i:
                    press_alpha = max(press_alpha, kp['alpha'])
            # Ripple highlight
            ripple_a = self._ripple_keys[i] if self._ripple_active else 0.0

            total_highlight = max(press_alpha, ripple_a)

            # Draw key
            if total_highlight > 0:
                # Pressed — slightly lower + colored
                offset = 1.2 * s * total_highlight
                p.setBrush(QBrush(QColor(
                    mood_color.red(), mood_color.green(), mood_color.blue(),
                    int(mood_color.alpha() * total_highlight))))
                p.setPen(QPen(QColor(160, 160, 160), 0.5))
                p.drawRect(QRectF(kx, ky + offset,
                                   white_w - 0.5, kb_h - offset))
            else:
                p.setBrush(QBrush(QColor(250, 248, 240)))
                p.setPen(QPen(QColor(180, 180, 170), 0.5))
                p.drawRect(QRectF(kx, ky, white_w - 0.5, kb_h))

        # Black keys (at specific positions in a standard octave pattern)
        # For 10 white keys (C D E F G A B C D E), black keys at:
        # C#(0.5), D#(1.5), F#(3.5), G#(4.5), A#(5.5), C#(7.5), D#(8.5)
        black_positions = [0.7, 1.7, 3.7, 4.7, 5.7, 7.7, 8.7]
        black_w = white_w * 0.6
        black_h = kb_h * 0.55
        for bp in black_positions:
            bx = key_x_start + bp * white_w - black_w / 2
            p.setBrush(QBrush(QColor(25, 25, 30)))
            p.setPen(QPen(QColor(15, 15, 15), 0.5))
            p.drawRect(QRectF(bx, kb_y, black_w, black_h))

        # === Floating music notes ===
        for n in self._notes:
            a = int(220 * max(0, n['alpha']))
            if a <= 0:
                continue
            c = QColor(mood_color.red(), mood_color.green(),
                       mood_color.blue(), a)
            sz = n['size']
            nx, ny = n['x'], n['y']
            # Note head
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(c))
            p.drawEllipse(QRectF(nx - sz / 3, ny, sz * 0.65, sz * 0.5))
            # Stem
            p.setPen(QPen(c, 1.0))
            p.drawLine(QPointF(nx + sz * 0.3, ny + sz * 0.2),
                       QPointF(nx + sz * 0.3, ny - sz * 0.7))

        # === End heart ===
        if self._end_heart_alpha > 0 and not self._ripple_active:
            ha = int(200 * self._end_heart_alpha)
            hx = px + pw / 2.0
            hy = py - 10 - (1.0 - self._end_heart_alpha) * 15
            heart_c = QColor(220, 100, 120, ha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(heart_c))
            path = QPainterPath()
            path.moveTo(hx, hy + 4)
            path.cubicTo(hx - 5, hy - 2, hx - 8, hy + 4, hx, hy + 8)
            path.cubicTo(hx + 8, hy + 4, hx + 5, hy - 2, hx, hy + 4)
            p.drawPath(path)

        p.restore()
