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
    error_occurred = pyqtSignal(str)
    ask_focus = pyqtSignal()  # emitted to ask user "what am I looking at?"

    def __init__(self, groq_keys: list[str]):
        super().__init__()
        self._groq_keys = groq_keys or []
        self._key_index = 0

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
            text = self._extract_text(img)
            if not text or len(text) < 20:
                self.review_ready.emit(
                    "I can barely read anything on screen. "
                    "Is it mostly images? I need readable text to review."
                )
                return
            review = self._send_to_groq(text, focus)
            self.review_ready.emit(review)
        except Exception as e:
            self.error_occurred.emit(f"Review failed: {e}")
