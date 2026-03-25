"""
Code assistant for Little Fish.
Analyzes code from clipboard, screen, or direct input.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Groq helpers
# ---------------------------------------------------------------------------

def _get_groq_client(groq_keys: list):
    """Create a Groq client from available keys."""
    if not groq_keys:
        return None
    try:
        import groq as groq_module
        return groq_module.Groq(api_key=groq_keys[0])
    except Exception:
        return None


def _ask_groq(client, system_prompt: str, user_content: str, max_tokens: int = 250) -> str:
    """Send a prompt to Groq and return the response text."""
    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Public API — every function returns a plain string
# ---------------------------------------------------------------------------

def analyze_code(code: str, groq_keys: list, question: str = "") -> str:
    """Analyze code and explain what it does or what's wrong."""
    client = _get_groq_client(groq_keys)
    if not client:
        return "I need Groq AI keys to analyze code. Add them in Settings."
    try:
        if question:
            system = (
                "You are a code reviewer. Answer the user's specific question "
                "about the code. Be direct and concise, 2-3 sentences max."
            )
            user = f"Question: {question}\n\nCode:\n{code[:3000]}"
        else:
            system = (
                "You are a code reviewer. Analyze this code briefly. "
                "Explain what it does in 2-3 sentences, then list any bugs "
                "or improvements you notice. Be direct and specific."
            )
            user = code[:3000]
        return _ask_groq(client, system, user, max_tokens=150)
    except Exception as e:
        return f"Code analysis failed: {e}"


def find_bugs(code: str, groq_keys: list) -> str:
    """Find bugs in code specifically."""
    client = _get_groq_client(groq_keys)
    if not client:
        return "I need Groq AI keys to find bugs. Add them in Settings."
    try:
        system = (
            "Find bugs in this code. List each bug on a new line with: "
            "what the bug is, which line it's on if identifiable, and how to fix it. "
            "Be specific. If no bugs found, say so."
        )
        return _ask_groq(client, system, code[:3000], max_tokens=200)
    except Exception as e:
        return f"Bug search failed: {e}"


def explain_error(error_message: str, groq_keys: list, code_context: str = "") -> str:
    """Explain an error message in plain language."""
    client = _get_groq_client(groq_keys)
    if not client:
        return "I need Groq AI keys to explain errors. Add them in Settings."
    try:
        system = (
            "Explain this error in simple terms and tell me how to fix it. "
            "Keep it under 3 sentences."
        )
        user = f"Error: {error_message[:1500]}"
        if code_context:
            user += f"\n\nRelevant code:\n{code_context[:1500]}"
        return _ask_groq(client, system, user, max_tokens=150)
    except Exception as e:
        return f"Error explanation failed: {e}"


def improve_code(code: str, groq_keys: list) -> str:
    """Suggest improvements for code."""
    client = _get_groq_client(groq_keys)
    if not client:
        return "I need Groq AI keys to improve code. Add them in Settings."
    try:
        system = (
            "Suggest 2-3 specific improvements for this code. "
            "Focus on: readability, performance, best practices. "
            "Be brief and specific. Show the improved version if short."
        )
        return _ask_groq(client, system, code[:3000], max_tokens=250)
    except Exception as e:
        return f"Code improvement failed: {e}"


def generate_code(description: str, language: str, groq_keys: list) -> str:
    """Generate code from description."""
    client = _get_groq_client(groq_keys)
    if not client:
        return "I need Groq AI keys to generate code. Add them in Settings."
    try:
        system = (
            f"Write {language} code that does what the user describes. "
            "Return ONLY the code, no explanation. Keep it clean and commented."
        )
        return _ask_groq(client, system, description, max_tokens=400)
    except Exception as e:
        return f"Code generation failed: {e}"


# ---------------------------------------------------------------------------
# Clipboard / file helpers
# ---------------------------------------------------------------------------

_CODE_INDICATORS = re.compile(
    r"(?:^|\s)(?:def |class |function |import |from |var |const |let |"
    r"return |if |else |for |while |try:|except |catch |=>|"
    r"#include|public |private |void |\{|\}|//|/\*|<!DOCTYPE|<html)",
    re.MULTILINE,
)


def get_clipboard_code() -> tuple:
    """Get code from clipboard. Returns (code, is_code)."""
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            return ("", False)
        clipboard = app.clipboard()
        text = clipboard.text() or ""
        if not text.strip():
            return ("", False)
        # Detect if content looks like code
        matches = len(_CODE_INDICATORS.findall(text))
        is_code = matches >= 2 or text.strip().startswith(("{", "[", "def ", "class ", "import ", "from ", "#!", "<!"))
        return (text[:3000], is_code)
    except Exception:
        return ("", False)


_CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
    ".md", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".rb",
    ".php", ".sh", ".bat", ".ps1", ".yaml", ".yml", ".toml", ".xml",
})


def get_active_file_content() -> tuple:
    """Try to read the currently active file in VSCode.
    Returns (content, filename) or ("", "")."""
    import os
    try:
        # VSCode stores recent files in storage.json
        appdata = os.environ.get("APPDATA", "")
        storage_path = Path(appdata) / "Code" / "storage.json"
        if not storage_path.exists():
            # Try User/globalStorage
            storage_path = Path(appdata) / "Code" / "User" / "globalStorage" / "storage.json"
        if not storage_path.exists():
            return ("", "")

        import json
        data = json.loads(storage_path.read_text(encoding="utf-8"))

        # Look for recently opened files
        recent = data.get("openedPathsList", {}).get("entries", [])
        for entry in recent:
            file_uri = entry.get("fileUri", "")
            if not file_uri:
                continue
            # Convert file URI to path
            if file_uri.startswith("file:///"):
                fpath = file_uri[8:]  # Strip file:///
                if os.name == "nt":
                    fpath = fpath.replace("/", "\\")
                    # Handle drive letter
                    if fpath.startswith("\\") and len(fpath) > 2 and fpath[2] == ":":
                        fpath = fpath[1:]
            else:
                continue

            p = Path(fpath)
            if p.suffix.lower() in _CODE_EXTENSIONS and p.exists():
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > 3000:
                    content = content[:3000] + "\n... (truncated)"
                return (content, p.name)

        return ("", "")
    except Exception:
        return ("", "")
