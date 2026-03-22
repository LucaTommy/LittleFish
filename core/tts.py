"""
Text-to-speech wrapper for Little Fish.
Supports three providers (priority order):
  1. ElevenLabs (cloud, requires API key — premium override)
  2. Edge TTS  (cloud, free, natural voices — primary engine)
  3. pyttsx3   (offline — emergency fallback)
Runs on a background thread to avoid blocking.
"""

import asyncio
import io
import os
import subprocess
import tempfile
import threading
import queue

# ---------------------------------------------------------------------------
# Language detection (simple, no external library)
# ---------------------------------------------------------------------------

ITALIAN_WORDS = {
    "ciao", "come", "cosa", "perché", "quando", "dove",
    "bene", "grazie", "prego", "sono", "hai", "non", "che",
    "una", "del", "della", "degli", "alle", "per", "con",
    "sì", "capito", "okay", "allora", "quindi", "però",
    "adesso", "ancora", "sempre", "anche", "molto", "bello",
    "stai", "questo", "questa", "tutto",
    "buongiorno", "buonasera", "scusa", "dimmi", "fai",
}


def detect_language(text: str) -> str:
    """Return 'it' if text looks Italian, else 'en'."""
    words = set(text.lower().split())
    italian_hits = len(words & ITALIAN_WORDS)
    return "it" if italian_hits >= 1 else "en"


class TTS:
    _mci_lock = threading.Lock()  # serialize all MCI calls across threads

    def __init__(self, config: dict):
        self._config = config
        self._enabled = (config.get("voice", {}).get("tts_enabled", True)
                         and config.get("permissions", {}).get("tts", True))
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._speaking = False
        self._lock = threading.Lock()
        self._last_text = ""  # last text queued for speaking (echo detection)

        voice_cfg = config.get("voice", {})
        self._provider = voice_cfg.get("tts_provider", "edge")  # "edge", "elevenlabs", or "pyttsx3"
        self._elevenlabs_key = voice_cfg.get("elevenlabs_key", "")
        self._elevenlabs_voice = voice_cfg.get("elevenlabs_voice", "Rachel")

        # Edge TTS voices
        self._edge_voice_en = voice_cfg.get("edge_voice_en", "en-US-AriaNeural")
        self._edge_voice_it = voice_cfg.get("edge_voice_it", "it-IT-ElsaNeural")

        # Init engine on background thread
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @property
    def is_speaking(self) -> bool:
        if self._speaking and not self._thread.is_alive():
            self._speaking = False
        return self._speaking

    def set_voice(self, lang: str, voice_name: str):
        """Update voice at runtime. lang is 'en' or 'it'."""
        if lang == "it":
            self._edge_voice_it = voice_name
        else:
            self._edge_voice_en = voice_name

    @property
    def last_text(self) -> str:
        return self._last_text

    def say(self, text: str):
        """Queue text to be spoken. Non-blocking."""
        if self._enabled and text:
            # Set speaking immediately so mouth sync starts right away
            with self._lock:
                self._speaking = True
            self._last_text = text
            self._queue.put(text)

    def stop(self):
        """Signal the worker to shut down."""
        self._queue.put(None)

    def stop_playback(self):
        """Immediately halt current audio playback (barge-in support)."""
        import ctypes
        try:
            with TTS._mci_lock:
                mci = ctypes.windll.winmm.mciSendStringW
                mci('stop lf_tts', None, 0, 0)
                mci('close lf_tts', None, 0, 0)
        except Exception:
            pass
        with self._lock:
            self._speaking = False

    # ------------------------------------------------------------------
    # Worker dispatch
    # ------------------------------------------------------------------

    def _worker(self):
        """Background thread: route to the appropriate TTS engine."""
        # ElevenLabs takes priority if configured
        if self._elevenlabs_key and self._provider in ("elevenlabs", "edge"):
            # Try ElevenLabs; fall back to Edge if voice resolution fails
            voice_id = self._resolve_elevenlabs_voice()
            if voice_id:
                self._worker_elevenlabs(voice_id)
                return

        # Primary: Edge TTS
        try:
            import edge_tts  # noqa: F401
            self._worker_edge()
            return
        except ImportError:
            pass

        # Fallback: pyttsx3
        self._worker_pyttsx3()

    # ------------------------------------------------------------------
    # Edge TTS engine (primary)
    # ------------------------------------------------------------------

    def _worker_edge(self):
        """Edge TTS loop — uses async edge_tts wrapped in a thread event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                with self._lock:
                    self._speaking = True
                lang = detect_language(text)
                voice = self._edge_voice_it if lang == "it" else self._edge_voice_en
                print(f"[TTS] Edge speak: lang={lang} voice={voice} text={text[:60]!r}")
                loop.run_until_complete(self._edge_speak(text, voice))
                print("[TTS] Edge speak finished")
            except Exception as e:
                print(f"[TTS] Edge TTS error: {e}")
                import traceback; traceback.print_exc()
                # Try pyttsx3 fallback for this one utterance
                self._pyttsx3_fallback_say(text)
            finally:
                with self._lock:
                    self._speaking = False

        loop.close()

    @staticmethod
    async def _edge_speak(text: str, voice: str):
        """Generate audio with edge_tts and play it."""
        import edge_tts

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            print(f"[TTS] Generating audio to: {tmp_path}")
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(tmp_path)
            exists = os.path.exists(tmp_path)
            size = os.path.getsize(tmp_path) if exists else 0
            print(f"[TTS] File exists={exists} size={size}")
            if exists and size > 0:
                print("[TTS] Playing audio...")
                TTS._play_mp3(tmp_path)
            else:
                print("[TTS] Audio file empty or missing, skipping playback")
        except Exception as e:
            print(f"[TTS] _edge_speak error: {e}")
            raise
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    @staticmethod
    def _play_mp3(path: str):
        """Play an MP3 file synchronously using Windows MCI (instant, no process spawn)."""
        import ctypes
        try:
            with TTS._mci_lock:
                mci = ctypes.windll.winmm.mciSendStringW
                alias = "lf_tts"
                mci(f'close {alias}', None, 0, 0)  # clean up any previous
                ret = mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, 0)
                if ret != 0:
                    raise RuntimeError(f"MCI open failed: {ret}")
                print(f"[TTS] MCI playing: {path}")
                mci(f'play {alias} wait', None, 0, 0)
                mci(f'close {alias}', None, 0, 0)
                print("[TTS] MCI playback done")
        except Exception as e:
            print(f"[TTS] MCI failed: {e}, trying ffplay fallback")
            # ffplay fallback
            try:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                    timeout=60,
                    creationflags=0x08000000,
                )
            except Exception as e2:
                print(f"[TTS] ffplay fallback also failed: {e2}")

    # ------------------------------------------------------------------
    # pyttsx3 fallback
    # ------------------------------------------------------------------

    def _worker_pyttsx3(self):
        """pyttsx3 offline TTS loop."""
        engine = self._init_pyttsx3()
        if engine is None:
            return

        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                with self._lock:
                    self._speaking = True
                engine.say(text)
                engine.runAndWait()
            except Exception:
                pass
            finally:
                with self._lock:
                    self._speaking = False

    def _pyttsx3_fallback_say(self, text: str):
        """One-shot pyttsx3 fallback for a single utterance."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            rate = engine.getProperty("rate")
            engine.setProperty("rate", int(rate * 1.2))
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass

    def _init_pyttsx3(self):
        """Initialize pyttsx3 engine. Returns engine or None."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            rate = engine.getProperty("rate")
            engine.setProperty("rate", int(rate * 1.2))

            voice_pref = self._config.get("voice", {}).get("tts_voice", "default")
            voices = engine.getProperty("voices")
            if voice_pref != "default":
                for v in voices:
                    if voice_pref.lower() in v.name.lower():
                        engine.setProperty("voice", v.id)
                        break
            else:
                for v in voices:
                    if "zira" in v.name.lower():
                        engine.setProperty("voice", v.id)
                        break
            return engine
        except Exception:
            return None

    # ------------------------------------------------------------------
    # ElevenLabs (premium override)
    # ------------------------------------------------------------------

    def _worker_elevenlabs(self, voice_id: str):
        """ElevenLabs cloud TTS loop."""
        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                with self._lock:
                    self._speaking = True
                audio_data = self._call_elevenlabs(voice_id, text)
                if audio_data:
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    try:
                        tmp.write(audio_data)
                        tmp.close()
                        self._play_mp3(tmp.name)
                    finally:
                        try:
                            os.unlink(tmp.name)
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                with self._lock:
                    self._speaking = False

    def _resolve_elevenlabs_voice(self) -> str:
        """Look up an ElevenLabs voice ID by name."""
        import urllib.request
        import json

        KNOWN = {
            "rachel": "21m00Tcm4TlvDq8ikWAM",
            "adam": "pNInz6obpgDQGcFmaJgB",
            "sam": "yoZ06aMxZJJ28mfd3POQ",
            "elli": "MF3mGyEYCl7XYWbV9V6O",
            "josh": "TxGEqnHWrfWFTfGW9XjX",
        }
        name_lower = self._elevenlabs_voice.lower()
        if name_lower in KNOWN:
            return KNOWN[name_lower]

        try:
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": self._elevenlabs_key},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                for v in data.get("voices", []):
                    if v.get("name", "").lower() == name_lower:
                        return v["voice_id"]
        except Exception:
            pass
        return ""

    def _call_elevenlabs(self, voice_id: str, text: str) -> bytes | None:
        """Call ElevenLabs TTS API and return MP3 bytes."""
        import urllib.request
        import json

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = json.dumps({
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.5},
        }).encode()

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "xi-api-key": self._elevenlabs_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except Exception:
            return None
