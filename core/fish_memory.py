"""
Fish Memory — persistent memory system for Little Fish.
Stores important details/memories the fish remembers about the user
and its own experiences. Editable via the launcher.
"""

import json
from pathlib import Path


def _memory_path() -> Path:
    import os
    appdata = os.environ.get("APPDATA", "")
    d = Path(appdata) / "LittleFish" if appdata else Path.home() / ".littlefish"
    d.mkdir(parents=True, exist_ok=True)
    return d / "fish_memories.json"


MAX_MEMORIES = 50


class FishMemory:
    """Persistent memory store for the fish."""

    def __init__(self):
        self.memories: list[dict] = []
        # Each memory: {"text": str, "category": str, "pinned": bool}

    def add(self, text: str, category: str = "general"):
        """Add a new memory."""
        text = text.strip()
        if not text:
            return
        # Don't duplicate
        for m in self.memories:
            if m["text"].lower() == text.lower():
                return
        self.memories.append({"text": text, "category": category, "pinned": False})
        if len(self.memories) > MAX_MEMORIES:
            # Remove oldest non-pinned
            for i, m in enumerate(self.memories):
                if not m.get("pinned"):
                    self.memories.pop(i)
                    break
        self.save()

    def remove(self, index: int):
        """Remove memory by index."""
        if 0 <= index < len(self.memories):
            self.memories.pop(index)
            self.save()

    def edit(self, index: int, new_text: str):
        """Edit memory text by index."""
        if 0 <= index < len(self.memories):
            self.memories[index]["text"] = new_text.strip()
            self.save()

    def toggle_pin(self, index: int):
        """Toggle pinned status."""
        if 0 <= index < len(self.memories):
            self.memories[index]["pinned"] = not self.memories[index].get("pinned", False)
            self.save()

    def get_chat_context(self) -> str:
        """Build a context string for the AI system prompt."""
        if not self.memories:
            return ""
        lines = ["Things you remember about the user and your experiences:"]
        for m in self.memories[:20]:  # limit context size
            lines.append(f"- {m['text']}")
        return "\n".join(lines)

    def save(self):
        """Persist to disk."""
        try:
            data = [m for m in self.memories]
            _memory_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def load() -> "FishMemory":
        """Load from disk."""
        fm = FishMemory()
        try:
            p = _memory_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    fm.memories = data
        except (OSError, json.JSONDecodeError):
            pass
        return fm
