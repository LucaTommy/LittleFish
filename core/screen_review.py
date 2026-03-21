"""
Screen review for Little Fish.
Takes a screenshot via mss, extracts text via pytesseract (Tesseract OCR),
then sends it to Groq Llama for a brutally honest critique.
"""

import random
import threading
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal


# Each review picks a random angle so consecutive reviews sound different
REVIEW_ANGLES = [
    (
        "You are Little Fish, a senior dev doing a screen review. "
        "Look at the extracted text and identify SPECIFIC elements — button labels, "
        "headings, code snippets, menu items, layout clues. "
        "Name them. Tell the user exactly what you see that works and what doesn't. "
        "Be direct, 3-5 sentences. No asterisks, no fluff."
    ),
    (
        "You are Little Fish. The user builds tools and websites. "
        "They're showing you their screen. Read the extracted text carefully — "
        "quote specific words, labels, or sections you notice. "
        "Give one concrete suggestion to improve what you see, and one thing "
        "that's already solid. Be specific enough that they know exactly what to change. "
        "3-5 sentences, no padding."
    ),
    (
        "You are Little Fish, a blunt UX reviewer. "
        "Analyze the screen text like a first-time user would. "
        "Point out anything confusing, unclear, or poorly worded — reference the "
        "actual text you see. Then mention what reads clearly. "
        "If it's code, focus on readability and naming. "
        "3-5 sentences. No generic advice — only things that apply to THIS screen."
    ),
    (
        "You are Little Fish. The user wants your real take on their screen. "
        "Read every piece of text extracted and react to the whole picture: "
        "What's the first thing that jumps out? What's buried that shouldn't be? "
        "What would you change if you had 5 minutes? "
        "Reference specific text from the screen. 3-5 sentences, no filler."
    ),
    (
        "You are Little Fish, reviewing a screen for a developer who builds tools. "
        "Don't just say 'looks good' or 'needs work'. Point at specific text, labels, "
        "or UI copy from the OCR output. Say what a real user would stumble on. "
        "Then say what actually lands well. Be constructive, not just critical. "
        "3-5 sentences."
    ),
]

FOCUS_PROMPTS = {
    "design": (
        "This is a UI/web design. Focus on: visual hierarchy clues in the text, "
        "whether headings/labels make sense, spacing issues implied by text layout, "
        "and whether the page communicates its purpose in the first 2 seconds."
    ),
    "code": (
        "This is source code. Focus on: function/variable naming quality, "
        "obvious logic issues, complexity, readability. Quote specific names or lines."
    ),
    "copy": (
        "This is written content (marketing, docs, or UI copy). Focus on: "
        "clarity of message, tone consistency, whether it says what it needs to "
        "in as few words as possible. Quote specific phrases that work or don't."
    ),
    "data": (
        "This is a data display or dashboard. Focus on: whether the numbers/labels "
        "are understandable at a glance, if anything is misleading, and whether "
        "the layout helps or hinders comprehension."
    ),
}


class ScreenReviewer(QObject):
    """Screenshot → OCR → Groq critique pipeline."""

    review_ready = pyqtSignal(str)
    peek_ready = pyqtSignal(str)       # lightweight comment (autonomous)
    error_occurred = pyqtSignal(str)
    ask_focus = pyqtSignal()  # emitted to ask user "what am I looking at?"

    def __init__(self, groq_keys: list[str]):
        super().__init__()
        self._groq_keys = groq_keys or []
        self._key_index = 0
        # Last peek data for "where?" / pointing feature
        self._last_peek_boxes: list[dict] = []   # [{text, x, y, w, h}, ...]
        self._last_peek_comment: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review(self, focus: Optional[str] = None):
        """Capture screen, OCR, send to Groq. Non-blocking."""
        if not self._groq_keys:
            self.error_occurred.emit("No Groq API keys configured.")
            return
        thread = threading.Thread(
            target=self._run_review, args=(focus,), daemon=True
        )
        thread.start()

    def peek(self, window_title: str = "", process_name: str = ""):
        """Quick autonomous glance at the screen — short casual comment."""
        if not self._groq_keys:
            return
        thread = threading.Thread(
            target=self._run_peek,
            args=(window_title, process_name),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _capture_screen(self) -> "Image.Image":
        """Grab primary monitor screenshot, return PIL Image."""
        import mss
        from PIL import Image

        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return img

    def _extract_text(self, img: "Image.Image") -> str:
        """Run Tesseract OCR on a PIL Image."""
        import pytesseract
        import shutil

        # Auto-detect Tesseract path on Windows
        tess_path = shutil.which("tesseract")
        if not tess_path:
            import os
            default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.isfile(default):
                pytesseract.pytesseract.tesseract_cmd = default
        text = pytesseract.image_to_string(img)
        return text.strip()

    def _extract_text_with_boxes(self, img: "Image.Image") -> tuple[str, list[dict]]:
        """Run Tesseract OCR and return (full_text, list of word boxes).

        Each box: {"text": str, "x": int, "y": int, "w": int, "h": int}
        Coordinates are in screen pixels (primary monitor).
        """
        import pytesseract
        import shutil

        tess_path = shutil.which("tesseract")
        if not tess_path:
            import os
            default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.isfile(default):
                pytesseract.pytesseract.tesseract_cmd = default

        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        boxes = []
        words = []
        n = len(data["text"])
        for i in range(n):
            word = data["text"][i].strip()
            if not word:
                continue
            words.append(word)
            boxes.append({
                "text": word,
                "x": data["left"][i],
                "y": data["top"][i],
                "w": data["width"][i],
                "h": data["height"][i],
            })
        full_text = " ".join(words)
        return full_text, boxes

    def find_on_screen(self, query: str) -> Optional[tuple[int, int]]:
        """Search recent OCR data for text matching *query*.

        Returns (screen_x, screen_y) center of the best match, or None.
        Uses the bounding boxes stored from the last peek/review.
        """
        if not self._last_peek_boxes or not query:
            return None

        query_lower = query.lower().split()
        if not query_lower:
            return None

        boxes = self._last_peek_boxes

        # Try to find a consecutive run of words matching the query
        best_score = 0
        best_center = None

        for start in range(len(boxes)):
            matched = 0
            x_min, y_min, x_max, y_max = 9999999, 9999999, 0, 0
            for qi, qw in enumerate(query_lower):
                idx = start + qi
                if idx >= len(boxes):
                    break
                if qw in boxes[idx]["text"].lower():
                    matched += 1
                    b = boxes[idx]
                    x_min = min(x_min, b["x"])
                    y_min = min(y_min, b["y"])
                    x_max = max(x_max, b["x"] + b["w"])
                    y_max = max(y_max, b["y"] + b["h"])
            if matched > best_score:
                best_score = matched
                best_center = ((x_min + x_max) // 2, (y_min + y_max) // 2)

        # Also try single-word partial matches
        if best_score == 0:
            full_query = " ".join(query_lower)
            for b in boxes:
                if full_query in b["text"].lower() or b["text"].lower() in full_query:
                    best_center = (b["x"] + b["w"] // 2, b["y"] + b["h"] // 2)
                    best_score = 1
                    break

        return best_center if best_score > 0 else None

    def _send_to_groq(self, screen_text: str, focus: Optional[str]) -> str:
        """Send extracted text to Groq Llama for review."""
        import groq as groq_module

        system = random.choice(REVIEW_ANGLES)
        if focus and focus in FOCUS_PROMPTS:
            system += "\n" + FOCUS_PROMPTS[focus]

        # Give the model the raw text and force it to reference what it sees
        user_msg = (
            "Here is all the text I can read on the user's screen right now "
            "(extracted via OCR — layout order may be approximate):\n\n"
            "---\n"
            f"{screen_text[:6000]}\n"
            "---\n\n"
            "Based on ONLY this text, give your review. "
            "You MUST reference specific words, labels, or lines from above — "
            "do not give generic advice that could apply to any screen."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        last_error = None
        for _ in range(len(self._groq_keys)):
            key = self._groq_keys[self._key_index]
            try:
                client = groq_module.Groq(api_key=key)
                completion = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=0.9,
                    max_tokens=400,
                )
                return completion.choices[0].message.content.strip()
            except Exception as e:
                last_error = e
                self._key_index = (self._key_index + 1) % len(self._groq_keys)

        raise RuntimeError(f"All Groq keys failed: {last_error}")

    def _run_review(self, focus: Optional[str]):
        """Full pipeline on background thread."""
        try:
            img = self._capture_screen()
            text, boxes = self._extract_text_with_boxes(img)
            self._last_peek_boxes = boxes  # store for pointing
            if not text or len(text) < 20:
                self.review_ready.emit(
                    "I can barely read anything on screen. "
                    "Is it mostly images? I need readable text to review."
                )
                return
            review = self._send_to_groq(text, focus)
            self._last_peek_comment = review
            self.review_ready.emit(review)
        except Exception as e:
            self.error_occurred.emit(f"Review failed: {e}")

    # ------------------------------------------------------------------
    # Autonomous peek — lightweight screen glance
    # ------------------------------------------------------------------

    _PEEK_PROMPTS = [
        (
            "You are Little Fish, a desktop pet. You just glanced at the user's screen. "
            "Based on the text below, make ONE short casual observation or comment — "
            "like something you'd say while looking over someone's shoulder. "
            "1 sentence max, be specific to what you see. No asterisks."
        ),
        (
            "You are Little Fish. The user doesn't know you're looking at their screen. "
            "Read the text below and make ONE short witty remark about what they're doing. "
            "Be casual and natural — you're a friend peeking over their shoulder. "
            "1 sentence, be specific. No asterisks."
        ),
        (
            "You are Little Fish, a curious desktop pet. You noticed something on the user's screen. "
            "Read the text below and ask ONE short, specific question or make a brief comment "
            "about what you see. Sound genuinely curious, not robotic. 1 sentence. No asterisks."
        ),
    ]

    def _run_peek(self, window_title: str, process_name: str):
        """Lightweight OCR + short Groq comment on background thread."""
        try:
            img = self._capture_screen()
            text, boxes = self._extract_text_with_boxes(img)
            if not text or len(text) < 30:
                return  # Nothing readable, skip silently

            # Store boxes for "where?" / pointing feature
            self._last_peek_boxes = boxes

            import groq as groq_module

            context = ""
            if window_title:
                context = f"The user has '{window_title}' open"
                if process_name:
                    context += f" ({process_name})"
                context += ". "

            system = random.choice(self._PEEK_PROMPTS)
            user_msg = (
                f"{context}"
                f"Here's the text visible on their screen:\n\n"
                f"---\n{text[:3000]}\n---\n\n"
                "Your short comment (1 sentence):"
            )

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ]

            for _ in range(len(self._groq_keys)):
                key = self._groq_keys[self._key_index]
                try:
                    client = groq_module.Groq(api_key=key)
                    completion = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=messages,
                        temperature=0.9,
                        max_tokens=60,
                    )
                    reply = completion.choices[0].message.content.strip()
                    if reply:
                        self._last_peek_comment = reply
                        self.peek_ready.emit(reply)
                    return
                except Exception:
                    self._key_index = (self._key_index + 1) % len(self._groq_keys)
        except Exception:
            pass  # Autonomous peek failures are silent
