"""
QPainter pixel art renderer for Little Fish.
Renders at low internal resolution (32x32), then scaled up with nearest-neighbor.
No antialiasing — every shape is crisp pixel art.
"""

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPen, QBrush

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
            self._draw_prop(p, animator.active_prop)

        # Particles (drawn after face, around body)
        if hasattr(animator, 'particles'):
            self._draw_particles(p, animator.particles)

        # Rage tint overlay
        if self._rage_tint > 0:
            a = int(80 * self._rage_tint)
            p.fillRect(0, 0, PIXEL_CANVAS, PIXEL_CANVAS, QColor(255, 30, 30, a))

        p.end()
        return self._pixmap

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
        self._draw_eyes(p, max(blink, 0.35), shrink_h=2)
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
            # Tiny coffee cup held near right side
            cup = QColor(180, 120, 60)
            cream = QColor(240, 220, 180)
            steam = QColor(200, 200, 200, 140)
            x, y = B - 2, B + 12
            p.fillRect(x, y, 4, 5, cup)                   # cup body
            p.fillRect(x + 4, y + 1, 1, 3, cup)           # handle
            p.fillRect(x + 1, y + 1, 2, 1, cream)         # cream top
            p.fillRect(x + 1, y - 1, 1, 1, steam)         # steam
            p.fillRect(x + 2, y - 2, 1, 1, steam)         # steam

        elif prop == AnimProp.TINY_BOOK:
            # Small open book held below face
            cover = QColor(100, 140, 200)
            page = QColor(240, 235, 220)
            spine = QColor(70, 100, 160)
            x, y = B + 3, B + 20
            p.fillRect(x, y, 4, 5, cover)                 # left cover
            p.fillRect(x + 4, y, 4, 5, QColor(120, 160, 220))  # right cover
            p.fillRect(x + 1, y + 1, 3, 3, page)          # left page
            p.fillRect(x + 5, y + 1, 3, 3, page)          # right page
            p.fillRect(x + 4, y, 1, 5, spine)             # spine

        elif prop == AnimProp.BLANKET:
            # Blanket draped over lower half
            blanket = QColor(120, 100, 180, 200)
            edge = QColor(100, 80, 160, 220)
            p.fillRect(B - 1, B + 14, PIXEL_BODY + 2, 10, blanket)
            p.fillRect(B - 1, B + 14, PIXEL_BODY + 2, 1, edge)  # top edge
            # Fold detail
            p.fillRect(B + 3, B + 16, 6, 1, QColor(140, 120, 200, 180))
            p.fillRect(B + 12, B + 17, 5, 1, QColor(140, 120, 200, 180))

        elif prop == AnimProp.UMBRELLA:
            # Umbrella held above head
            canopy = QColor(60, 130, 200)
            dark = QColor(40, 100, 170)
            handle = QColor(120, 90, 60)
            # Canopy arc
            p.fillRect(B + 1, B - 5, 22, 1, dark)
            p.fillRect(B + 0, B - 4, 24, 1, canopy)
            p.fillRect(B + 1, B - 3, 22, 1, canopy)
            p.fillRect(B + 3, B - 2, 18, 1, canopy)
            # Handle
            p.fillRect(B + 12, B - 1, 1, 4, handle)
            p.fillRect(B + 11, B + 2, 1, 1, handle)       # hook

        elif prop == AnimProp.SUNGLASSES:
            # Cool sunglasses on the face
            frame = QColor(30, 30, 30)
            lens = QColor(40, 40, 60, 200)
            highlight = QColor(100, 100, 120, 150)
            ly = B + 8
            # Left lens
            p.fillRect(B + 5, ly, 5, 3, frame)
            p.fillRect(B + 6, ly + 1, 3, 1, lens)
            p.fillRect(B + 6, ly + 1, 1, 1, highlight)
            # Right lens
            p.fillRect(B + 14, ly, 5, 3, frame)
            p.fillRect(B + 15, ly + 1, 3, 1, lens)
            p.fillRect(B + 15, ly + 1, 1, 1, highlight)
            # Bridge
            p.fillRect(B + 10, ly, 4, 1, frame)

        elif prop == AnimProp.TOOTHBRUSH:
            # Toothbrush held near mouth
            handle_c = QColor(80, 180, 220)
            bristle = QColor(240, 240, 250)
            x, y = B + PIXEL_BODY, B + 14
            p.fillRect(x, y, 4, 1, handle_c)              # handle
            p.fillRect(x + 4, y - 1, 2, 3, bristle)       # bristles

        elif prop == AnimProp.TINY_WEIGHTS:
            # Tiny dumbbell held above head
            bar = QColor(120, 120, 130)
            weight = QColor(80, 80, 90)
            x, y = B + 4, B - 3
            p.fillRect(x + 3, y + 1, 8, 1, bar)           # bar
            p.fillRect(x, y, 3, 3, weight)                 # left weight
            p.fillRect(x + 11, y, 3, 3, weight)            # right weight

        elif prop == AnimProp.SNACK:
            # Small cookie/snack near left side
            cookie = QColor(210, 170, 100)
            chip = QColor(140, 100, 50)
            x, y = B - 2, B + 14
            p.fillRect(x, y, 4, 3, cookie)
            p.fillRect(x + 1, y + 1, 1, 1, chip)          # choc chip
            p.fillRect(x + 3, y, 1, 1, chip)              # choc chip

        elif prop == AnimProp.SCARF:
            # Warm scarf around lower body
            scarf = QColor(200, 70, 70, 200)
            stripe = QColor(220, 120, 120, 180)
            y = B + 18
            p.fillRect(B + 2, y, 20, 3, scarf)
            p.fillRect(B + 2, y + 1, 20, 1, stripe)
            # Hanging end
            p.fillRect(B + PIXEL_BODY - 2, y + 3, 2, 4, scarf)
            p.fillRect(B + PIXEL_BODY - 2, y + 4, 2, 1, stripe)

        elif prop == AnimProp.PARTY_HORN:
            # Party horn / noisemaker
            horn = QColor(220, 60, 180)
            tip = QColor(255, 200, 60)
            x, y = B + PIXEL_BODY, B + 15
            p.fillRect(x, y, 3, 2, horn)
            p.fillRect(x + 3, y, 2, 2, QColor(60, 180, 220))
            p.fillRect(x + 5, y, 1, 2, tip)

        elif prop == AnimProp.GIFT_BOX:
            # Small wrapped gift box
            box = QColor(220, 60, 60)
            ribbon = QColor(255, 215, 0)
            x, y = B - 3, B + 16
            p.fillRect(x, y, 6, 5, box)
            p.fillRect(x, y + 2, 6, 1, ribbon)            # horizontal ribbon
            p.fillRect(x + 3, y, 1, 5, ribbon)            # vertical ribbon
            p.fillRect(x + 2, y - 1, 3, 1, ribbon)        # bow

        elif prop == AnimProp.TELESCOPE:
            # Small telescope / spyglass
            tube = QColor(140, 120, 80)
            lens_c = QColor(180, 200, 240)
            x, y = B + PIXEL_BODY - 2, B + 4
            p.fillRect(x, y, 5, 2, tube)
            p.fillRect(x + 5, y - 1, 2, 4, tube)
            p.fillRect(x + 7, y, 1, 2, lens_c)

        elif prop == AnimProp.MIRROR:
            # Small hand mirror
            frame_c = QColor(180, 160, 100)
            glass = QColor(200, 220, 240)
            x, y = B - 4, B + 6
            p.fillRect(x, y, 4, 5, frame_c)
            p.fillRect(x + 1, y + 1, 2, 3, glass)
            p.fillRect(x + 1, y + 5, 1, 3, frame_c)      # handle

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
