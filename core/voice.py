"""
Voice input for Little Fish.
Records audio via sounddevice, transcribes via Groq Whisper API.
Local faster-whisper support is optional — if not installed, uses Groq only.
Includes: push-to-talk, always-on VAD mode, whisper/singing detection.
"""

import io
import wave
import tempfile
import threading
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal, QTimer


SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
MAX_RECORD_SECONDS = 15
SILENCE_THRESHOLD = 500       # RMS below this = silence
SILENCE_DURATION = 1.5        # seconds of silence to stop recording
VAD_THRESHOLD = 800           # RMS above this = voice activity
VAD_CONFIRM_CHUNKS = 3        # consecutive loud chunks to confirm speech


# Sentiment word lists for compliment/insult/name detection
_COMPLIMENTS = frozenset({
    "good boy", "well done", "nice job", "great job", "you're awesome",
    "good fish", "love you", "so cute", "thank you", "thanks",
    "you're the best", "amazing", "perfect", "brilliant", "smart",
    "i like you", "beautiful", "wonderful", "excellent", "you rock",
})
_INSULTS = frozenset({
    "stupid", "useless", "dumb", "shut up", "go away",
    "annoying", "ugly", "hate you", "worst", "terrible",
    "idiot", "moron", "stop", "bad fish",
})
_NAME_TRIGGERS = ("little fish", "littlefish", "hey fish", "hi fish")


class VoiceRecorder(QObject):
    """
    Records audio from the microphone.
    Emits transcription_ready(str) when speech is transcribed.
    Emits listening_started() / listening_stopped() for UI feedback.
    """

    transcription_ready = pyqtSignal(str)
    listening_started = pyqtSignal()
    listening_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)
    # New detection signals
    compliment_detected = pyqtSignal()
    insult_detected = pyqtSignal()
    name_called = pyqtSignal()
    whisper_detected = pyqtSignal()
    singing_detected = pyqtSignal()
    mic_spike = pyqtSignal()

    def __init__(self, config: dict, fish_name: str = ""):
        super().__init__()
        self._config = config
        self._recording = False
        self._groq_keys = config.get("groq_keys", [])
        self._groq_key_index = 0
        self._fish_name = fish_name.lower().strip() if fish_name else ""

        # VAD mode
        self._vad_enabled = config.get("voice", {}).get("always_listening", False)
        self._vad_running = False
        self._vad_thread: Optional[threading.Thread] = None

        # Try to load faster-whisper for local transcription
        self._whisper_model = None
        whisper_mode = config.get("voice", {}).get("whisper_mode", "local")
        if whisper_mode == "local":
            self._try_load_local_whisper()

    def _try_load_local_whisper(self):
        """Attempt to load faster-whisper. Silently fails if not installed."""
        try:
            from faster_whisper import WhisperModel
            self._whisper_model = WhisperModel(
                "tiny",  # smallest model — fast, low memory
                device="cpu",
                compute_type="int8",
            )
        except ImportError:
            self._whisper_model = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_listening(self):
        """Start recording in a background thread."""
        if self._recording:
            return
        self._recording = True
        self.listening_started.emit()
        thread = threading.Thread(target=self._record_and_transcribe, daemon=True)
        thread.start()

    def stop_listening(self):
        """Signal to stop recording."""
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ------------------------------------------------------------------
    # VAD (Voice Activity Detection) — always-on mode
    # ------------------------------------------------------------------

    def start_vad(self):
        """Start always-on voice activity detection in background."""
        if self._vad_running:
            return
        self._vad_running = True
        self._vad_thread = threading.Thread(target=self._vad_loop, daemon=True)
        self._vad_thread.start()

    def stop_vad(self):
        """Stop VAD mode."""
        self._vad_running = False

    @property
    def vad_enabled(self) -> bool:
        return self._vad_enabled

    def _vad_loop(self):
        """Continuously monitor mic for voice activity."""
        chunk_size = int(SAMPLE_RATE * 0.1)
        loud_count = 0
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype=DTYPE, blocksize=chunk_size) as stream:
                while self._vad_running:
                    if self._recording:
                        # Don't interfere with active push-to-talk
                        import time as _t
                        _t.sleep(0.5)
                        continue
                    data, _ = stream.read(chunk_size)
                    rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))

                    # Mic spike detection (loud sudden noise)
                    if rms > 3000:
                        self.mic_spike.emit()

                    if rms > VAD_THRESHOLD:
                        loud_count += 1
                        if loud_count >= VAD_CONFIRM_CHUNKS:
                            # Voice activity confirmed — record and transcribe
                            loud_count = 0
                            self._recording = True
                            self.listening_started.emit()
                            self._record_and_transcribe()
                            loud_count = 0
                    else:
                        loud_count = max(0, loud_count - 1)
        except Exception:
            self._vad_running = False

    # ------------------------------------------------------------------
    # Speech content analysis
    # ------------------------------------------------------------------

    def analyze_transcription(self, text: str):
        """Check transcription for compliments, insults, name, whisper hints."""
        lower = text.lower().strip()

        # Name detection
        triggers = list(_NAME_TRIGGERS)
        if self._fish_name and self._fish_name not in ("little fish", "littlefish"):
            triggers.append(self._fish_name)
        for trigger in triggers:
            if trigger in lower:
                self.name_called.emit()
                break

        # Compliment detection
        for phrase in _COMPLIMENTS:
            if phrase in lower:
                self.compliment_detected.emit()
                break

        # Insult detection
        for phrase in _INSULTS:
            if phrase in lower:
                self.insult_detected.emit()
                break

    def analyze_audio_characteristics(self, audio: np.ndarray):
        """Analyze audio for whisper (low volume) or singing (sustained tones)."""
        if len(audio) < SAMPLE_RATE * 0.5:
            return

        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))

        # Whisper detection: low RMS but clearly has content
        if 100 < rms < 400:
            self.whisper_detected.emit()
            return

        # Singing detection: check for sustained tones via zero-crossing rate
        # Low zero-crossing rate = tonal/sustained, high = noise/speech
        signs = np.sign(audio.flatten().astype(np.float32))
        zero_crossings = np.sum(np.abs(np.diff(signs)) > 0)
        zcr = zero_crossings / len(audio)
        # Singing typically has ZCR < 0.05, speech > 0.05
        if zcr < 0.04 and rms > 500:
            self.singing_detected.emit()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _record_and_transcribe(self):
        try:
            audio_data = self._record_audio()
            if audio_data is None or len(audio_data) < SAMPLE_RATE * 0.3:
                self.listening_stopped.emit()
                self._recording = False
                return

            self.listening_stopped.emit()

            # Analyze audio characteristics before transcription
            self.analyze_audio_characteristics(audio_data)

            text = self._transcribe(audio_data)
            self._recording = False

            if text and text.strip():
                clean = text.strip()
                # Analyze content for sentiment/name
                self.analyze_transcription(clean)
                self.transcription_ready.emit(clean)

        except Exception as e:
            self._recording = False
            self.listening_stopped.emit()
            self.error_occurred.emit(str(e))

    def _record_audio(self) -> Optional[np.ndarray]:
        """Record until silence or max duration."""
        chunks = []
        silence_samples = 0
        max_samples = int(MAX_RECORD_SECONDS * SAMPLE_RATE)
        total_samples = 0
        chunk_size = int(SAMPLE_RATE * 0.1)  # 100ms chunks

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype=DTYPE, blocksize=chunk_size) as stream:
                while self._recording and total_samples < max_samples:
                    data, _ = stream.read(chunk_size)
                    chunks.append(data.copy())
                    total_samples += len(data)

                    rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))
                    if rms < SILENCE_THRESHOLD:
                        silence_samples += len(data)
                        if silence_samples > SAMPLE_RATE * SILENCE_DURATION:
                            break
                    else:
                        silence_samples = 0
        except Exception as e:
            self.error_occurred.emit(f"Mic error: {e}")
            return None

        if not chunks:
            return None
        return np.concatenate(chunks)

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def _transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio — local whisper first, Groq API fallback."""
        # Try local first
        if self._whisper_model is not None:
            try:
                return self._transcribe_local(audio)
            except Exception:
                pass

        # Groq API fallback
        if self._groq_keys:
            try:
                return self._transcribe_groq(audio)
            except Exception:
                pass

        self.error_occurred.emit("No transcription method available. Add Groq API keys or install faster-whisper.")
        return ""

    def _transcribe_local(self, audio: np.ndarray) -> str:
        """Transcribe using local faster-whisper."""
        # Write to temp wav file
        wav_path = self._audio_to_wav_path(audio)
        try:
            segments, _ = self._whisper_model.transcribe(
                str(wav_path), beam_size=1, language="en",
            )
            return " ".join(seg.text for seg in segments).strip()
        finally:
            wav_path.unlink(missing_ok=True)

    def _transcribe_groq(self, audio: np.ndarray) -> str:
        """Transcribe using Groq Whisper API with key rotation."""
        import groq as groq_module

        wav_bytes = self._audio_to_wav_bytes(audio)
        last_error = None

        for _ in range(len(self._groq_keys)):
            key = self._groq_keys[self._groq_key_index]
            try:
                client = groq_module.Groq(api_key=key)
                transcription = client.audio.transcriptions.create(
                    file=("audio.wav", wav_bytes),
                    model="whisper-large-v3",
                    response_format="text",
                    language="en",
                )
                return str(transcription).strip()
            except Exception as e:
                last_error = e
                # Rotate to next key
                self._groq_key_index = (self._groq_key_index + 1) % len(self._groq_keys)

        raise last_error or RuntimeError("All Groq keys exhausted")

    # ------------------------------------------------------------------
    # Audio helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _audio_to_wav_bytes(audio: np.ndarray) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # int16
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return buf.getvalue()

    @staticmethod
    def _audio_to_wav_path(audio: np.ndarray) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return Path(tmp.name)
