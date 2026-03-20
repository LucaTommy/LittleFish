"""
Text-to-speech wrapper for Little Fish.
Supports two providers:
  - pyttsx3 (offline, default)
  - ElevenLabs (cloud, requires API key)
Runs on a background thread to avoid blocking.
"""

import io
import threading
import queue
import tempfile

import pyttsx3


class TTS:
    def __init__(self, config: dict):
        self._config = config
        self._enabled = (config.get("voice", {}).get("tts_enabled", True)
                         and config.get("permissions", {}).get("tts", True))
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._speaking = False

        voice_cfg = config.get("voice", {})
        self._provider = voice_cfg.get("tts_provider", "pyttsx3")  # "pyttsx3" or "elevenlabs"
        self._elevenlabs_key = voice_cfg.get("elevenlabs_key", "")
        self._elevenlabs_voice = voice_cfg.get("elevenlabs_voice", "Rachel")

        # Init engine on background thread
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def say(self, text: str):
        """Queue text to be spoken. Non-blocking."""
        if self._enabled and text:
            self._queue.put(text)

    def stop(self):
        """Signal the worker to shut down."""
        self._queue.put(None)

    def _worker(self):
        """Background thread: owns TTS engine."""
        if self._provider == "elevenlabs" and self._elevenlabs_key:
            self._worker_elevenlabs()
        else:
            self._worker_pyttsx3()

    def _worker_pyttsx3(self):
        """pyttsx3 offline TTS loop."""
        try:
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
                # Default to a higher-pitched voice (Zira on Windows)
                for v in voices:
                    if "zira" in v.name.lower():
                        engine.setProperty("voice", v.id)
                        break
        except Exception:
            return

        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                self._speaking = True
                engine.say(text)
                engine.runAndWait()
            except Exception:
                pass
            finally:
                self._speaking = False

    def _worker_elevenlabs(self):
        """ElevenLabs cloud TTS loop."""
        import urllib.request
        import urllib.error
        import json

        # Resolve voice ID from name
        voice_id = self._resolve_elevenlabs_voice()
        if not voice_id:
            # Fallback to pyttsx3
            self._worker_pyttsx3()
            return

        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                self._speaking = True
                audio_data = self._call_elevenlabs(voice_id, text)
                if audio_data:
                    self._play_audio_bytes(audio_data)
            except Exception:
                pass
            finally:
                self._speaking = False

    def _resolve_elevenlabs_voice(self) -> str:
        """Look up an ElevenLabs voice ID by name. Returns voice_id or ''."""
        import urllib.request
        import urllib.error
        import json

        # Common default voice IDs so we don't have to call the API
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

        # Query API for custom voices
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
        import urllib.error
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

    @staticmethod
    def _play_audio_bytes(data: bytes):
        """Play MP3 audio bytes using a temp file."""
        import os
        import subprocess
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        try:
            tmp.write(data)
            tmp.close()
            # Use Windows Media.SoundPlayer (WAV) doesn't work for MP3.
            # Use wmplayer via COM or ffplay as fallback.
            subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-Command",
                 f'Add-Type -AssemblyName PresentationCore; '
                 f'$p = New-Object System.Windows.Media.MediaPlayer; '
                 f'$p.Open([Uri]::new(\"{tmp.name}\")); '
                 f'$p.Play(); '
                 f'Start-Sleep -Milliseconds 500; '
                 f'while($p.Position -lt $p.NaturalDuration.TimeSpan) {{ Start-Sleep -Milliseconds 100 }}; '
                 f'$p.Close()'],
                timeout=30, creationflags=0x08000000,
            )
        except Exception:
            try:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp.name],
                    timeout=30, creationflags=0x08000000,
                )
            except Exception:
                pass
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
