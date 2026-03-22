"""
Voice input for Little Fish.
Records audio via sounddevice, transcribes with multiple backends:
  1. Vosk (local, fast, offline — primary)
  2. faster-whisper (local, accurate — optional)
  3. Groq Whisper API (cloud, very accurate — if keys available)
  4. Google free STT (cloud, no key — last resort)
Includes: push-to-talk, always-on VAD mode, whisper/singing detection,
          conversation state machine (wake word → active listening window).
"""

import io
import json
import time as _time
import wave
import tempfile
import threading
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal, QTimer


SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
MAX_RECORD_SECONDS = 15
SILENCE_THRESHOLD = 100       # RMS below this = silence
SILENCE_DURATION = 0.6        # seconds of silence to stop recording (was 1.0)
VAD_THRESHOLD = 200           # RMS above this = voice activity
VAD_CONFIRM_CHUNKS = 3        # consecutive loud chunks to confirm speech
CONVERSATION_TIMEOUT = 10.0   # seconds of silence before leaving active mode
TTS_COOLDOWN_BASE = 1.0       # minimum seconds after TTS ends before listening
TTS_COOLDOWN_PER_CHAR = 0.04  # additional cooldown per character of TTS text
TTS_COOLDOWN_MAX = 4.0        # cap on dynamic cooldown


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
_NAME_TRIGGERS = ("little fish", "littlefish", "hey fish", "hi fish",
                  "pesciolino", "ciao fish")
_WAKE_WORDS = ("hey little fish", "hey fish", "little fish",
               "ciao little fish", "ciao fish", "ehi fish",
               "ciao pesciolino", "ehi pesciolino",
               "fish", "pesciolino")

# Energy gate thresholds for _should_transcribe()
MIN_ENERGY_RMS = 50           # skip audio quieter than this (silence/noise)
MIN_AUDIO_SECS = 0.3          # skip audio shorter than this (accidental blip)

# Known Whisper hallucination patterns (common ghost outputs on silence/noise)
import re as _re
_HALLUCINATION_RE = _re.compile(
    r'^[\s.!?,;:"\'\-…\u200b]*$'   # only punctuation / whitespace / ellipsis / zero-width
    r'|^.{0,2}$'                    # 1-2 chars (random junk)
    r'|[\u2E80-\u9FFF]'             # CJK characters (e.g. 謝謝)
    r'|[\u3040-\u30FF]'             # Japanese kana
    r'|[\uAC00-\uD7AF]'             # Korean
    r'|[\u0600-\u06FF]'             # Arabic
    r'|[\u0400-\u04FF]{3,}'         # Cyrillic blocks
    r'|^thank you for watching'
    r'|^thanks for watching'
    r'|please subscribe'
    r'|sottotitoli'
    r'|amara\.org'
    r'|^\W+$'                       # only non-word characters (covers "!", "!!", etc.)
    r'|^(you|\.)+$'                 # repeated "you" or dots
    r'|^bye[\s.!]*$'               # lone "bye" (Whisper ghost)
    r'|^okay[\s.!]*$'              # lone "okay" from ambient noise
    r'|^(uh|um|ah|oh|hmm)[\s.!]*$' # filler sounds
, _re.IGNORECASE)

# Short single-word filter: if transcription is 1 word and <= 3 chars,
# only allow it if it matches a known valid short utterance
_VALID_SHORT_WORDS = frozenset({
    "fish", "ciao", "hey", "hi", "yes", "no", "stop", "help",
    "mute", "play", "game", "news", "joke", "hide", "come",
    "mood", "rest", "sì", "ehi", "qui", "che", "dai",
})


class ConversationState(Enum):
    PASSIVE = auto()            # Waiting for wake word
    ACTIVE_LISTENING = auto()   # Listening for speech (no wake word needed)
    PROCESSING = auto()         # Transcription/AI response in progress
    SPEAKING = auto()           # TTS is playing


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
    # Conversation state signals
    conversation_started = pyqtSignal()   # PASSIVE → ACTIVE_LISTENING
    conversation_ended = pyqtSignal()     # → PASSIVE

    def __init__(self, config: dict, fish_name: str = "", tts=None, groq_keys: list | None = None):
        super().__init__()
        self._config = config
        self._recording = False
        self._groq_keys = groq_keys if groq_keys is not None else config.get("groq_keys", [])
        self._groq_key_index = 0
        self._fish_name = fish_name.lower().strip() if fish_name else ""
        self._tts_ref = tts  # reference to TTS for barge-in
        self._tts_cooldown_until = 0.0  # monotonic deadline after TTS ends
        self._last_tts_text = ""        # last text spoken by TTS (echo filter)

        # VAD mode
        self._vad_enabled = config.get("voice", {}).get("always_listening", False)
        self._vad_running = False
        self._vad_thread: Optional[threading.Thread] = None
        self._vad_stream = None   # live reference to the VAD InputStream
        self._vad_prebuffer: list = []  # chunks buffered before voice confirmed

        # Conversation state machine
        self._conv_state = ConversationState.PASSIVE
        self._conv_last_activity = 0.0  # monotonic timestamp
        self._manual_listen = False      # True when user clicks Listen button

        # Local STT engines (try Vosk first, then faster-whisper)
        self._vosk_recognizer = None
        self._whisper_model = None
        self._try_load_vosk()
        if self._vosk_recognizer is None:
            self._try_load_local_whisper()

    def _try_load_vosk(self):
        """Attempt to load Vosk for fast local STT. Auto-downloads model."""
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)  # suppress Vosk debug logs
            # Vosk auto-downloads a small model on first use
            model = Model(lang="en-us")
            self._vosk_recognizer = KaldiRecognizer(model, SAMPLE_RATE)
            self._vosk_recognizer.SetWords(True)
        except Exception:
            self._vosk_recognizer = None

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
        """Start recording in a background thread (manual Listen button)."""
        if self._recording:
            return
        self._recording = True
        self._manual_listen = True
        self.listening_started.emit()
        # Grab the VAD stream (if VAD is running) so we reuse it
        # instead of opening a competing second InputStream.
        stream_ref = self._vad_stream
        thread = threading.Thread(
            target=self._record_and_transcribe,
            kwargs={"vad_stream": stream_ref},
            daemon=True,
        )
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

    # ------------------------------------------------------------------
    # Conversation state machine
    # ------------------------------------------------------------------

    @property
    def conversation_state(self) -> ConversationState:
        return self._conv_state

    def enter_conversation(self):
        """Transition to ACTIVE_LISTENING (wake word detected externally or internally)."""
        if self._conv_state == ConversationState.PASSIVE:
            self._conv_state = ConversationState.ACTIVE_LISTENING
            self._conv_last_activity = _time.monotonic()
            self.conversation_started.emit()

    def on_tts_started(self, text: str = ""):
        """Called when TTS begins playing."""
        self._conv_state = ConversationState.SPEAKING
        self._conv_last_activity = _time.monotonic()
        if text:
            self._last_tts_text = text.lower().strip()

    def on_tts_finished(self):
        """Called when TTS finishes — return to ACTIVE_LISTENING with dynamic cooldown."""
        # Dynamic cooldown based on how long the TTS text was
        cooldown = min(TTS_COOLDOWN_MAX,
                       TTS_COOLDOWN_BASE + len(self._last_tts_text) * TTS_COOLDOWN_PER_CHAR)
        self._tts_cooldown_until = _time.monotonic() + cooldown
        print(f"[CONV] TTS cooldown {cooldown:.1f}s (text len={len(self._last_tts_text)})")
        if self._conv_state in (ConversationState.SPEAKING, ConversationState.PROCESSING):
            self._conv_state = ConversationState.ACTIVE_LISTENING
            self._conv_last_activity = _time.monotonic()
            print("[CONV] Active window — listening for follow-up")

    def _check_conversation_timeout(self):
        """Check if conversation should end due to silence timeout."""
        if self._conv_state == ConversationState.ACTIVE_LISTENING:
            if _time.monotonic() - self._conv_last_activity > CONVERSATION_TIMEOUT:
                self._conv_state = ConversationState.PASSIVE
                self.conversation_ended.emit()

    def _vad_loop(self):
        """Continuously monitor mic for voice activity."""
        print("[VAD] VAD loop started")
        chunk_size = int(SAMPLE_RATE * 0.1)
        loud_count = 0
        prebuffer = []  # rolling buffer of recent chunks for pre-buffering
        PREBUFFER_CHUNKS = 5  # keep last ~500ms
        prev_state = self._conv_state
        _rms_log_counter = 0  # periodic RMS logging
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype=DTYPE, blocksize=chunk_size) as stream:
                self._vad_stream = stream  # expose for manual listen reuse
                while self._vad_running:
                    if self._recording:
                        prebuffer.clear()
                        _time.sleep(0.5)
                        prev_state = self._conv_state
                        continue

                    self._check_conversation_timeout()

                    # Detect transition out of SPEAKING — flush mic buffer
                    cur_state = self._conv_state
                    if prev_state == ConversationState.SPEAKING and cur_state != ConversationState.SPEAKING:
                        # Discard 800ms of stale audio (TTS bleed / echo)
                        flush_chunks = 8  # 8 × 100ms
                        for _ in range(flush_chunks):
                            stream.read(chunk_size)
                        prebuffer.clear()
                        loud_count = 0
                        print(f"[VAD] Resuming listen at {_time.monotonic():.2f}")
                    prev_state = cur_state

                    data, _ = stream.read(chunk_size)

                    # Hard gate: discard audio while TTS is speaking + cooldown
                    if self._tts_ref and self._tts_ref.is_speaking:
                        continue
                    if _time.monotonic() < self._tts_cooldown_until:
                        continue

                    rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))

                    # Log RMS every ~2 seconds so we can see what the mic reads
                    _rms_log_counter += 1
                    if _rms_log_counter % 20 == 0:
                        print(f"[VAD] mic rms={rms:.0f} (threshold={VAD_THRESHOLD})")

                    # During TTS playback, keep reading (stream alive) but
                    # don't accumulate speaker audio into prebuffer
                    if cur_state == ConversationState.SPEAKING:
                        # Still check for barge-in
                        if rms > VAD_THRESHOLD:
                            loud_count += 1
                            if loud_count >= VAD_CONFIRM_CHUNKS:
                                loud_count = 0
                                if self._tts_ref is not None:
                                    print("[CONV] Barge-in — user interrupted TTS")
                                    self._tts_ref.stop_playback()
                                    _time.sleep(0.15)  # let audio fully stop
                                # Flush after barge-in too
                                for _ in range(2):
                                    stream.read(chunk_size)
                                prebuffer.clear()
                                self._conv_state = ConversationState.ACTIVE_LISTENING
                                prev_state = ConversationState.ACTIVE_LISTENING
                                print(f"[VAD] Resuming listen at {_time.monotonic():.2f}")
                        else:
                            loud_count = max(0, loud_count - 1)
                        continue

                    # Keep a rolling pre-buffer of recent audio
                    prebuffer.append(data.copy())
                    if len(prebuffer) > PREBUFFER_CHUNKS:
                        prebuffer.pop(0)

                    if rms > 3000:
                        self.mic_spike.emit()

                    if rms > VAD_THRESHOLD:
                        loud_count += 1
                        print(f"[VAD] Speech detected at {_time.monotonic():.2f}")
                        if loud_count >= VAD_CONFIRM_CHUNKS:
                            loud_count = 0

                            # Save pre-buffered audio so recording starts with it
                            self._vad_prebuffer = list(prebuffer)
                            prebuffer.clear()

                            self._recording = True
                            self.listening_started.emit()

                            if self._conv_state == ConversationState.ACTIVE_LISTENING:
                                self._conv_state = ConversationState.PROCESSING
                                self._conv_last_activity = _time.monotonic()

                            # Pass the existing VAD stream so we don't
                            # open a second InputStream (which hangs on
                            # some Windows audio drivers).
                            self._record_and_transcribe(vad_stream=stream)
                            loud_count = 0
                    else:
                        loud_count = max(0, loud_count - 1)
        except Exception as e:
            print(f"[VAD] ERROR in vad_loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._vad_stream = None
            self._vad_running = False

    # ------------------------------------------------------------------
    # Speech content analysis
    # ------------------------------------------------------------------

    def analyze_transcription(self, text: str):
        """Check transcription for compliments, insults, name, whisper hints, wake words."""
        lower = text.lower().strip()

        # Wake word detection → enter conversation mode
        for wake in _WAKE_WORDS:
            if wake in lower:
                self.enter_conversation()
                break

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

    def _is_echo(self, text: str) -> bool:
        """Return True if *text* looks like the mic picking up TTS output."""
        from difflib import SequenceMatcher
        a = text.lower().strip()
        b = self._last_tts_text
        if not b:
            return False
        # Exact or near-exact match
        ratio = SequenceMatcher(None, a, b).ratio()
        if ratio > 0.55:
            print(f"[STT] Echo similarity {ratio:.2f} — tts={b!r}")
            return True
        # Short fragment that appears inside the TTS text
        if len(a) < 30 and a in b:
            return True
        return False

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _should_transcribe(self, audio_data: np.ndarray) -> bool:
        """Return True only if audio contains real speech, not silence."""
        rms = float(np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)))
        duration = len(audio_data) / SAMPLE_RATE

        if rms < MIN_ENERGY_RMS:
            print(f"[WHISPER] Skipped — too quiet (rms={rms:.0f})")
            return False

        if duration < MIN_AUDIO_SECS:
            print(f"[WHISPER] Skipped — too short ({duration:.2f}s)")
            return False

        return True

    def _record_and_transcribe(self, vad_stream=None):
        try:
            audio_data = self._record_audio(existing_stream=vad_stream)
            if audio_data is None:
                self.listening_stopped.emit()
                self._recording = False
                return

            self.listening_stopped.emit()

            # Energy gate — only send real speech to Whisper
            if not self._should_transcribe(audio_data):
                self._recording = False
                return

            rms = float(np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)))
            dur = len(audio_data) / SAMPLE_RATE
            print(f"[WHISPER] Sending audio, duration: {dur:.2f}s, energy: {rms:.4f}")

            # Analyze audio characteristics before transcription
            self.analyze_audio_characteristics(audio_data)

            # Mark as processing
            if self._conv_state in (ConversationState.ACTIVE_LISTENING,
                                     ConversationState.PROCESSING):
                self._conv_state = ConversationState.PROCESSING

            text = self._transcribe(audio_data)
            self._recording = False
            print(f"[STT] Raw transcription: {text!r}")

            if text and text.strip():
                clean = text.strip()

                # Filter Whisper hallucinations (regex patterns)
                if _HALLUCINATION_RE.search(clean):
                    print(f"[STT] Filtered hallucination: {clean!r}")
                    self._manual_listen = False
                    return

                # Filter single short words (<=3 chars) that aren't valid commands
                words = clean.split()
                if len(words) == 1:
                    word_clean = words[0].strip('.,!?…').lower()
                    if len(word_clean) <= 3 and word_clean not in _VALID_SHORT_WORDS:
                        print(f"[STT] Filtered short word: {clean!r}")
                        self._manual_listen = False
                        return

                # Echo filter: if transcription closely matches what TTS just said, discard
                if self._last_tts_text and self._is_echo(clean):
                    print(f"[STT] Filtered echo of TTS: {clean!r}")
                    self._manual_listen = False
                    return

                print(f"[STT] Accepted: {clean!r}")
                self._conv_last_activity = _time.monotonic()
                # Analyze content for sentiment/name/wake words
                self.analyze_transcription(clean)
                self.transcription_ready.emit(clean)
            else:
                print("[STT] Empty transcription — all backends returned nothing")

            self._manual_listen = False

        except Exception as e:
            import traceback
            print(f"[VAD] Exception in _record_and_transcribe: {e}")
            traceback.print_exc()
            self._recording = False
            self.listening_stopped.emit()
            self.error_occurred.emit(str(e))

    def _record_audio(self, existing_stream=None) -> Optional[np.ndarray]:
        """Record until silence or max duration, prepending any VAD pre-buffer.

        If *existing_stream* is supplied (from the VAD loop) we read from
        it directly instead of opening a second sd.InputStream — opening
        two InputStreams on the same device hangs on many Windows drivers.
        """
        chunks = list(self._vad_prebuffer)  # start with pre-buffered audio
        self._vad_prebuffer.clear()
        silence_samples = 0
        max_samples = int(MAX_RECORD_SECONDS * SAMPLE_RATE)
        total_samples = sum(len(c) for c in chunks)
        chunk_size = int(SAMPLE_RATE * 0.1)  # 100ms chunks
        silence_dur = SILENCE_DURATION

        try:
            if existing_stream is not None:
                # Reuse the VAD loop's already-open stream
                self._read_until_silence(existing_stream, chunks, chunk_size,
                                         silence_dur, max_samples, total_samples)
            else:
                # Manual listen — open our own stream
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                    dtype=DTYPE, blocksize=chunk_size) as stream:
                    self._read_until_silence(stream, chunks, chunk_size,
                                             silence_dur, max_samples, total_samples)
        except Exception as e:
            print(f"[REC] Mic error: {e}")
            self.error_occurred.emit(f"Mic error: {e}")
            return None

        if not chunks:
            return None
        audio = np.concatenate(chunks)
        print(f"[REC] Recorded {len(audio)/SAMPLE_RATE:.2f}s, "
              f"RMS={float(np.sqrt(np.mean(audio.astype(np.float32)**2))):.0f}")
        return audio

    def _read_until_silence(self, stream, chunks, chunk_size,
                            silence_dur, max_samples, total_samples):
        """Read from *stream* appending to *chunks* until silence or max."""
        silence_samples = 0
        while self._recording and total_samples < max_samples:
            data, _ = stream.read(chunk_size)
            chunks.append(data.copy())
            total_samples += len(data)

            rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))
            if rms < SILENCE_THRESHOLD:
                silence_samples += len(data)
                if silence_samples > SAMPLE_RATE * silence_dur:
                    break
            else:
                silence_samples = 0

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def _transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio — Vosk → local whisper → Groq API → Google free STT.
        Vosk is English-only, so skip it unless language is explicitly 'en'.
        """
        voice_lang = self._config.get("voice", {}).get("voice_language", "auto")
        print(f"[STT] Starting transcription (lang={voice_lang}, audio={len(audio)/SAMPLE_RATE:.1f}s)")

        # Vosk only for explicit English — it mangles Italian into English gibberish
        if voice_lang == "en" and self._vosk_recognizer is not None:
            try:
                result = self._transcribe_vosk(audio)
                print(f"[STT] Vosk result: {result!r}")
                return result
            except Exception as e:
                print(f"[STT] Vosk failed: {e}")

        # Try local faster-whisper
        if self._whisper_model is not None:
            try:
                result = self._transcribe_local(audio)
                print(f"[STT] Local whisper result: {result!r}")
                return result
            except Exception as e:
                print(f"[STT] Local whisper failed: {e}")

        # Groq Whisper (supports Italian + English, language-aware)
        if self._groq_keys:
            try:
                result = self._transcribe_groq(audio)
                print(f"[STT] Groq result: {result!r}")
                return result
            except Exception as e:
                print(f"[STT] Groq failed: {e}")
        else:
            print("[STT] No Groq keys available!")

        # Vosk fallback for "auto" — better than nothing if cloud fails
        if voice_lang == "auto" and self._vosk_recognizer is not None:
            try:
                result = self._transcribe_vosk(audio)
                print(f"[STT] Vosk fallback result: {result!r}")
                return result
            except Exception as e:
                print(f"[STT] Vosk fallback failed: {e}")

        # Google free STT fallback (no API key needed)
        try:
            result = self._transcribe_google(audio)
            print(f"[STT] Google result: {result!r}")
            return result
        except Exception as e:
            print(f"[STT] Google failed: {e}")

        self.error_occurred.emit("No transcription method available. Check your microphone or internet connection.")
        return ""

    def _transcribe_vosk(self, audio: np.ndarray) -> str:
        """Transcribe using Vosk (fast, local, offline)."""
        self._vosk_recognizer.Reset()
        # Feed audio in chunks for Vosk
        raw = audio.tobytes()
        chunk_size = 4000
        for i in range(0, len(raw), chunk_size):
            self._vosk_recognizer.AcceptWaveform(raw[i:i + chunk_size])
        result = json.loads(self._vosk_recognizer.FinalResult())
        text = result.get("text", "").strip()
        if not text:
            raise ValueError("Vosk returned empty text")
        return text

    def _transcribe_local(self, audio: np.ndarray) -> str:
        """Transcribe using local faster-whisper."""
        wav_path = self._audio_to_wav_path(audio)
        try:
            segments, _ = self._whisper_model.transcribe(
                str(wav_path), beam_size=1,
            )
            return " ".join(seg.text for seg in segments).strip()
        finally:
            wav_path.unlink(missing_ok=True)

    def _transcribe_groq(self, audio: np.ndarray) -> str:
        """Transcribe using Groq Whisper API with key rotation."""
        import groq as groq_module

        wav_bytes = self._audio_to_wav_bytes(audio)
        last_error = None

        # Resolve language preference from settings
        voice_lang = self._config.get("voice", {}).get("voice_language", "auto")
        whisper_lang = None if voice_lang == "auto" else voice_lang

        for _ in range(len(self._groq_keys)):
            key = self._groq_keys[self._groq_key_index]
            try:
                client = groq_module.Groq(api_key=key)
                transcription = client.audio.transcriptions.create(
                    file=("audio.wav", wav_bytes),
                    model="whisper-large-v3",
                    language=whisper_lang,
                    prompt="Little Fish, companion, ciao, come stai, cosa fai, grazie, prego, capito, bene, sì, no, VSCode, Python",
                    temperature=0.0,
                    response_format="json",
                )
                text = transcription.text.strip()
                print(f"[STT] Groq Whisper: {text!r}")
                if not text:
                    raise ValueError("Groq returned empty text")
                return text
            except Exception as e:
                print(f"[STT] Groq key {self._groq_key_index} failed: {e}")
                last_error = e
                self._groq_key_index = (self._groq_key_index + 1) % len(self._groq_keys)

        raise last_error or RuntimeError("All Groq keys exhausted")

    def _transcribe_google(self, audio: np.ndarray) -> str:
        """Transcribe using Google free Speech Recognition (no API key).
        Single request with auto-detect for speed.
        """
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        raw_pcm = audio.tobytes()
        audio_data = sr.AudioData(raw_pcm, SAMPLE_RATE, 2)  # 2 bytes (int16)

        try:
            return recognizer.recognize_google(audio_data)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            raise RuntimeError(f"Google STT request failed: {e}")

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
