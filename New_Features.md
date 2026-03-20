100 Things Little Fish Can Do

🖥️ System Control (hardcoded)

Open any application by name
Close any application by name
Volume up / down / mute / exact percentage
Brightness up / down (laptop)
Take a screenshot and save it
Lock the screen
Empty the recycle bin
Show desktop (minimize all windows)
Restart / shutdown / sleep with confirmation
Switch between open windows
Open Task Manager
Kill a frozen process by name
Check disk space remaining
Eject USB device
Toggle WiFi on/off
Toggle Bluetooth on/off
Connect to a saved WiFi network by name
Check download/upload speed (fast.com or speedtest CLI)
Open Settings to a specific page
Change system theme (dark/light mode toggle)


📁 Files & Clipboard (hardcoded)

Open a specific folder by name ("open downloads", "open desktop")
Search for a file by name across the whole machine
Open the most recently modified file in a folder
Read clipboard contents aloud
Clear clipboard
Save clipboard content to a text file with timestamp
Create a new empty text file on desktop
Rename a file by voice
Move a file to a specific folder
Zip a folder by name


🌐 Browser & Web (hardcoded + free APIs)

Open any website
Google search a query
Open YouTube and search
Open YouTube channel by name
Open Spotify (app or web)
Open Netflix
Open your most visited sites (hardcoded favorites list)
Check current weather — wttr.in
Check weather for any city — wttr.in
Check weather forecast for tomorrow
Get a Wikipedia summary on any topic
Get today's top news headlines (NewsAPI free tier)
Check if a website is down (downforeveryoneorjustme API)
Translate a word or phrase (LibreTranslate free API)
Get the definition of a word (Free Dictionary API)
Get a random fun fact (uselessfacts.jsph.pl free API)
Get current exchange rate between two currencies (frankfurter.app free API)
Check if it's a public holiday today (date.nager.at free API)
Get sunrise/sunset times for your location
Get current air quality index for your city (OpenAQ free API)


⏰ Time & Productivity (hardcoded)

Set a timer for X minutes with voice alert
Set multiple simultaneous timers with names ("pasta timer", "laundry timer")
Set a reminder ("remind me in 2 hours to call mom")
Tell you the current time and date
Tell you what day of the week a date falls on
Calculate time between two dates
Start a Pomodoro session (25min work, 5min break, Fish tracks it)
Tell you how long your PC has been on
Wake-up alarm (plays sound at set time)
Count down to a specific date ("how many days until March 25")


💬 Conversation & Knowledge (Groq)

Answer any general knowledge question
Summarize a long text you paste or dictate
Explain a concept simply ("explain quantum computing like I'm 10")
Translate a sentence to any language
Write a short email draft by voice
Suggest what to watch (based on your mood, hardcoded preference list)
Suggest what to eat (random from a hardcoded favorites list)
Tell a joke
Tell a fun fact about a specific topic
Roast you (on demand, lightly)
Give you a motivational line (non-cringe, dry delivery)
Brainstorm ideas on a topic
Proofread a sentence you dictate
Help you name something (project, variable, pet)
Quiz you on a topic (generates questions via Groq)


🎵 Media Control (hardcoded via Windows Media Session)

Play / pause media
Next track
Previous track
Tell you what's currently playing
Set a sleep timer for media (pause after X minutes)
Open last played Spotify playlist
Search YouTube for a specific song and open it
Mute/unmute microphone system-wide
Switch audio output device (headphones vs speakers)
Lower volume gradually over 10 minutes (wind-down mode)


🧠 Smart Awareness (hardcoded)

Tell you how long you've been on the PC today
Tell you how long you've been in VS Code specifically
Warn you if you've been sitting for 2+ hours (posture reminder)
Tell you your current CPU / RAM / battery status
Tell you which apps are using the most CPU right now
Detect if a specific app has been open too long and suggest a break
Tell you the last time you took a break
Track how many voice commands you've used today
Tell you Little Fish's current mood and why
Give you a daily summary at end of day (mood log + what you did)


🎮 Games & Fun (hardcoded)

Launch a random minigame
Launch a specific minigame by name
Tell you your high scores
Challenge you to beat your best score
Flip a coin / roll a dice / pick a random number


Every item in this list is buildable without paying for anything beyond your existing Groq free tier. The Groq items (61–75) are the only ones touching the API. Everything else is libraries, free APIs, or pure Python.

🌱 The Core Concept — The Behavior Tick
Every 30-60 seconds, a background thread rolls the dice and potentially triggers an autonomous behavior. Not every tick does something — that would be annoying. The probability is low but consistent, like a real pet.
BEHAVIOR_TICK = 45  # seconds
BEHAVIOR_CHANCE = 0.3  # 30% chance something happens each tick
# Modified by current emotion — bored = higher chance, focused = lower
```

---

### 😴 Idle & Ambient Behaviors
- Falls asleep if no input for 30min — full sleep animation, zzz particles
- Wakes himself up randomly after a while — stretch, look around confused
- Yawns randomly when sleepy state is high
- Stares off to the side occasionally — eyes drift, holds for 3 seconds, snaps back
- Scratches himself (wiggle animation, brief)
- Stretches randomly — scale up slow, hold, back down
- Looks around the screen — eyes pan left, right, up, down
- Does a little spin for no reason when happy and bored simultaneously
- Sighs (tiny exhale animation + small puff particle)
- Taps foot equivalent — subtle rhythmic bob when waiting

---

### 🕐 Time-Triggered Behaviors
- **Every new hour** — wakes up, blinks clock eyes, goes back to idle
- **9am** — morning greeting, energetic animation, says good morning once
- **12pm** — lunch nudge ("you eaten?", dry delivery)
- **5pm** — end of work day comment if VS Code was open most of the day
- **11pm** — gets visibly sleepy, suggests you sleep too
- **Midnight exactly** — yawn sequence, sleepy state locked for 10min
- **Monday morning** — grumpy for 30min, slight attitude in responses
- **Friday afternoon** — noticeably more upbeat
- **Your birthday** (set in config) — party hat overlay, celebration particles all day
- **His birthday** (his install date) — anniversary celebration, remembers how long he's been alive

---

### 👀 Curiosity Behaviors
- Notices when you switch apps — brief glance toward screen, curious face
- Notices when a new USB is plugged in — looks around, perks up
- Notices when CPU spikes — worried glance, checks back, relaxes when it drops
- Notices when you're on YouTube — turns toward screen, settles in
- Notices when you open a game — excited, watches screen
- Notices when you've been on the same app for 3+ hours — comments once, doesn't nag
- Peeks at your clipboard occasionally (permission-gated) — curious animation, says nothing
- Reacts to loud audio from your speakers — jumps slightly, looks at screen

---

### 🎭 Attention-Seeking Behaviors (when bored threshold hit)
- Walks to a random position on screen via bezier movement — just relocates himself for no reason
- Nudges the mouse slightly — moves it 5px, stops, innocent face
- Throws a tiny particle at the screen and watches it fall
- Writes a one-word sticky note on screen ("bored", "hello?", "...")
- Bounces once, unprompted, then acts like nothing happened
- Stares directly at the cursor and follows it intensely for 10 seconds
- Does a little dance (rotation + scale animation, 3 seconds)
- Blows a bubble that floats up and pops (particle animation)
- Pretends to fall asleep, then one eye opens to check if you noticed
- Walks to the edge of the screen and peeks over it

---

### 💼 Work-Aware Behaviors
- Goes quiet and focused when VS Code is the active window
- After 25min of coding — Pomodoro nudge (one animation, no voice unless you respond)
- After 2 hours straight of coding — stronger break suggestion, won't repeat for 1 hour
- Notices when you're on Stack Overflow — sympathetic face, occasional dry comment
- Notices when you're on GitHub — approving nod
- Celebrates when you hit Ctrl+S repeatedly (productive streak)
- Winces when you hit Ctrl+Z repeatedly (debugging struggle)
- Goes into party mode briefly when you close VS Code after a long session

---

### 🌦️ World-Aware Behaviors
- Checks weather once in the morning — comments if it's raining or unusually hot
- Checks if it's a public holiday — relaxed mode all day, comments on it once
- Reacts to your system clock hitting specific dates (Halloween, Christmas, New Year)
- Notices if your battery is draining faster than usual — concerned
- Notices if you haven't restarted your PC in 5+ days — suggests it once

---

### 🎲 Random Personality Moments
- Occasionally has an opinion about nothing ("...hm.") — just a thought bubble
- Randomly picks a "word of the day" from the dictionary API and tells you at 10am
- Occasionally comments on the time ("it's 2am, just saying")
- Has a favorite color that changes monthly — occasionally mentions it unprompted
- Occasionally "finds" a random fun fact and shares it (uselessfacts API)
- Sometimes disagrees with himself — thought bubble appears, disappears, different one appears
- Occasionally rates your current app out of 10 (hardcoded opinions per app)
- Has a running streak counter — "day 12 of you not talking to me" (only if interaction is low)

---

### 🤝 Reactive Autonomy (responds to YOUR patterns)
- Notices you always open YouTube at a certain time — starts getting excited slightly before
- Notices your typical work hours — adjusts energy accordingly
- Notices if you're always on your PC past midnight — starts giving you a look
- If you ignore him for 3 days straight — sulk mode, slightly less responsive, recovers when you interact
- If you interact positively every day for a week — trust level increases, becomes more expressive
- Remembers the last game you played together — occasionally suggests it again

---

### Implementation Note for Opus
```
All autonomous behaviors run on a BehaviorEngine background thread.
Tick rate: 45 seconds.
Each tick: roll random float 0-1, compare against behavior_chance 
(modified by current emotion state).
If triggered: pick randomly from the pool of behaviors valid for 
current emotion + time + system state.
Each behavior has a cooldown — same behavior cannot repeat within 
its cooldown window.
Behaviors never interrupt voice commands or active reactions.
All behaviors are toggleable in settings under "Autonomous Behavior".
Intensity slider (0-100%) scales behavior_chance globally.