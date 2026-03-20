oh oh oh. alright. we got a base. but this is almost what I wanted. 

We now want to give Little Fish his life. 
We actually want to customize it even smaller. 
But; we want, him to be able to move talk on his own like questions, be curious. 

Highest priority additions, in order:
1. Idle behaviors (most impactful)
After 2-3 minutes of no interaction, he should do something on his own. Pick randomly from a small pool: look around (eyes shift left/right), stretch (quick scale up/down), yawn (mouth opens wide, slow), scratch (brief wiggle). This single change makes him feel inhabited vs. decorative.
2. Cursor awareness
His pupils track your mouse position subtly — not aggressively, just a small offset toward where the cursor is. Even 4-5px of movement makes him feel like he's watching you. Genuinely uncanny how alive this feels for almost zero code.
3. Time-based personality

Morning (8-11am): slightly more energetic, faster blink
Afternoon: neutral
Late night (11pm+): droopy, slow blink, occasionally nods off mid-idle
This costs almost nothing and makes him feel like he lives in your day

4. Random unprompted sounds (Phase 4 but worth jumping)
A tiny blip or boop every 5-10 minutes of idleness. Not a voice, just a sound. Like he sneezed. Makes you look over at him.
5. React to you opening VS Code specifically
He goes into focused mode — squints, quiets down, stops doing idle behaviors. Respects your work. When you close it, he perks back up. This one has the most personality payoff.

## LITTLE FISH — Complete Feature Backlog

---

### 🧠 Emotion & Personality

- Emotion decay system (all emotions drift toward baseline over time)
- Monday detection — grumpy for first 30 minutes
- Friday detection — slightly more excited all day
- Morning boost (8–11am) — happy baseline +0.1
- Late night mode (11pm–5am) — sleepy baseline, slower everything
- Seasonal awareness — Christmas (Dec 25), Halloween (Oct 31), New Year's Eve, his own "birthday" (whatever date you pick)
- Weather integration via free API (wttr.in, no key needed) — rainy day = slightly sad, sunny = happy boost
- Personality config sliders in settings (curiosity, boredom threshold, attention seeking, chattiness, sleep resistance)
- Mood memory — if you ignored him all day yesterday, he starts today slightly sulky
- "Trust level" system — the more you interact positively, the more expressive and bold he gets over time
- Reaction to being left alone overnight — morning greeting animation when you return

---

### 👁️ Awareness & Reactivity

- Cursor tracking — pupils follow mouse with subtle offset (4–6px max)
- Idle detection — no input for 15min triggers bored state
- Deep idle (45min+) — falls asleep
- Wake reaction — stretch + excited flash when you return
- Active window tracking — knows what app you're in
- VS Code detected — focused mode, quiets down
- YouTube in browser title — happy, turns toward screen
- Spotify/music detected — bobs slightly, happy
- Game detected (Steam, any .exe in games folder) — excited
- CPU spike >80% — worried, sweat drop particle
- CPU returns to normal — relieved exhale animation
- Battery low (<15%) — worried spike
- Battery plugged in — happy flash, small spark particle
- Battery full (100%) — small celebration
- RAM >90% used — stressed face
- New USB device connected — curious, looks around
- Webcam activated — notices, looks at screen
- Screen locked / away — pauses all activity, enters deep sleep
- Screen unlocked — wakes up, greeting reaction
- System time = exactly midnight — yawn sequence, sleepy
- New hour — tiny clock-eye blink
- Clipboard change detected — curious peek (optional, permission-gated)
- Network disconnected — worried face, small antenna-down particle
- Network reconnected — relieved, happy flash
- Microphone spike (you're talking nearby) — ears perk, curious
- Notification sound detected (audio spike pattern) — looks around
- Fullscreen app detected — Fish minimizes to corner automatically, returns when fullscreen exits

---

### 🎭 Reactions & Animations

- Left click — flinch then look at cursor
- Right click — context menu appears
- Double click — surprised double blink, excited flash
- Drag — wiggle, annoyed face
- Drop — bounce
- Flick (fast drag + release) — slides with momentum, hits edge, bounces back
- Edge collision — bounce off screen edges with squish animation
- Thrown against edge hard — brief stars particle, shakes it off
- Long press (hold click 2s+) — he grabs your finger, annoyed face, pulls away
- Ignored for 30min — falls asleep (slow blink x3, eyes close, zzz floats)
- Wake from sleep — stretch, yawn, excited
- Pet (slow mouse movement over him) — happy, purr-like animation, eyes half close
- Rapid clicking — gets dizzy, spiral eyes briefly
- Shake (rapid drag back and forth) — very annoyed, refuses to look at you briefly
- Voice command received — perks up, curious
- Voice command success — happy bounce
- Voice command fail — confused head tilt, small question mark particle
- Minigame win — celebration animation, confetti particles
- Minigame loss — droopy sad face, recovers after 3s
- Screenshot taken — blinks like a camera flash
- File dropped onto him — inspects it, curious animation
- Ctrl+Z detected (undo) — sympathetic wince
- Ctrl+S detected (save) — approving nod
- Error sound from system — worried glance
- Media play detected — turns toward screen
- Media pause — turns back to you
- Media stop — looks at you expectantly
- Song skip — surprised blink
- Volume maxed — covers ears equivalent (eyes scrunch)
- Midnight — yawn sequence
- Seasonal event detected — special costume overlay (Santa hat, witch hat, party hat)

---

### 💬 Voice & Communication

- Push-to-talk (hold key, default Right Ctrl)
- Always-on VAD mode (voice activity detection, optional)
- Groq Whisper transcription (API, key rotation across 4 keys)
- faster-whisper local transcription (offline fallback)
- Pattern-matched commands (no AI needed for most)
- Groq Llama NLP fallback for unrecognized commands
- TTS responses via pyttsx3 (offline)
- ElevenLabs free tier TTS (optional, better voice)
- Voice feedback on every command (confirms what he's doing)
- "Good morning" / "Good night" contextual greetings
- Small talk responses (hardcoded pool of personality-consistent lines)
- Compliment detection ("good boy", "well done") — very happy reaction
- Insult detection ("stupid", "useless") — hurt face, sulks briefly
- Name response — reacts when you say "Little Fish"
- Whisper detection (low mic volume) — leans in, curious
- Singing detection (sustained tones) — dances subtly

---

### 🌐 Browser & System Control

- Open any website by voice
- Open YouTube + search query by voice
- Open YouTube channel by name (fuzzy match a hardcoded list + search fallback)
- Open Spotify (app or web)
- Open specific app by name (fuzzy match installed apps)
- Close app by name
- Volume up / down / mute by voice
- Screenshot by voice command
- Google search by voice ("search for...")
- Open file explorer
- Set a timer ("set a timer for 10 minutes") — he counts down, alerts you
- Reminder system ("remind me in 1 hour to...") — he tells you when time is up
- Paste clipboard content by voice
- Lock screen by voice
- Shutdown / restart with confirmation dialog

---

### 🎮 Minigames

- Game picker panel (slides out from Fish widget)
- Fish grabs mouse via bezier curve movement to invite you
- Snake — Fish cheers on food, mourns on death
- Breakout — Fish reacts to near-misses
- Flappy Fish — Fish IS the character
- Whack-a-Mole — Fish laughs at misses
- Memory Match — Fish covers eyes during flip
- Pong — Fish controls one paddle (plays against you)
- Minesweeper lite
- Typing speed test — Fish judges your WPM
- Reaction time test — Fish drops something, you click it
- Trivia — Fish asks questions, reacts to answers
- High score tracking per game
- Fish taunts/encourages based on your performance
- "Challenge me" voice command launches random game

---

### ✨ Particles & Visual Effects

- zzz particle (sleepy state, floats upward)
- Sweat drop (worried/stressed)
- Sparkle burst (excited/happy peak)
- Heart particle (when petted or complimented)
- Question mark (confused)
- Exclamation mark (surprised)
- Music note (music detected)
- Star burst (celebration)
- Confetti (win)
- Clock symbol eyes (on the hour)
- Small spark (battery plugged in)
- Antenna-down icon (network lost)
- Snow particles (December, optional)
- Falling leaves (October, optional)

---

### 🎨 Appearance & Customization

- Size slider (80px – 200px)
- Opacity slider (50% – 100%)
- Custom color picker for body (replaces default blue)
- Alternate eye styles (round, square, star, heart)
- Alternate mouth styles
- Seasonal costume overlays (Santa hat, witch hat, party hat, sunglasses)
- Custom name (rename him from "Little Fish")
- Dark / light widget border toggle
- Glow effect toggle (subtle outer glow matching body color)
- Custom idle animations (community-contributed, loaded from JSON)

---

### ⚙️ System & Config

- Full permissions panel (toggle each capability on/off)
- Personality sliders (curiosity, boredom, attention seeking, chattiness, sleep resistance)
- Startup on boot toggle
- Save/restore position across sessions
- Multi-monitor free movement
- Right-click context menu (Settings, Games, Sleep, Quit)
- System tray icon (show/hide Fish, quick quit)
- Auto-update checker (GitHub releases)
- Export/import settings (share your Fish config)
- Reset to defaults button
- "Fish log" — a simple text log of what he's been noticing/doing (debug + fun)
- Hotkey customization for push-to-talk and other shortcuts

---

### 🌙 Long-term / Ambitious

- Relationship system — tracks positive vs. negative interactions, changes personality expression
- Dream mode — when asleep, thought bubble shows pixel art of random things
- Two Fish mode — run two instances, they notice each other and interact
- Fish writes you a note — occasionally leaves a small sticky note on screen ("I'm bored", "you've been working 3 hours")
- Mood history graph in settings (30-day emotional state log)
- Fish learns your schedule — notices patterns and starts anticipating them
- Community mood — optional anonymous data share, Fish reflects "global Fish mood" for the day

Great addition. Here's the full picture before you prompt the agent.

---

## The Launcher / Updater App

This is a **separate application** from Little Fish himself. Think of it like the Epic Games Launcher, but tiny and charming. It has one job: manage Little Fish.

---

### What it is

A small desktop app (also PyQt6, also packaged with PyInstaller) that:

- Lives in the taskbar permanently
- Is the **only thing that auto-starts on boot** — it then decides whether to launch Fish
- Handles installing, updating, and launching Little Fish
- Shows Fish's current mood/status in the taskbar icon itself

---

### Taskbar Icon Behavior

This is the killer feature of the launcher. The taskbar icon is **not static** — it reflects Little Fish's current emotional state:

- Happy → blue icon, normal eyes
- Sleepy → half-closed eyes on icon
- Worried → small exclamation on icon
- Bored → flat mouth visible
- Excited → sparkle on icon

16x16 or 32x32 pixel art, rendered dynamically. It updates every few seconds. People will notice it and love it.

---

### Launcher UI — Main Screen

Clean, minimal window. Dark theme. Pixel aesthetic matching Fish.

```
┌─────────────────────────────────────┐
│  🐟 Little Fish Launcher      — □ × │
├─────────────────────────────────────┤
│                                     │
│         [Fish idle animation]       │
│         Little Fish v1.2.0          │
│         Status: Running 🟢          │
│                                     │
│  [  Launch / Stop Fish  ]           │
│                                     │
│  ─────────────────────────────────  │
│  Update available: v1.3.0           │
│  "Emotions + cursor tracking"       │
│  [ Update Now ]  [ Skip ]           │
│                                     │
│  ─────────────────────────────────  │
│  [ Settings ]  [ Mood Log ]  [ ?]   │
└─────────────────────────────────────┘
```

---

### Update System

Two options, pick one based on how you want to distribute:

**Option A — GitHub Releases (recommended)**
- Launcher checks `api.github.com/repos/yourname/little-fish/releases/latest` on startup
- Compares version tag to local `version.json`
- If newer: shows update panel, downloads the zip, extracts, replaces files, restarts Fish
- Free, no server needed, works forever

**Option B — Self-hosted JSON manifest**
- You host a `manifest.json` somewhere (even a GitHub Gist)
- Contains latest version number + download URL + changelog
- Launcher fetches it, same flow as above
- More control over rollout

Go with **Option A**. Less infrastructure, GitHub gives you release notes for free.

---

### Version file

Every Little Fish install has a `version.json`:

```json
{
  "version": "1.2.0",
  "install_date": "2025-03-10",
  "channel": "stable"
}
```

Channels: `stable` and `beta`. Power users can opt into beta in settings.

---

### Full Feature List for the Launcher

**Core:**
- Launch / stop Little Fish
- Auto-launch Fish on launcher start (toggleable)
- Launcher auto-starts on Windows boot (registry entry or startup folder)
- Check for updates on startup + once daily
- Download + install updates with progress bar
- Changelog display per update
- Rollback to previous version (keeps one backup)

**Status panel:**
- Fish running / stopped indicator
- Current emotional state (reads from a small shared state file Fish writes)
- Uptime counter ("Fish has been alive for 3h 22m")
- Today's mood summary ("Mostly focused, briefly worried at 3pm")

**Mood log viewer:**
- Simple timeline of emotional states throughout the day
- Small pixel art Fish face icons next to each entry
- Filterable by emotion, searchable by date

**Settings passthrough:**
- Open Fish's full settings panel from the launcher
- Quick toggles for the most common permissions

**About / credits:**
- Version info
- Your name + Leonardo's name
- Link to GitHub / website

---

### Tech for the Launcher

Same stack as Fish — PyQt6, PyInstaller. Two separate executables:

```
LittleFishLauncher.exe   ← installs to Program Files, adds to taskbar/startup
LittleFish.exe           ← lives in AppData/LittleFish/, managed by launcher
```

Launcher manages Fish's process directly (`subprocess.Popen`, tracks PID).

Communication between them: a tiny **shared JSON file** in AppData that Fish writes to every 30 seconds (current emotion, uptime, last event). Launcher reads it. Simple, no sockets needed.

---

### Packaging & Installation

The user downloads one thing: `LittleFishSetup.exe`

Built with **NSIS** (free Windows installer builder) or **Inno Setup** (simpler, also free). It:

1. Installs the Launcher to `Program Files/LittleFish/`
2. Installs Fish itself to `AppData/Local/LittleFish/`
3. Creates a Start Menu shortcut
4. Adds Launcher to startup
5. Optionally creates a desktop shortcut
6. Runs the Launcher immediately after install

First run experience: Launcher opens, Fish spawns for the first time, does a special "first boot" animation (hatches from an egg? swims in from the side? your call).

---

### Prompt addition for your agent

When you're ready to build this, add this block to your master prompt or as a follow-up:

```
Build a separate PyQt6 application: the Little Fish Launcher.
It is a standalone desktop app that manages the Little Fish process.
It auto-starts on Windows boot, lives in the taskbar with a dynamic
icon that reflects Fish's current emotional state (read from a shared
AppData JSON state file that Fish writes every 30 seconds).

The launcher handles: launch/stop Fish, check for updates via GitHub
Releases API, download and install updates with a progress bar, display
a mood log timeline, and surface Fish's settings panel.

UI: dark theme, pixel aesthetic matching Fish, ~400x500px window,
minimizes to taskbar (not system tray — actual taskbar pinnable app).

Packaging: PyInstaller for both executables. Inno Setup script for the
combined installer (LittleFishSetup.exe). Installer puts Launcher in
Program Files, Fish in AppData/Local/LittleFish/, adds Launcher to
Windows startup, creates Start Menu entry.

Shared state file: AppData/Local/LittleFish/state.json — Fish writes
current emotion, uptime, last_event every 30 seconds. Launcher reads it.
```

---

This makes Little Fish feel like a **real shipped product**, not a script you run from a terminal. That gap matters a lot for how people perceive it.