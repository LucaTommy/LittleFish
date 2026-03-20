# LITTLE FISH — Implementation Plan

## Overview

Little Fish is a persistent, emotionally-aware desktop pet built in Python with PyQt6.
He lives on your screen 24/7, reacts to your machine state, responds to voice commands,
controls the browser/system, and hosts minigames. He feels alive — not like software.

---

## Phase 1 — The Widget Lives

**Goal:** A draggable, breathing, blinking blue square with pixel eyes on the desktop.

### 1.1 — Project Skeleton & Dependencies

- Create the full directory structure (`core/`, `widget/`, `games/`, `config/`, `assets/`)
- Create `requirements.txt` with Phase 1 deps:
  - `PyQt6` — GUI framework
  - `psutil` — (prep for Phase 2, lightweight)
- Create `main.py` entry point
- Create `config/settings.json` with default values
- Add `__init__.py` files where needed

### 1.2 — The Fish Widget (`widget/fish_widget.py`)

- Frameless window (`Qt.FramelessWindowHint`)
- Always-on-top (`Qt.WindowStaysOnTopHint`)
- Transparent background (`Qt.WA_TranslucentBackground`)
- Tool window flag (no taskbar entry): `Qt.Tool`
- Fixed size: 160x160 px canvas (120px fish body + padding for particles/effects)
- Track position for dragging
- Implement drag:
  - `mousePressEvent` — record offset
  - `mouseMoveEvent` — move window
  - `mouseReleaseEvent` — trigger drop reaction
- Main render loop via `QTimer` at ~16ms interval (60fps)
- Delegate all painting to `renderer.py`
- Delegate all animation state to `animator.py`

### 1.3 — The Renderer (`widget/renderer.py`)

All drawing via `QPainter`, pixel art aesthetic. No image files — everything procedural.

**The Body:**
- 120x120 rounded rect, beveled look
- Base color: `#7EC8E3`, gradient to `#A8D8EA` (top-left to bottom-right)
- Subtle 2px darker border (`#5BA8C8`) for bevel effect
- Inner highlight line on top edge for 3D pop

**The Eyes (default/happy):**
- Two oval shapes, ~18x22px each
- Positioned at roughly (35, 42) and (73, 42) relative to body
- Pupil: small dark circle inside each eye, 8x8px
- Pupils can offset slightly toward cursor position later (Phase 4 polish)

**The Mouth (default/happy):**
- Small upward arc, 3px thick, at roughly y=80 relative to body
- Drawn with `QPainterPath` cubic bezier

**Face States (all implemented in Phase 1, driven by emotion later):**

| State | Eyes | Mouth |
|-------|------|-------|
| happy | normal ovals | upward curve |
| bored | half-closed (droopy top lid line) | flat horizontal line |
| curious | wide circles (larger radius) | small O shape |
| sleepy | thin horizontal lines (nearly shut) | flat, tiny |
| excited | large star/sparkle shapes | wide smile arc |
| worried | angled brow lines above eyes | wavy line |
| focused | narrow squint (compressed height) | straight line |
| talking | (same as current emotion) | alternating open/close rect |
| blink-closed | thin horizontal lines | (unchanged) |

Phase 1 renders: happy, blink-closed. Other states are coded but won't be emotion-driven until Phase 2.

**Rendering approach:**
- `render_body(painter, scale, rotation)` — body + bevel
- `render_eyes(painter, eye_state, blink_progress)` — eyes with blink interpolation
- `render_mouth(painter, mouth_state)` — mouth shape
- `render_particles(painter, particles)` — for zzz, sweat, sparkles (later phases)
- All coordinates relative to center; scale/rotation applied via `QTransform`

### 1.4 — The Animator (`widget/animator.py`)

Central animation state machine. Holds all running animations, blends them.

**Breathing (always active):**
- Scale oscillation: `1.0 → 1.015 → 1.0`
- Period: 3.5 seconds
- Formula: `scale = 1.0 + 0.015 * sin(2π * t / 3.5)`
- Applied to body transform before render

**Blinking:**
- State: `open`, `closing`, `closed`, `opening`
- Random interval between blinks: 2.5s to 6.0s (uniform random)
- Blink timing: 80ms close → 80ms open (160ms total)
- `blink_progress` float 0.0 (open) → 1.0 (closed) — renderer uses this to interpolate eye height
- Slow blink variant (for contentment): 200ms close → 200ms open
- Double blink variant (for surprise): two 160ms blinks with 80ms gap
- Rule: NEVER blink during talking state

**Reaction Animations (Phase 1 — drag only):**
- Reaction queue: list of `ReactionAnimation` objects
- Each has: keyframes (time → property values), easing function, callback on complete
- Only one reaction plays at a time; queue processes FIFO
- Phase 1 reactions:
  - **Flinch (on click):** scale to 0.85 over 80ms (ease-out), back to 1.0 over 120ms (ease-in-out)
  - **Wiggle (during drag):** rotation ±8° alternating, 4 cycles over 600ms
  - **Bounce (on drop):** scale 1.0→1.1 (80ms) → 0.95 (80ms) → 1.0 (100ms)

**Transition blending:**
- Face state changes crossfade over 300ms
- Interpolate between old and new eye/mouth positions using `t` (0→1 over 300ms, ease-in-out)

### 1.5 — Main Entry Point (`main.py`)

```
- QApplication setup
- Load config/settings.json
- Create FishWidget
- Show widget at saved position (or default 100,100)
- Start QTimer render loop
- app.exec()
```

### 1.6 — Phase 1 Deliverables Checklist

- [ ] Window appears, transparent, frameless, always-on-top, no taskbar icon
- [ ] Blue beveled square renders with pixel eyes and mouth
- [ ] Breathing animation runs smoothly at 60fps
- [ ] Blinking happens at random intervals (2.5–6s)
- [ ] All 7 emotion face states are renderable (happy shown by default)
- [ ] Left-click → flinch reaction
- [ ] Drag → wiggle reaction, window moves with cursor
- [ ] Drop → bounce reaction
- [ ] Widget stays within screen bounds
- [ ] Clean shutdown (no hanging threads)

---

## Phase 2 — Emotions React to Machine (future)

- `core/emotion_engine.py` — state machine, 500ms tick, decay toward baseline
- `core/system_monitor.py` — psutil CPU/battery/processes, idle detection, window title tracking
- `core/personality.py` — constants + config-driven baselines
- Background QThread for system monitoring (never block render)
- Signals feed into emotion engine → face changes smoothly
- All emotion triggers from the spec implemented

---

## Phase 3 — Voice + Commands (future)

- `core/voice.py` — sounddevice recording, faster-whisper or Groq Whisper transcription
- `core/command_parser.py` — regex patterns for all commands, Groq Llama fallback
- `core/tts.py` — pyttsx3 offline TTS
- Push-to-talk hotkey system
- Groq API key rotation logic
- Fish reacts to voice events (curious on hearing, happy on completion, confused on failure)

---

## Phase 4 — Reactions + Polish (future)

- Full reaction system: all triggers from spec
- Media detection (Windows Media Session API via winrt)
- Particle effects: zzz, sweat drops, sparkles, clock eyes
- Sound effects system (small wav blips)
- Eye tracking toward cursor
- Smooth rotation toward screen edge when media plays

---

## Phase 5 — Minigames (future)

- `games/game_manager.py` — BaseGame interface, game picker panel
- Bezier mouse control (`widget/mouse_control.py`)
- Games: Snake, Breakout, Flappy Fish, Whack-a-Mole, Memory Match
- Game panel slides open from Fish widget
- Fish reacts to game events

---

## Phase 6 — Config UI + Packaging (future)

- `config/config_ui.py` — PyQt6 settings panel
- System tray icon
- Auto-start on boot
- PyInstaller packaging
- All permissions toggleable

---

## Technical Decisions & Notes

### Why no image/sprite files for the face?
Everything is QPainter-drawn procedurally. This lets us:
- Smoothly interpolate between face states (crossfade via alpha)
- Scale without pixelation artifacts
- Animate individual features independently (eyes blink while mouth talks)
- Keep the repo tiny with no asset management

### Animation Architecture
- Single `QTimer` at 16ms (≈60fps) drives everything
- Each tick: `animator.update(dt)` → computes all animation states → `widget.update()` → `paintEvent` → `renderer.draw()`
- No separate threads for animation — all on the Qt main thread (GPU-friendly)
- System monitor runs on QThread, emits signals to main thread

### Easing Functions
Implement a small easing library:
- `ease_in_out_sine(t)` — primary, for breathing and most transitions
- `ease_out_cubic(t)` — for flinch/bounce (snappy)
- `ease_in_cubic(t)` — for gravity-like motion
- `linear(t)` — only for progress bars, never for character animation

### Performance Budget
- Idle CPU: <2% (timer fires at 60fps, but QPainter is hardware-accelerated)
- Memory: <80MB for Phase 1 (PyQt6 base is ~50MB)
- Render budget per frame: <2ms (simple geometry, no complex shaders)

### Config Loading
- `settings.json` loaded at startup into a Python dict
- Writes happen on change (debounced, 500ms, background thread)
- Missing keys filled with defaults — forward-compatible

---

## Decisions (Confirmed)

1. **Screen edges**: Free float + soft edge resistance. Not a snap, not a bounce — gentle reluctance to go off-screen. Feels alive.
2. **Right-click menu**: Yes, Phase 1. Minimal: Settings (placeholder), Games (placeholder), Quit.
3. **Multi-monitor**: Free movement across all screens. No cage.
4. **Startup position**: Always resume last position from settings.json.
5. **Sound**: Deferred to Phase 4. Get rendering stable first.
6. **Tray icon**: Minimal in Phase 1. Just Quit. Clean exit path for development.
