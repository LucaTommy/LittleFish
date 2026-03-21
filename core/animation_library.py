"""
Little Fish Animation Library — complex multi-step animation sequences.

Each animation is a sequence of timed steps. A step can:
- Set a face state
- Queue a reaction
- Spawn particles
- Show/hide a prop on the renderer
- Nudge position (offset_x, offset_y)
- Trigger a blink variant
- Say something (optional, most are silent)

Animations are selected autonomously by the behavior engine based on
emotion, time of day, weather, and season. The fish performs them
because he wants to, not because he was told to.
"""

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class AnimProp(Enum):
    """Visual props that can be overlaid on the fish during animations."""
    NONE = auto()
    COFFEE_CUP = auto()
    TINY_BOOK = auto()
    BLANKET = auto()
    UMBRELLA = auto()
    SUNGLASSES = auto()
    TINY_WEIGHTS = auto()
    SNACK = auto()
    SCARF = auto()
    PARTY_HORN = auto()
    GIFT_BOX = auto()
    TELESCOPE = auto()
    # Hobby props
    EASEL = auto()
    HANDHELD_GAME = auto()
    POTTED_PLANT = auto()
    JOURNAL = auto()
    TINY_PIANO = auto()


@dataclass
class AnimStep:
    """A single step in an animation sequence."""
    delay: float = 0.0          # seconds after previous step
    face: Optional[str] = None  # face state to transition to
    reaction: Optional[str] = None  # ReactionType name to queue
    particle: Optional[str] = None  # particle kind to spawn
    particle_count: int = 1     # how many of that particle
    prop: Optional[AnimProp] = None  # prop to show (None = don't change)
    hide_prop: bool = False     # if True, hide current prop
    blink: Optional[str] = None  # "slow", "double", "nod_off"
    offset_x: float = 0.0      # temporary position nudge
    offset_y: float = 0.0
    message: Optional[str] = None  # optional speech
    look_dir: Optional[tuple] = None  # (dx, dy) gaze direction override


@dataclass
class AnimSequence:
    """A complete animation the fish can perform."""
    name: str
    category: str  # daily_life, weather, emotional, activity, silly, seasonal
    steps: list[AnimStep] = field(default_factory=list)
    duration: float = 0.0  # auto-calculated
    cooldown: float = 300.0  # seconds before can repeat
    last_played: float = 0.0

    def __post_init__(self):
        if self.steps and self.duration == 0.0:
            t = 0.0
            for s in self.steps:
                t += s.delay
            self.duration = t


# -----------------------------------------------------------------------
# Animation Definitions
# -----------------------------------------------------------------------

def _build_library() -> dict[str, AnimSequence]:
    """Build the complete animation library. Returns dict of name -> sequence."""
    lib = {}

    # ===================================================================
    # DAILY LIFE — cozy everyday things
    # ===================================================================

    # --- Sipping coffee — slow, content, savoring ---
    lib["coffee_sip"] = AnimSequence("coffee_sip", "daily_life", [
        AnimStep(delay=0.0, face="content", prop=AnimProp.COFFEE_CUP),
        AnimStep(delay=0.6, blink="slow"),
        AnimStep(delay=0.8, offset_y=-1.0),                        # lift to sip
        AnimStep(delay=0.5, particle="emote_coffee"),
        AnimStep(delay=0.6, offset_y=0.0, face="happy", reaction="NOD"),
        AnimStep(delay=0.8, blink="slow", particle="emote_coffee"),
        AnimStep(delay=0.5, face="content", hide_prop=True),
        AnimStep(delay=0.4, blink="slow"),
    ], cooldown=600)

    # --- Eating a snack — nom nom nom ---
    lib["eat_snack"] = AnimSequence("eat_snack", "daily_life", [
        AnimStep(delay=0.0, face="curious", prop=AnimProp.SNACK),
        AnimStep(delay=0.5, face="happy"),
        AnimStep(delay=0.3, offset_y=1.0),                         # nom
        AnimStep(delay=0.25, offset_y=0.0),
        AnimStep(delay=0.3, offset_y=1.0),                         # nom
        AnimStep(delay=0.25, offset_y=0.0, particle="sparkle"),
        AnimStep(delay=0.3, offset_y=1.0),                         # nom
        AnimStep(delay=0.25, offset_y=0.0),
        AnimStep(delay=0.5, face="content", hide_prop=True, particle="sparkle"),
        AnimStep(delay=0.4, blink="slow"),
    ], cooldown=900)

    # --- Reading a tiny book — eyes scanning, cozy ---
    lib["read_book"] = AnimSequence("read_book", "daily_life", [
        AnimStep(delay=0.0, face="focused", prop=AnimProp.TINY_BOOK),
        AnimStep(delay=0.8, look_dir=(-0.5, 0.3)),                 # read left
        AnimStep(delay=1.0, look_dir=(0.5, 0.3), blink="slow"),    # read right
        AnimStep(delay=0.8, look_dir=(-0.3, 0.3)),
        AnimStep(delay=0.7, face="curious", reaction="HEAD_TILT"),
        AnimStep(delay=0.8, look_dir=(0.3, 0.3), blink="slow"),
        AnimStep(delay=0.5, face="content", hide_prop=True),
        AnimStep(delay=0.4, look_dir=(0.0, 0.0), blink="slow"),
    ], cooldown=600)

    # --- Big stretch — idle stiffness relief ---
    lib["big_stretch"] = AnimSequence("big_stretch", "daily_life", [
        AnimStep(delay=0.0, face="bored"),
        AnimStep(delay=0.4, reaction="STRETCH"),
        AnimStep(delay=0.5, offset_y=-2.0),                        # reach up
        AnimStep(delay=0.4, offset_x=-1.0),                        # twist left
        AnimStep(delay=0.3, offset_x=1.0),                         # twist right
        AnimStep(delay=0.3, offset_x=0.0, offset_y=0.0),
        AnimStep(delay=0.3, face="content", reaction="BOUNCE"),
        AnimStep(delay=0.4, particle="sparkle", blink="slow"),
    ], cooldown=600)

    # --- Napping under a blanket ---
    lib["nap_blanket"] = AnimSequence("nap_blanket", "daily_life", [
        AnimStep(delay=0.0, face="sleepy", blink="slow"),
        AnimStep(delay=0.5, prop=AnimProp.BLANKET, offset_y=1.0),
        AnimStep(delay=0.5, blink="nod_off"),
        AnimStep(delay=1.5, particle="zzz"),
        AnimStep(delay=1.2, particle="zzz"),
        AnimStep(delay=1.2, particle="sleep_bubble"),
        AnimStep(delay=1.0, blink="slow"),
        AnimStep(delay=0.5, face="content", reaction="STRETCH"),
        AnimStep(delay=0.4, offset_y=0.0, hide_prop=True),
        AnimStep(delay=0.3, face="happy", blink="double"),
    ], cooldown=1200)

    # ===================================================================
    # EMOTIONAL — expressive character moments
    # ===================================================================

    # --- Blushing ---
    lib["blush"] = AnimSequence("blush", "emotional", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, reaction="FLINCH"),
        AnimStep(delay=0.4, look_dir=(0.8, 0.5)),                  # look away
        AnimStep(delay=0.5, particle="heart"),
        AnimStep(delay=0.6, blink="slow"),
        AnimStep(delay=0.5, look_dir=(0.0, 0.0), face="content"),
    ], cooldown=600)

    # --- Proud puff — accomplished something ---
    lib["proud_puff"] = AnimSequence("proud_puff", "emotional", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, reaction="STRETCH", offset_y=-1.5),    # puff up
        AnimStep(delay=0.5, particle="sparkle", particle_count=2),
        AnimStep(delay=0.6, face="content", blink="slow"),
        AnimStep(delay=0.4, offset_y=0.0),
    ], cooldown=600)

    # --- Contemplating life ---
    lib["contemplate"] = AnimSequence("contemplate", "emotional", [
        AnimStep(delay=0.0, face="curious"),
        AnimStep(delay=0.5, reaction="HEAD_TILT"),
        AnimStep(delay=0.8, look_dir=(0.5, -0.5), particle="question"),
        AnimStep(delay=1.5, blink="slow"),
        AnimStep(delay=0.6, look_dir=(0.0, 0.0), face="content"),
    ], cooldown=900)

    # --- Excited wiggle ---
    lib["excited_wiggle"] = AnimSequence("excited_wiggle", "emotional", [
        AnimStep(delay=0.0, face="excited"),
        AnimStep(delay=0.2, reaction="WIGGLE"),
        AnimStep(delay=0.3, reaction="BOUNCE", particle="sparkle"),
        AnimStep(delay=0.25, reaction="WIGGLE"),
        AnimStep(delay=0.3, face="happy", particle="sparkle"),
        AnimStep(delay=0.3, blink="double"),
    ], cooldown=600)

    # --- Sulking quietly ---
    lib["sulk"] = AnimSequence("sulk", "emotional", [
        AnimStep(delay=0.0, face="frustrated"),
        AnimStep(delay=0.5, look_dir=(-0.8, 0.3)),
        AnimStep(delay=1.0, blink="slow"),
        AnimStep(delay=0.8, particle="dust"),
        AnimStep(delay=0.7, face="bored"),
        AnimStep(delay=0.5, look_dir=(0.0, 0.0)),
    ], cooldown=900)

    # ===================================================================
    # ACTIVITY — things the fish does when bored/engaged
    # ===================================================================

    # --- Little dance ---
    lib["little_dance"] = AnimSequence("little_dance", "activity", [
        AnimStep(delay=0.0, face="excited", particle="music"),
        AnimStep(delay=0.3, reaction="BOUNCE"),
        AnimStep(delay=0.3, reaction="WIGGLE", particle="music"),
        AnimStep(delay=0.3, reaction="BOUNCE"),
        AnimStep(delay=0.3, offset_x=2.0, reaction="WIGGLE"),
        AnimStep(delay=0.3, offset_x=-2.0, particle="music"),
        AnimStep(delay=0.3, offset_x=0.0, reaction="BOUNCE"),
        AnimStep(delay=0.3, reaction="WIGGLE", particle="sparkle"),
        AnimStep(delay=0.3, face="happy"),
        AnimStep(delay=0.3, blink="slow"),
    ], cooldown=600)

    # --- Head bob to music ---
    lib["head_bob"] = AnimSequence("head_bob", "activity", [
        AnimStep(delay=0.0, face="happy", particle="music"),
        AnimStep(delay=0.3, reaction="NOD"),
        AnimStep(delay=0.35, reaction="NOD", particle="music"),
        AnimStep(delay=0.35, reaction="NOD"),
        AnimStep(delay=0.35, reaction="NOD", particle="music"),
        AnimStep(delay=0.35, reaction="NOD"),
        AnimStep(delay=0.35, reaction="NOD", particle="music"),
        AnimStep(delay=0.4, face="content", blink="slow"),
    ], cooldown=600)

    # --- Deep focus mode ---
    lib["deep_focus"] = AnimSequence("deep_focus", "activity", [
        AnimStep(delay=0.0, face="focused"),
        AnimStep(delay=0.5, look_dir=(-0.3, 0.2)),
        AnimStep(delay=1.0, blink="slow"),
        AnimStep(delay=0.8, look_dir=(0.3, 0.2)),
        AnimStep(delay=0.7, reaction="NOD"),
        AnimStep(delay=0.8, particle="star"),
        AnimStep(delay=0.5, face="content", look_dir=(0.0, 0.0), blink="slow"),
    ], cooldown=600)

    # --- Lifting tiny weights ---
    lib["lift_weights"] = AnimSequence("lift_weights", "activity", [
        AnimStep(delay=0.0, face="focused", prop=AnimProp.TINY_WEIGHTS),
        AnimStep(delay=0.4, offset_y=-2.0, reaction="STRETCH"),    # lift
        AnimStep(delay=0.4, offset_y=0.0),                         # down
        AnimStep(delay=0.3, offset_y=-2.0, reaction="STRETCH"),    # lift
        AnimStep(delay=0.4, offset_y=0.0, particle="sweat"),       # down
        AnimStep(delay=0.3, offset_y=-2.0, reaction="STRETCH"),    # lift
        AnimStep(delay=0.4, offset_y=0.0, face="frustrated", particle="sweat"),
        AnimStep(delay=0.5, face="happy", hide_prop=True, particle="sparkle"),
        AnimStep(delay=0.3, reaction="BOUNCE"),
    ], cooldown=900)

    # --- Stargazing at night ---
    lib["stargaze"] = AnimSequence("stargaze", "activity", [
        AnimStep(delay=0.0, face="curious", prop=AnimProp.TELESCOPE),
        AnimStep(delay=0.5, look_dir=(0.0, -1.0)),
        AnimStep(delay=0.8, particle="stars", particle_count=3),
        AnimStep(delay=0.7, blink="slow"),
        AnimStep(delay=0.8, particle="stars", particle_count=2),
        AnimStep(delay=0.6, face="content", look_dir=(0.3, -0.8)),
        AnimStep(delay=0.7, particle="star"),
        AnimStep(delay=0.5, look_dir=(0.0, 0.0), hide_prop=True),
        AnimStep(delay=0.3, face="happy", blink="slow"),
    ], cooldown=1800)

    # ===================================================================
    # SILLY — playful goofy moments
    # ===================================================================

    # --- Hiccuping ---
    lib["hiccup"] = AnimSequence("hiccup", "silly", [
        AnimStep(delay=0.0, face="content"),
        AnimStep(delay=0.6, reaction="FLINCH", offset_y=-1.0),     # hic!
        AnimStep(delay=0.4, offset_y=0.0, face="curious"),
        AnimStep(delay=0.7, reaction="FLINCH", offset_y=-1.5),     # hic!
        AnimStep(delay=0.4, offset_y=0.0, face="worried"),
        AnimStep(delay=0.6, reaction="FLINCH", offset_y=-2.0,
                 particle="exclamation"),                           # HIC!
        AnimStep(delay=0.4, offset_y=0.0, face="frustrated"),
        AnimStep(delay=0.6, face="content", blink="slow"),
    ], cooldown=900)

    # --- Sneeze that launches backwards ---
    lib["sneeze_fly"] = AnimSequence("sneeze_fly", "silly", [
        AnimStep(delay=0.0, face="worried"),
        AnimStep(delay=0.5, blink="slow"),
        AnimStep(delay=0.3, face="curious", offset_y=-1.0),        # wind up
        AnimStep(delay=0.2, offset_y=-1.5),
        AnimStep(delay=0.15, face="excited", offset_y=0.0, offset_x=-4.0,
                 reaction="FLINCH", particle="dust", particle_count=3),
        AnimStep(delay=0.4, offset_x=-2.0),
        AnimStep(delay=0.4, offset_x=0.0, face="bored", blink="double"),
        AnimStep(delay=0.5, face="content"),
    ], cooldown=900)

    # --- Tripping over nothing ---
    lib["trip"] = AnimSequence("trip", "silly", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.4, reaction="FLINCH"),
        AnimStep(delay=0.2, offset_y=3.0, offset_x=1.5),          # fall
        AnimStep(delay=0.3, face="worried", particle="exclamation"),
        AnimStep(delay=0.4, particle="dust", particle_count=2),
        AnimStep(delay=0.5, offset_y=0.0, offset_x=0.0, reaction="STRETCH"),
        AnimStep(delay=0.4, face="content", blink="double"),
    ], cooldown=900)

    # --- Chasing own tail ---
    lib["chase_tail"] = AnimSequence("chase_tail", "silly", [
        AnimStep(delay=0.0, face="curious", look_dir=(0.8, 0.5)),
        AnimStep(delay=0.3, reaction="WIGGLE"),
        AnimStep(delay=0.3, reaction="DIZZY"),
        AnimStep(delay=0.35, reaction="WIGGLE", particle="question"),
        AnimStep(delay=0.3, reaction="DIZZY"),
        AnimStep(delay=0.35, face="excited", reaction="WIGGLE"),
        AnimStep(delay=0.35, reaction="DIZZY", particle="spiral"),
        AnimStep(delay=0.5, face="bored", blink="slow"),
        AnimStep(delay=0.4, face="content", look_dir=(0.0, 0.0)),
    ], cooldown=900)

    # --- Trying to whistle ---
    lib["try_whistle"] = AnimSequence("try_whistle", "silly", [
        AnimStep(delay=0.0, face="curious"),
        AnimStep(delay=0.5, face="focused"),
        AnimStep(delay=0.6, particle="music"),
        AnimStep(delay=0.4, face="frustrated"),
        AnimStep(delay=0.5, face="focused"),
        AnimStep(delay=0.6, particle="music"),
        AnimStep(delay=0.5, face="happy", blink="slow"),
    ], cooldown=900)

    # ===================================================================
    # WEATHER — reactions to current weather
    # ===================================================================

    # --- Umbrella in rain ---
    lib["rain_umbrella"] = AnimSequence("rain_umbrella", "weather", [
        AnimStep(delay=0.0, face="worried", particle="rain", particle_count=3),
        AnimStep(delay=0.4, reaction="FLINCH"),
        AnimStep(delay=0.3, prop=AnimProp.UMBRELLA),
        AnimStep(delay=0.6, face="content", particle="rain", particle_count=2),
        AnimStep(delay=0.8, blink="slow"),
        AnimStep(delay=0.8, face="happy", reaction="NOD"),
        AnimStep(delay=0.8, hide_prop=True),
    ], cooldown=1800)

    # --- Cool shades in sun ---
    lib["sunny_shades"] = AnimSequence("sunny_shades", "weather", [
        AnimStep(delay=0.0, face="happy", particle="sparkle"),
        AnimStep(delay=0.4, prop=AnimProp.SUNGLASSES),
        AnimStep(delay=0.3, reaction="NOD"),
        AnimStep(delay=0.8, blink="slow", particle="sparkle"),
        AnimStep(delay=0.8, look_dir=(0.5, -0.3)),
        AnimStep(delay=0.6, look_dir=(0.0, 0.0), face="content"),
        AnimStep(delay=0.5, hide_prop=True, blink="slow"),
    ], cooldown=1800)

    # --- Shivering in cold ---
    lib["cold_shiver"] = AnimSequence("cold_shiver", "weather", [
        AnimStep(delay=0.0, face="worried", prop=AnimProp.SCARF),
        AnimStep(delay=0.3, reaction="RAGE_SHAKE"),
        AnimStep(delay=0.5, particle="snow"),
        AnimStep(delay=0.3, reaction="RAGE_SHAKE"),
        AnimStep(delay=0.4, offset_x=0.5),
        AnimStep(delay=0.2, offset_x=-0.5),
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.5, face="content", blink="slow"),
        AnimStep(delay=0.4, hide_prop=True),
    ], cooldown=1800)

    # ===================================================================
    # SEASONAL — rare special event animations
    # ===================================================================

    lib["santa_gift"] = AnimSequence("santa_gift", "seasonal", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, prop=AnimProp.GIFT_BOX),
        AnimStep(delay=0.5, reaction="BOUNCE"),
        AnimStep(delay=0.4, offset_x=2.0),
        AnimStep(delay=0.3, offset_x=0.0, particle="sparkle", particle_count=3),
        AnimStep(delay=0.4, hide_prop=True, particle="confetti", particle_count=5),
        AnimStep(delay=0.5, face="content", blink="slow"),
    ], cooldown=3600)

    lib["new_year_fireworks"] = AnimSequence("new_year_fireworks", "seasonal", [
        AnimStep(delay=0.0, face="excited", prop=AnimProp.PARTY_HORN),
        AnimStep(delay=0.3, particle="firework", particle_count=4),
        AnimStep(delay=0.4, reaction="BOUNCE", particle="confetti", particle_count=6),
        AnimStep(delay=0.5, particle="firework", particle_count=5),
        AnimStep(delay=0.3, reaction="WIGGLE"),
        AnimStep(delay=0.4, particle="firework", particle_count=3),
        AnimStep(delay=0.5, face="happy", hide_prop=True, blink="slow"),
    ], cooldown=3600)

    lib["valentine_hearts"] = AnimSequence("valentine_hearts", "seasonal", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, particle="heart", particle_count=2),
        AnimStep(delay=0.4, reaction="BOUNCE"),
        AnimStep(delay=0.4, particle="heart", particle_count=3),
        AnimStep(delay=0.4, blink="slow"),
        AnimStep(delay=0.5, particle="heart", particle_count=2),
        AnimStep(delay=0.4, face="content", particle="sparkle"),
    ], cooldown=3600)

    lib["halloween_spook"] = AnimSequence("halloween_spook", "seasonal", [
        AnimStep(delay=0.0, face="curious"),
        AnimStep(delay=0.4, face="worried", reaction="FLINCH"),
        AnimStep(delay=0.3, particle="exclamation"),
        AnimStep(delay=0.4, reaction="SHAKE_OFF"),
        AnimStep(delay=0.3, face="excited", particle="sparkle"),
        AnimStep(delay=0.5, reaction="BOUNCE", particle="confetti", particle_count=3),
        AnimStep(delay=0.4, face="happy"),
    ], cooldown=3600)

    # ===================================================================
    # HOBBIES — longer activities the fish settles into
    # ===================================================================

    # --- Painting — messy, frustrated, then suddenly proud ---
    lib["painting"] = AnimSequence("painting", "hobby", [
        # Setup: approach the easel seriously
        AnimStep(delay=0.0, face="focused", prop=AnimProp.EASEL),
        AnimStep(delay=1.2, reaction="HEAD_TILT"),                    # study the blank canvas
        AnimStep(delay=1.5, look_dir=(-0.3, 0.2), blink="slow"),     # lean in, sizing it up
        AnimStep(delay=1.0, look_dir=(0.0, 0.0)),                    # nod to self
        # First strokes — careful, deliberate
        AnimStep(delay=0.8, offset_x=0.5),                           # long stroke right
        AnimStep(delay=0.5, offset_x=-0.4),                          # stroke left
        AnimStep(delay=0.4, offset_x=0.3),                           # dab
        AnimStep(delay=0.3, offset_x=0.0),
        AnimStep(delay=1.0, reaction="HEAD_TILT"),                    # step back to look
        AnimStep(delay=1.2, blink="slow"),                            # ...not great
        # Try again — getting a bit frustrated
        AnimStep(delay=0.8, face="curious", look_dir=(-0.3, 0.2)),
        AnimStep(delay=0.6, offset_x=-0.5),                          # aggressive stroke
        AnimStep(delay=0.3, offset_x=0.5),
        AnimStep(delay=0.3, offset_x=-0.3),
        AnimStep(delay=0.2, offset_x=0.4),
        AnimStep(delay=0.3, offset_x=0.0),
        AnimStep(delay=1.0, reaction="HEAD_TILT"),                    # step back again
        AnimStep(delay=1.5, face="frustrated", look_dir=(0.0, 0.0)), # this isn't working
        AnimStep(delay=0.8, blink="slow"),
        AnimStep(delay=0.6, particle="sweat"),
        # Frustrated phase — messy, fast, almost angry
        AnimStep(delay=0.5, offset_x=0.6),                           # wild strokes
        AnimStep(delay=0.2, offset_x=-0.6),
        AnimStep(delay=0.2, offset_x=0.4),
        AnimStep(delay=0.2, offset_x=-0.5),
        AnimStep(delay=0.3, offset_x=0.0),
        AnimStep(delay=0.8, reaction="FLINCH"),                       # ugh
        AnimStep(delay=1.2, face="worried", blink="slow"),           # stares at the mess
        AnimStep(delay=1.5, look_dir=(-0.3, 0.2)),                   # almost gives up
        # One last try — a single careful stroke
        AnimStep(delay=2.0, face="focused", blink="slow"),           # deep breath
        AnimStep(delay=0.8, offset_x=0.3),                           # one... slow... stroke
        AnimStep(delay=0.6, offset_x=0.0),
        AnimStep(delay=1.5, reaction="HEAD_TILT"),                    # steps way back
        # Sudden delight — it actually looks good
        AnimStep(delay=1.2, face="excited", reaction="BOUNCE"),
        AnimStep(delay=0.6, particle="sparkle", particle_count=3),
        AnimStep(delay=0.8, face="happy", reaction="NOD"),
        AnimStep(delay=1.0, reaction="HEAD_TILT"),                    # admiring it
        AnimStep(delay=1.5, face="content", blink="slow"),           # genuinely pleased
        AnimStep(delay=1.2, look_dir=(-0.3, 0.2)),                   # one last fond look
        AnimStep(delay=1.0, blink="slow"),
        AnimStep(delay=0.8, face="happy", hide_prop=True),
        AnimStep(delay=0.5, blink="double"),
    ], cooldown=1800)

    # --- Gaming — full narrative arc with wins and losses ---
    lib["gaming"] = AnimSequence("gaming", "hobby", [
        # Act 1: Confident start
        AnimStep(delay=0.0, face="excited", prop=AnimProp.HANDHELD_GAME),
        AnimStep(delay=0.5, look_dir=(0.0, 0.4)),                    # lock eyes on screen
        AnimStep(delay=0.6, offset_x=0.3),                           # tap tap
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.4, offset_x=-0.3),                          # tap
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.5, face="focused", offset_x=0.3),          # getting into it
        AnimStep(delay=0.2, offset_x=-0.2),
        AnimStep(delay=0.2, offset_x=0.3),
        AnimStep(delay=0.2, offset_x=0.0, blink="slow"),
        AnimStep(delay=0.8, reaction="NOD"),                         # yeah, nailing it
        # Act 2: Things go wrong
        AnimStep(delay=0.6, face="curious"),                          # huh?
        AnimStep(delay=0.4, reaction="FLINCH"),                       # close call!
        AnimStep(delay=0.3, offset_x=0.4),                           # frantic mashing
        AnimStep(delay=0.15, offset_x=-0.4),
        AnimStep(delay=0.15, offset_x=0.3),
        AnimStep(delay=0.15, offset_x=-0.3),
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.6, face="worried"),                          # losing badly
        AnimStep(delay=0.4, offset_x=0.5),                           # desperate mashing
        AnimStep(delay=0.15, offset_x=-0.5),
        AnimStep(delay=0.15, offset_x=0.4),
        AnimStep(delay=0.15, offset_x=-0.4),
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.5, reaction="FLINCH"),                       # another near-miss
        AnimStep(delay=0.8, face="frustrated", particle="sweat"),    # come ON
        AnimStep(delay=0.6, reaction="RAGE_SHAKE"),                   # UNFAIR!
        AnimStep(delay=0.8, particle="exclamation"),
        # Act 3: Clutch comeback
        AnimStep(delay=0.7, face="focused", blink="slow"),           # refocus...
        AnimStep(delay=0.5, offset_x=0.3),                           # careful inputs
        AnimStep(delay=0.3, offset_x=-0.2),
        AnimStep(delay=0.3, offset_x=0.2),
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.6, reaction="FLINCH"),                       # heart-stopper
        AnimStep(delay=0.4, offset_x=0.4),                           # one last push
        AnimStep(delay=0.2, offset_x=-0.3),
        AnimStep(delay=0.2, offset_x=0.3),
        AnimStep(delay=0.3, offset_x=0.0),
        AnimStep(delay=0.8, face="excited", reaction="BOUNCE"),      # YES!
        AnimStep(delay=0.5, particle="sparkle", particle_count=3),
        AnimStep(delay=0.4, reaction="BOUNCE"),                       # victory bounce
        # Act 4: Victory lap, then tired
        AnimStep(delay=0.6, face="happy", particle="confetti", particle_count=2),
        AnimStep(delay=0.8, reaction="NOD"),                         # satisfied nod
        AnimStep(delay=1.0, blink="slow"),                            # phew
        AnimStep(delay=1.2, face="content", particle="sweat"),       # exhausted but happy
        AnimStep(delay=1.0, blink="slow"),
        AnimStep(delay=0.6, face="happy", hide_prop=True),
        AnimStep(delay=0.5, blink="double"),
    ], cooldown=1800)

    # --- Gardening — slow, meditative, genuinely caring ---
    lib["gardening"] = AnimSequence("gardening", "hobby", [
        # Arrive and settle in
        AnimStep(delay=0.0, face="content", prop=AnimProp.POTTED_PLANT),
        AnimStep(delay=2.0, look_dir=(0.0, 0.5), blink="slow"),     # just looking
        AnimStep(delay=2.5, blink="slow"),                            # no rush at all
        # Lean in to examine
        AnimStep(delay=1.8, offset_y=-0.4),                           # lean close
        AnimStep(delay=2.0, reaction="HEAD_TILT"),                    # studying a leaf
        AnimStep(delay=2.5, blink="slow"),                            # ...just looking
        AnimStep(delay=1.5, offset_y=0.0),                            # lean back
        # Watering — slow, careful pours with pauses
        AnimStep(delay=2.0, particle="rain"),                         # first pour
        AnimStep(delay=2.5, blink="slow"),                            # watching it soak in
        AnimStep(delay=2.0, particle="rain"),                         # second pour
        AnimStep(delay=2.0, blink="slow"),                            # patient
        # Check the soil
        AnimStep(delay=1.8, offset_y=-0.3),                           # lean in again
        AnimStep(delay=1.5, offset_x=0.2),                            # touch the soil
        AnimStep(delay=1.0, offset_x=-0.2),
        AnimStep(delay=1.2, offset_x=0.0, offset_y=0.0),
        AnimStep(delay=2.0, blink="slow"),                            # satisfied with soil
        # Adjust something delicately
        AnimStep(delay=1.5, offset_x=0.15),                           # tiny adjustment
        AnimStep(delay=1.2, offset_x=0.0),
        AnimStep(delay=2.5, reaction="HEAD_TILT"),                    # observe the result
        AnimStep(delay=2.0, blink="slow"),
        # Notice growth
        AnimStep(delay=2.0, particle="leaf"),                         # a new leaf
        AnimStep(delay=2.5, face="happy", blink="slow"),             # quiet smile
        AnimStep(delay=2.0, particle="leaf"),
        # Just sit and watch contentedly
        AnimStep(delay=2.5, face="content", look_dir=(0.0, 0.5)),   # sitting with the plant
        AnimStep(delay=3.0, blink="slow"),                            # longest pause — pure peace
        AnimStep(delay=2.0, blink="slow"),
        AnimStep(delay=1.5, face="content", hide_prop=True),
        AnimStep(delay=1.0, blink="slow"),
    ], cooldown=1800)

    # --- Journaling — introspective, starts slow, builds to catharsis ---
    lib["journaling"] = AnimSequence("journaling", "hobby", [
        # Staring at the blank page
        AnimStep(delay=0.0, face="content", prop=AnimProp.JOURNAL),
        AnimStep(delay=1.5, look_dir=(-0.2, 0.4)),                   # stare at blank page
        AnimStep(delay=2.0, blink="slow"),                            # ...nothing comes
        AnimStep(delay=1.8, face="curious", look_dir=(0.3, -0.3)),  # gaze up-left, thinking
        AnimStep(delay=2.0, blink="slow"),                            # still thinking
        AnimStep(delay=1.5, particle="question"),                     # what to write?
        # First hesitant words
        AnimStep(delay=1.2, face="content", look_dir=(-0.2, 0.4)),  # back to page
        AnimStep(delay=0.8, offset_x=0.2),                           # slow... write
        AnimStep(delay=0.6, offset_x=-0.1),
        AnimStep(delay=0.5, offset_x=0.15),
        AnimStep(delay=0.4, offset_x=0.0),
        AnimStep(delay=1.5, blink="slow"),                            # pause, re-read
        # Thinking break — gazing up
        AnimStep(delay=1.2, face="curious", look_dir=(0.3, -0.3)),  # gaze up again
        AnimStep(delay=2.0, blink="slow"),                            # deep in thought
        AnimStep(delay=1.0, particle="question"),
        # Gets emotional — something surfacing
        AnimStep(delay=1.0, face="worried", look_dir=(-0.2, 0.4)),  # hits a nerve
        AnimStep(delay=0.6, offset_x=0.3),                           # writing with feeling
        AnimStep(delay=0.3, offset_x=-0.2),
        AnimStep(delay=0.3, offset_x=0.25),
        AnimStep(delay=0.3, offset_x=-0.15),
        AnimStep(delay=0.3, offset_x=0.0),
        AnimStep(delay=1.0, particle="heart"),                        # something tender
        AnimStep(delay=1.5, blink="slow"),
        # The dam breaks — fast writing, he figured something out
        AnimStep(delay=0.8, face="focused"),
        AnimStep(delay=0.4, offset_x=0.3),                           # rapid writing
        AnimStep(delay=0.2, offset_x=-0.25),
        AnimStep(delay=0.2, offset_x=0.3),
        AnimStep(delay=0.2, offset_x=-0.2),
        AnimStep(delay=0.2, offset_x=0.25),
        AnimStep(delay=0.15, offset_x=-0.2),
        AnimStep(delay=0.15, offset_x=0.2),
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.6, particle="heart"),
        # Closing the journal — quiet catharsis
        AnimStep(delay=1.2, face="happy", reaction="NOD"),           # done
        AnimStep(delay=1.5, blink="slow"),
        AnimStep(delay=1.8, face="content", look_dir=(0.0, 0.0)),   # closes journal, sits quietly
        AnimStep(delay=2.0, blink="slow"),                            # peaceful
        AnimStep(delay=1.0, face="content", hide_prop=True),
        AnimStep(delay=0.8, blink="slow"),
    ], cooldown=1800)

    # --- Piano — starts hesitant, becomes beautiful, ends emotional ---
    lib["piano"] = AnimSequence("piano", "hobby", [
        # Nervous approach
        AnimStep(delay=0.0, face="worried", prop=AnimProp.TINY_PIANO),
        AnimStep(delay=1.2, look_dir=(0.0, 0.4), blink="slow"),     # staring at the keys
        AnimStep(delay=1.5, blink="slow"),                            # hesitating
        # First hesitant notes
        AnimStep(delay=1.0, offset_x=-0.2),                           # tentative tap
        AnimStep(delay=0.8, offset_x=0.0),                            # pause
        AnimStep(delay=0.7, offset_x=0.2),                            # another note
        AnimStep(delay=0.8, offset_x=0.0),                            # long pause
        AnimStep(delay=0.6, offset_x=-0.3, particle="music"),        # a real note
        AnimStep(delay=0.5, reaction="FLINCH"),                       # wrong note!
        AnimStep(delay=1.0, face="frustrated", blink="slow"),        # sigh
        # Starting over
        AnimStep(delay=1.2, face="focused", look_dir=(0.0, 0.4)),   # deep breath, try again
        AnimStep(delay=0.7, offset_x=-0.2),                           # careful...
        AnimStep(delay=0.5, offset_x=0.2, particle="music"),
        AnimStep(delay=0.5, offset_x=-0.3, particle="music"),
        AnimStep(delay=0.4, offset_x=0.2),                            # finding the melody
        AnimStep(delay=0.5, offset_x=0.0, blink="slow"),
        # Something clicks — the rhythm flows
        AnimStep(delay=0.6, face="content"),
        AnimStep(delay=0.4, offset_x=-0.3, particle="music"),
        AnimStep(delay=0.35, offset_x=0.3, particle="music"),
        AnimStep(delay=0.35, offset_x=-0.2, particle="music"),
        AnimStep(delay=0.35, offset_x=0.2),
        AnimStep(delay=0.35, offset_x=-0.3, particle="music"),
        AnimStep(delay=0.35, offset_x=0.3, particle="music"),
        AnimStep(delay=0.4, offset_x=0.0),
        AnimStep(delay=0.6, reaction="NOD", particle="music"),       # nodding to rhythm
        # Fully in it — confident, beautiful
        AnimStep(delay=0.4, face="happy"),
        AnimStep(delay=0.35, offset_x=-0.3, particle="music"),
        AnimStep(delay=0.3, offset_x=0.3, particle="music"),
        AnimStep(delay=0.3, offset_x=-0.2, particle="music"),
        AnimStep(delay=0.3, offset_x=0.2, particle="music"),
        AnimStep(delay=0.3, offset_x=-0.3, particle="music"),
        AnimStep(delay=0.3, offset_x=0.3, particle="music"),
        AnimStep(delay=0.35, offset_x=0.0),
        AnimStep(delay=0.5, reaction="NOD", particle="music"),       # deep in the music
        AnimStep(delay=0.4, particle="sparkle"),
        # The last note fades
        AnimStep(delay=0.6, offset_x=-0.2, particle="music"),        # final slow chord
        AnimStep(delay=0.8, offset_x=0.0),                            # hands rest
        AnimStep(delay=1.5, blink="slow"),                            # silence
        AnimStep(delay=2.0, face="content", blink="slow"),           # sitting quietly after
        AnimStep(delay=1.5, particle="heart"),                        # single heart
        AnimStep(delay=2.0, blink="slow"),                            # lingering
        AnimStep(delay=1.0, look_dir=(0.0, 0.0), hide_prop=True),
        AnimStep(delay=0.8, blink="slow"),
    ], cooldown=1800)

    return lib


# -----------------------------------------------------------------------
# Singleton library instance
# -----------------------------------------------------------------------
ANIMATION_LIBRARY: dict[str, AnimSequence] = _build_library()


def get_animations_by_category(category: str) -> list[AnimSequence]:
    """Get all animations in a category."""
    return [a for a in ANIMATION_LIBRARY.values() if a.category == category]


def get_available_animations(category: str | None = None,
                             now: float = 0.0) -> list[AnimSequence]:
    """Get animations that are off cooldown, optionally filtered by category."""
    results = []
    for a in ANIMATION_LIBRARY.values():
        if category and a.category != category:
            continue
        if now - a.last_played < a.cooldown:
            continue
        results.append(a)
    return results


def pick_animation(category: str | None = None,
                   now: float = 0.0) -> AnimSequence | None:
    """Pick a random available animation, optionally from a specific category."""
    available = get_available_animations(category, now)
    if not available:
        return None
    return random.choice(available)
