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
    TOOTHBRUSH = auto()
    TINY_WEIGHTS = auto()
    SNACK = auto()
    SCARF = auto()
    PARTY_HORN = auto()
    GIFT_BOX = auto()
    TELESCOPE = auto()
    MIRROR = auto()


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
    # DAILY LIFE
    # ===================================================================

    # --- Drinking coffee ---
    lib["coffee_sip"] = AnimSequence("coffee_sip", "daily_life", [
        AnimStep(delay=0.0, face="content", prop=AnimProp.COFFEE_CUP),
        AnimStep(delay=0.4, blink="slow"),
        AnimStep(delay=0.8, offset_y=-1.0, particle="emote_coffee"),
        AnimStep(delay=0.6, face="happy", reaction="NOD"),
        AnimStep(delay=0.5, blink="slow"),
        AnimStep(delay=0.8, particle="emote_coffee"),
        AnimStep(delay=0.5, offset_y=0.0),
        AnimStep(delay=0.4, face="content", hide_prop=True),
        AnimStep(delay=0.3, blink="slow"),
    ], cooldown=600)

    # --- Yawning and stretching ---
    lib["yawn_stretch"] = AnimSequence("yawn_stretch", "daily_life", [
        AnimStep(delay=0.0, face="sleepy"),
        AnimStep(delay=0.3, reaction="STRETCH", blink="slow"),
        AnimStep(delay=0.8, face="sleepy", particle="zzz"),
        AnimStep(delay=0.5, reaction="STRETCH"),
        AnimStep(delay=0.6, offset_y=-2.0),
        AnimStep(delay=0.4, offset_y=0.0, face="content"),
        AnimStep(delay=0.3, blink="double", reaction="WIGGLE"),
        AnimStep(delay=0.5, face="happy"),
    ], cooldown=300)

    # --- Eating a snack ---
    lib["eat_snack"] = AnimSequence("eat_snack", "daily_life", [
        AnimStep(delay=0.0, face="curious", prop=AnimProp.SNACK),
        AnimStep(delay=0.5, face="happy", reaction="NOD"),
        AnimStep(delay=0.3, offset_y=1.0),  # nom
        AnimStep(delay=0.2, offset_y=0.0),
        AnimStep(delay=0.3, offset_y=1.0),  # nom
        AnimStep(delay=0.2, offset_y=0.0, particle="sparkle"),
        AnimStep(delay=0.3, offset_y=1.0),  # nom
        AnimStep(delay=0.2, offset_y=0.0),
        AnimStep(delay=0.4, face="content", hide_prop=True, particle="sparkle"),
        AnimStep(delay=0.5, blink="slow"),
    ], cooldown=900)

    # --- Reading a tiny book ---
    lib["read_book"] = AnimSequence("read_book", "daily_life", [
        AnimStep(delay=0.0, face="focused", prop=AnimProp.TINY_BOOK),
        AnimStep(delay=0.8, look_dir=(-0.5, 0.3)),
        AnimStep(delay=1.2, look_dir=(0.5, 0.3), blink="slow"),
        AnimStep(delay=1.0, look_dir=(-0.3, 0.3)),
        AnimStep(delay=0.8, face="curious", reaction="HEAD_TILT"),
        AnimStep(delay=1.0, look_dir=(0.3, 0.3), blink="slow"),
        AnimStep(delay=0.6, face="content"),
        AnimStep(delay=0.5, hide_prop=True, blink="slow"),
    ], cooldown=600)

    # --- Napping with blanket ---
    lib["nap_blanket"] = AnimSequence("nap_blanket", "daily_life", [
        AnimStep(delay=0.0, face="sleepy", blink="slow"),
        AnimStep(delay=0.5, prop=AnimProp.BLANKET, offset_y=1.0),
        AnimStep(delay=0.4, blink="nod_off"),
        AnimStep(delay=1.5, particle="zzz"),
        AnimStep(delay=1.0, particle="zzz"),
        AnimStep(delay=1.0, particle="sleep_bubble"),
        AnimStep(delay=1.5, particle="zzz"),
        AnimStep(delay=0.8, blink="slow"),
        AnimStep(delay=0.5, face="content", reaction="STRETCH"),
        AnimStep(delay=0.5, offset_y=0.0, hide_prop=True),
        AnimStep(delay=0.3, face="happy", blink="double"),
    ], cooldown=1200)

    # --- Brushing teeth at night ---
    lib["brush_teeth"] = AnimSequence("brush_teeth", "daily_life", [
        AnimStep(delay=0.0, face="focused", prop=AnimProp.TOOTHBRUSH),
        AnimStep(delay=0.3, offset_x=1.0),
        AnimStep(delay=0.2, offset_x=-1.0),
        AnimStep(delay=0.2, offset_x=1.0),
        AnimStep(delay=0.2, offset_x=-1.0),
        AnimStep(delay=0.2, offset_x=1.0),
        AnimStep(delay=0.2, offset_x=-1.0),
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.4, face="happy", particle="sparkle"),
        AnimStep(delay=0.3, hide_prop=True, blink="slow"),
        AnimStep(delay=0.4, face="content"),
    ], cooldown=3600)

    # --- Making breakfast (morning routine) ---
    lib["morning_routine"] = AnimSequence("morning_routine", "daily_life", [
        AnimStep(delay=0.0, face="sleepy", blink="slow"),
        AnimStep(delay=0.5, reaction="STRETCH"),
        AnimStep(delay=0.6, face="content", blink="double"),
        AnimStep(delay=0.5, prop=AnimProp.COFFEE_CUP),
        AnimStep(delay=0.8, face="happy", particle="emote_coffee"),
        AnimStep(delay=0.5, blink="slow", reaction="NOD"),
        AnimStep(delay=0.5, hide_prop=True),
    ], cooldown=3600)

    # ===================================================================
    # WEATHER REACTIONS
    # ===================================================================

    # --- Umbrella in rain ---
    lib["rain_umbrella"] = AnimSequence("rain_umbrella", "weather", [
        AnimStep(delay=0.0, face="worried", particle="rain", particle_count=3),
        AnimStep(delay=0.4, reaction="FLINCH"),
        AnimStep(delay=0.3, prop=AnimProp.UMBRELLA),
        AnimStep(delay=0.5, face="content", particle="rain", particle_count=2),
        AnimStep(delay=0.8, blink="slow"),
        AnimStep(delay=1.0, particle="rain", particle_count=3),
        AnimStep(delay=0.8, face="happy", reaction="NOD"),
        AnimStep(delay=1.0, hide_prop=True),
    ], cooldown=1800)

    # --- Sunglasses in sun ---
    lib["sunny_shades"] = AnimSequence("sunny_shades", "weather", [
        AnimStep(delay=0.0, face="happy", particle="sparkle"),
        AnimStep(delay=0.4, prop=AnimProp.SUNGLASSES),
        AnimStep(delay=0.3, reaction="NOD"),
        AnimStep(delay=0.8, blink="slow", particle="sparkle"),
        AnimStep(delay=1.0, face="content"),
        AnimStep(delay=0.8, look_dir=(0.5, -0.3)),
        AnimStep(delay=0.6, look_dir=(0.0, 0.0)),
        AnimStep(delay=0.5, hide_prop=True),
    ], cooldown=1800)

    # --- Shivering in cold ---
    lib["cold_shiver"] = AnimSequence("cold_shiver", "weather", [
        AnimStep(delay=0.0, face="worried", prop=AnimProp.SCARF),
        AnimStep(delay=0.3, reaction="RAGE_SHAKE"),  # shivering effect
        AnimStep(delay=0.4, particle="snow"),
        AnimStep(delay=0.3, reaction="RAGE_SHAKE"),
        AnimStep(delay=0.4, offset_x=0.5),
        AnimStep(delay=0.2, offset_x=-0.5),
        AnimStep(delay=0.2, offset_x=0.0),
        AnimStep(delay=0.5, face="content", blink="slow"),
        AnimStep(delay=0.5, hide_prop=True),
    ], cooldown=1800)

    # --- Melting in heat ---
    lib["heat_melt"] = AnimSequence("heat_melt", "weather", [
        AnimStep(delay=0.0, face="worried"),
        AnimStep(delay=0.4, offset_y=1.0, particle="sweat"),
        AnimStep(delay=0.4, offset_y=2.0, particle="sweat"),
        AnimStep(delay=0.5, face="sleepy", blink="slow"),
        AnimStep(delay=0.6, offset_y=3.0, particle="sweat"),
        AnimStep(delay=0.5, face="frustrated"),
        AnimStep(delay=0.8, offset_y=1.0, reaction="STRETCH"),
        AnimStep(delay=0.5, offset_y=0.0, face="content"),
    ], cooldown=1800)

    # ===================================================================
    # EMOTIONAL MOMENTS
    # ===================================================================

    # --- Dramatic single tear ---
    lib["dramatic_tear"] = AnimSequence("dramatic_tear", "emotional", [
        AnimStep(delay=0.0, face="worried"),
        AnimStep(delay=0.5, blink="slow"),
        AnimStep(delay=0.6, particle="sweat"),  # the "tear"
        AnimStep(delay=0.3, reaction="HEAD_TILT"),
        AnimStep(delay=0.8, face="content", blink="slow"),
        AnimStep(delay=0.5, face="happy"),
    ], cooldown=600)

    # --- Laughing so hard he falls over ---
    lib["laugh_fall"] = AnimSequence("laugh_fall", "emotional", [
        AnimStep(delay=0.0, face="excited"),
        AnimStep(delay=0.3, reaction="WIGGLE"),
        AnimStep(delay=0.4, reaction="BOUNCE"),
        AnimStep(delay=0.3, reaction="WIGGLE", particle="sparkle"),
        AnimStep(delay=0.3, reaction="DIZZY"),
        AnimStep(delay=0.5, offset_y=3.0, offset_x=2.0),
        AnimStep(delay=0.4, face="happy", particle="sparkle"),
        AnimStep(delay=0.6, offset_y=0.0, offset_x=0.0, reaction="STRETCH"),
        AnimStep(delay=0.4, blink="double"),
    ], cooldown=600)

    # --- Blushing ---
    lib["blush"] = AnimSequence("blush", "emotional", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, reaction="FLINCH"),
        AnimStep(delay=0.3, look_dir=(0.8, 0.5)),  # look away
        AnimStep(delay=0.5, particle="heart"),
        AnimStep(delay=0.5, blink="slow"),
        AnimStep(delay=0.6, look_dir=(0.0, 0.0), face="content"),
    ], cooldown=300)

    # --- Hiding face (embarrassed) ---
    lib["hide_face"] = AnimSequence("hide_face", "emotional", [
        AnimStep(delay=0.0, face="worried"),
        AnimStep(delay=0.3, reaction="FLINCH"),
        AnimStep(delay=0.3, offset_y=2.0),  # duck down
        AnimStep(delay=0.5, blink="nod_off"),  # eyes shut
        AnimStep(delay=1.5, blink="slow"),
        AnimStep(delay=0.5, offset_y=0.0, face="content"),
        AnimStep(delay=0.3, look_dir=(0.0, 0.0)),
    ], cooldown=600)

    # --- Proud puff ---
    lib["proud_puff"] = AnimSequence("proud_puff", "emotional", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, reaction="STRETCH", offset_y=-1.0),
        AnimStep(delay=0.5, particle="sparkle", particle_count=2),
        AnimStep(delay=0.5, face="content", blink="slow"),
        AnimStep(delay=0.5, offset_y=0.0),
    ], cooldown=300)

    # --- Existential stare ---
    lib["existential_stare"] = AnimSequence("existential_stare", "emotional", [
        AnimStep(delay=0.0, face="bored"),
        AnimStep(delay=0.5, look_dir=(0.0, -0.8)),  # stare into distance
        AnimStep(delay=2.0, blink="slow"),
        AnimStep(delay=1.0, face="content"),
        AnimStep(delay=0.5, look_dir=(0.0, 0.0), blink="double"),
    ], cooldown=900)

    # ===================================================================
    # ACTIVITY REACTIONS
    # ===================================================================

    # --- Lifting tiny weights ---
    lib["lift_weights"] = AnimSequence("lift_weights", "activity", [
        AnimStep(delay=0.0, face="focused", prop=AnimProp.TINY_WEIGHTS),
        AnimStep(delay=0.4, offset_y=-2.0, reaction="STRETCH"),
        AnimStep(delay=0.4, offset_y=0.0),
        AnimStep(delay=0.3, offset_y=-2.0, reaction="STRETCH"),
        AnimStep(delay=0.4, offset_y=0.0, particle="sweat"),
        AnimStep(delay=0.3, offset_y=-2.0, reaction="STRETCH"),
        AnimStep(delay=0.4, offset_y=0.0, face="frustrated", particle="sweat"),
        AnimStep(delay=0.5, face="happy", hide_prop=True, particle="sparkle"),
        AnimStep(delay=0.3, reaction="BOUNCE"),
    ], cooldown=900)

    # --- Typing frantically ---
    lib["type_frantic"] = AnimSequence("type_frantic", "activity", [
        AnimStep(delay=0.0, face="focused"),
        AnimStep(delay=0.15, offset_x=0.5),
        AnimStep(delay=0.12, offset_x=-0.5),
        AnimStep(delay=0.12, offset_x=0.5),
        AnimStep(delay=0.12, offset_x=-0.5),
        AnimStep(delay=0.12, offset_x=0.5),
        AnimStep(delay=0.12, offset_x=-0.5, particle="spark"),
        AnimStep(delay=0.12, offset_x=0.5),
        AnimStep(delay=0.12, offset_x=-0.5),
        AnimStep(delay=0.12, offset_x=0.5),
        AnimStep(delay=0.12, offset_x=-0.5),
        AnimStep(delay=0.15, offset_x=0.0, face="happy", particle="sparkle"),
        AnimStep(delay=0.4, reaction="NOD"),
    ], cooldown=600)

    # --- Little dance ---
    lib["little_dance"] = AnimSequence("little_dance", "activity", [
        AnimStep(delay=0.0, face="excited", particle="music"),
        AnimStep(delay=0.25, reaction="BOUNCE"),
        AnimStep(delay=0.3, reaction="WIGGLE", particle="music"),
        AnimStep(delay=0.3, reaction="BOUNCE"),
        AnimStep(delay=0.3, offset_x=2.0, reaction="WIGGLE"),
        AnimStep(delay=0.3, offset_x=-2.0, particle="music"),
        AnimStep(delay=0.3, offset_x=0.0, reaction="BOUNCE"),
        AnimStep(delay=0.3, reaction="WIGGLE", particle="sparkle"),
        AnimStep(delay=0.3, face="happy", reaction="BOUNCE"),
    ], cooldown=600)

    # --- Stargazing at night ---
    lib["stargaze"] = AnimSequence("stargaze", "activity", [
        AnimStep(delay=0.0, face="curious", prop=AnimProp.TELESCOPE),
        AnimStep(delay=0.5, look_dir=(0.0, -1.0)),
        AnimStep(delay=0.8, particle="stars", particle_count=3),
        AnimStep(delay=0.6, blink="slow"),
        AnimStep(delay=0.8, particle="stars", particle_count=2),
        AnimStep(delay=0.6, face="content", look_dir=(0.3, -0.8)),
        AnimStep(delay=0.8, particle="star"),
        AnimStep(delay=0.5, look_dir=(0.0, 0.0), hide_prop=True),
        AnimStep(delay=0.3, face="happy", blink="slow"),
    ], cooldown=1800)

    # --- Deep focus coding ---
    lib["deep_focus"] = AnimSequence("deep_focus", "activity", [
        AnimStep(delay=0.0, face="focused"),
        AnimStep(delay=0.4, look_dir=(-0.3, 0.2)),
        AnimStep(delay=0.8, blink="slow"),
        AnimStep(delay=1.0, look_dir=(0.3, 0.2)),
        AnimStep(delay=0.6, reaction="NOD"),
        AnimStep(delay=0.8, particle="star"),
        AnimStep(delay=0.5, face="content", blink="slow"),
    ], cooldown=600)

    # --- Doing pushups ---
    lib["pushups"] = AnimSequence("pushups", "activity", [
        AnimStep(delay=0.0, face="focused"),
        AnimStep(delay=0.3, offset_y=2.0),
        AnimStep(delay=0.3, offset_y=0.0),
        AnimStep(delay=0.3, offset_y=2.0),
        AnimStep(delay=0.3, offset_y=0.0, particle="sweat"),
        AnimStep(delay=0.3, offset_y=2.0),
        AnimStep(delay=0.3, offset_y=0.0),
        AnimStep(delay=0.3, offset_y=2.0, particle="sweat"),
        AnimStep(delay=0.4, offset_y=0.0, face="happy"),
        AnimStep(delay=0.3, reaction="BOUNCE", particle="sparkle"),
    ], cooldown=900)

    # ===================================================================
    # SILLY ONES
    # ===================================================================

    # --- Chasing own tail ---
    lib["chase_tail"] = AnimSequence("chase_tail", "silly", [
        AnimStep(delay=0.0, face="curious", look_dir=(0.8, 0.5)),
        AnimStep(delay=0.3, reaction="WIGGLE"),
        AnimStep(delay=0.3, reaction="DIZZY"),
        AnimStep(delay=0.4, reaction="WIGGLE", particle="question"),
        AnimStep(delay=0.3, reaction="DIZZY"),
        AnimStep(delay=0.4, face="excited", reaction="WIGGLE"),
        AnimStep(delay=0.4, reaction="DIZZY", particle="spiral"),
        AnimStep(delay=0.5, face="sleepy", blink="slow"),
        AnimStep(delay=0.4, face="content", look_dir=(0.0, 0.0)),
    ], cooldown=900)

    # --- Hiccuping ---
    lib["hiccup"] = AnimSequence("hiccup", "silly", [
        AnimStep(delay=0.0, face="curious"),
        AnimStep(delay=0.5, reaction="FLINCH", offset_y=-1.0),
        AnimStep(delay=0.4, offset_y=0.0, face="worried"),
        AnimStep(delay=0.6, reaction="FLINCH", offset_y=-1.5),
        AnimStep(delay=0.4, offset_y=0.0),
        AnimStep(delay=0.5, reaction="FLINCH", offset_y=-2.0, particle="exclamation"),
        AnimStep(delay=0.4, offset_y=0.0, face="frustrated"),
        AnimStep(delay=0.8, face="content", blink="slow"),
    ], cooldown=600)

    # --- Sneeze fly backwards ---
    lib["sneeze_fly"] = AnimSequence("sneeze_fly", "silly", [
        AnimStep(delay=0.0, face="worried"),
        AnimStep(delay=0.4, blink="slow"),
        AnimStep(delay=0.3, face="curious", offset_y=-1.0),
        AnimStep(delay=0.2, offset_y=-1.5),  # wind up
        AnimStep(delay=0.15, face="excited", offset_y=0.0, offset_x=-4.0,
                 reaction="FLINCH", particle="dust", particle_count=3),
        AnimStep(delay=0.4, offset_x=-2.0),
        AnimStep(delay=0.3, offset_x=0.0, face="sleepy", blink="double"),
        AnimStep(delay=0.5, face="content"),
    ], cooldown=600)

    # --- Spooked by own reflection ---
    lib["spooked_reflection"] = AnimSequence("spooked_reflection", "silly", [
        AnimStep(delay=0.0, face="happy", prop=AnimProp.MIRROR),
        AnimStep(delay=0.5, face="curious", look_dir=(0.0, 0.0)),
        AnimStep(delay=0.4, face="worried", reaction="FLINCH",
                 particle="exclamation"),
        AnimStep(delay=0.3, hide_prop=True, reaction="SHAKE_OFF"),
        AnimStep(delay=0.4, offset_x=-2.0),
        AnimStep(delay=0.3, offset_x=0.0, face="content"),
        AnimStep(delay=0.5, blink="double"),
    ], cooldown=1200)

    # --- Tripping over nothing ---
    lib["trip"] = AnimSequence("trip", "silly", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, reaction="FLINCH"),
        AnimStep(delay=0.2, offset_y=3.0, offset_x=1.0),
        AnimStep(delay=0.3, face="worried", particle="exclamation"),
        AnimStep(delay=0.4, particle="dust", particle_count=2),
        AnimStep(delay=0.5, offset_y=0.0, offset_x=0.0, reaction="STRETCH"),
        AnimStep(delay=0.3, face="content", blink="double"),
    ], cooldown=900)

    # --- Pretending to be a statue ---
    lib["statue"] = AnimSequence("statue", "silly", [
        AnimStep(delay=0.0, face="focused"),
        AnimStep(delay=0.3, blink="nod_off"),  # eyes frozen open pretend
        AnimStep(delay=2.0),  # hold perfectly still
        AnimStep(delay=0.5, blink="slow"),
        AnimStep(delay=0.3, face="happy", blink="double"),
        AnimStep(delay=0.3, reaction="BOUNCE"),
    ], cooldown=1200)

    # --- Burp ---
    lib["burp"] = AnimSequence("burp", "silly", [
        AnimStep(delay=0.0, face="content"),
        AnimStep(delay=0.4, reaction="FLINCH", face="curious"),
        AnimStep(delay=0.2, particle="dust"),
        AnimStep(delay=0.3, face="worried", look_dir=(0.5, 0.0)),  # look around
        AnimStep(delay=0.5, face="content", look_dir=(0.0, 0.0), blink="slow"),
    ], cooldown=900)

    # ===================================================================
    # SEASONAL
    # ===================================================================

    # --- Santa hat + delivering gift ---
    lib["santa_gift"] = AnimSequence("santa_gift", "seasonal", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, prop=AnimProp.GIFT_BOX),
        AnimStep(delay=0.5, reaction="BOUNCE"),
        AnimStep(delay=0.4, offset_x=2.0),
        AnimStep(delay=0.3, offset_x=0.0, particle="sparkle", particle_count=3),
        AnimStep(delay=0.4, hide_prop=True, particle="confetti", particle_count=5),
        AnimStep(delay=0.5, face="content", blink="slow"),
    ], cooldown=3600)

    # --- New Year fireworks ---
    lib["new_year_fireworks"] = AnimSequence("new_year_fireworks", "seasonal", [
        AnimStep(delay=0.0, face="excited", prop=AnimProp.PARTY_HORN),
        AnimStep(delay=0.3, particle="firework", particle_count=4),
        AnimStep(delay=0.4, reaction="BOUNCE", particle="confetti", particle_count=6),
        AnimStep(delay=0.5, particle="firework", particle_count=5),
        AnimStep(delay=0.3, reaction="WIGGLE"),
        AnimStep(delay=0.4, particle="firework", particle_count=3),
        AnimStep(delay=0.5, particle="confetti", particle_count=4),
        AnimStep(delay=0.5, face="happy", hide_prop=True, blink="slow"),
    ], cooldown=3600)

    # --- Valentine's hearts ---
    lib["valentine_hearts"] = AnimSequence("valentine_hearts", "seasonal", [
        AnimStep(delay=0.0, face="happy"),
        AnimStep(delay=0.3, particle="heart", particle_count=2),
        AnimStep(delay=0.4, reaction="BOUNCE"),
        AnimStep(delay=0.4, particle="heart", particle_count=3),
        AnimStep(delay=0.3, blink="slow"),
        AnimStep(delay=0.5, particle="heart", particle_count=2),
        AnimStep(delay=0.4, face="content", particle="sparkle"),
    ], cooldown=3600)

    # --- Halloween spooky ---
    lib["halloween_spook"] = AnimSequence("halloween_spook", "seasonal", [
        AnimStep(delay=0.0, face="curious"),
        AnimStep(delay=0.4, face="worried", reaction="FLINCH"),
        AnimStep(delay=0.3, particle="exclamation"),
        AnimStep(delay=0.4, reaction="SHAKE_OFF"),
        AnimStep(delay=0.3, face="excited", particle="sparkle"),
        AnimStep(delay=0.5, reaction="BOUNCE", particle="confetti", particle_count=3),
        AnimStep(delay=0.4, face="happy"),
    ], cooldown=3600)

    # --- Spring stretch ---
    lib["spring_stretch"] = AnimSequence("spring_stretch", "seasonal", [
        AnimStep(delay=0.0, face="content"),
        AnimStep(delay=0.4, reaction="STRETCH"),
        AnimStep(delay=0.5, particle="leaf", particle_count=2),
        AnimStep(delay=0.4, face="happy", particle="sparkle"),
        AnimStep(delay=0.5, blink="slow"),
    ], cooldown=3600)

    # --- Summer vibes ---
    lib["summer_vibes"] = AnimSequence("summer_vibes", "seasonal", [
        AnimStep(delay=0.0, face="happy", prop=AnimProp.SUNGLASSES),
        AnimStep(delay=0.5, blink="slow"),
        AnimStep(delay=0.8, particle="sparkle"),
        AnimStep(delay=0.6, face="content", reaction="NOD"),
        AnimStep(delay=0.8, hide_prop=True),
    ], cooldown=3600)

    # ===================================================================
    # BONUS: Additional character moments
    # ===================================================================

    # --- Victory pose (after completing something) ---
    lib["victory_pose"] = AnimSequence("victory_pose", "emotional", [
        AnimStep(delay=0.0, face="excited"),
        AnimStep(delay=0.3, reaction="BOUNCE", particle="confetti", particle_count=4),
        AnimStep(delay=0.3, reaction="WIGGLE"),
        AnimStep(delay=0.3, particle="sparkle", particle_count=3),
        AnimStep(delay=0.4, face="happy", reaction="BOUNCE"),
        AnimStep(delay=0.3, particle="star", particle_count=2),
        AnimStep(delay=0.5, face="content", blink="slow"),
    ], cooldown=300)

    # --- Sulking ---
    lib["sulk"] = AnimSequence("sulk", "emotional", [
        AnimStep(delay=0.0, face="frustrated"),
        AnimStep(delay=0.5, look_dir=(-0.8, 0.3)),
        AnimStep(delay=1.0, blink="slow"),
        AnimStep(delay=0.8, particle="dust"),
        AnimStep(delay=0.7, face="bored"),
        AnimStep(delay=0.5, look_dir=(0.0, 0.0)),
    ], cooldown=600)

    # --- Excited wiggle (general excitement) ---
    lib["excited_wiggle"] = AnimSequence("excited_wiggle", "emotional", [
        AnimStep(delay=0.0, face="excited"),
        AnimStep(delay=0.2, reaction="WIGGLE"),
        AnimStep(delay=0.3, reaction="BOUNCE", particle="sparkle"),
        AnimStep(delay=0.2, reaction="WIGGLE"),
        AnimStep(delay=0.3, face="happy"),
    ], cooldown=300)

    # --- Contemplating ---
    lib["contemplate"] = AnimSequence("contemplate", "emotional", [
        AnimStep(delay=0.0, face="curious"),
        AnimStep(delay=0.5, reaction="HEAD_TILT"),
        AnimStep(delay=0.8, look_dir=(0.5, -0.5), particle="question"),
        AnimStep(delay=1.2, blink="slow"),
        AnimStep(delay=0.6, look_dir=(0.0, 0.0), face="content"),
    ], cooldown=600)

    # --- Jump scare recovery ---
    lib["jump_scare"] = AnimSequence("jump_scare", "silly", [
        AnimStep(delay=0.0, face="worried", reaction="FLINCH"),
        AnimStep(delay=0.2, particle="exclamation"),
        AnimStep(delay=0.2, offset_y=-3.0),  # jump
        AnimStep(delay=0.3, offset_y=0.0, particle="sweat"),
        AnimStep(delay=0.4, face="frustrated"),
        AnimStep(delay=0.5, face="content", blink="double"),
    ], cooldown=600)

    # --- Trying to whistle ---
    lib["try_whistle"] = AnimSequence("try_whistle", "silly", [
        AnimStep(delay=0.0, face="curious"),
        AnimStep(delay=0.4, face="focused"),
        AnimStep(delay=0.5, particle="music"),
        AnimStep(delay=0.3, face="frustrated"),
        AnimStep(delay=0.4, face="focused"),
        AnimStep(delay=0.5, particle="music"),
        AnimStep(delay=0.4, face="happy", blink="slow"),
    ], cooldown=900)

    # --- Stretching after sitting too long ---
    lib["big_stretch"] = AnimSequence("big_stretch", "daily_life", [
        AnimStep(delay=0.0, face="sleepy"),
        AnimStep(delay=0.3, reaction="STRETCH"),
        AnimStep(delay=0.5, offset_y=-2.0),
        AnimStep(delay=0.4, offset_x=-1.0),
        AnimStep(delay=0.3, offset_x=1.0),
        AnimStep(delay=0.3, offset_x=0.0, offset_y=0.0),
        AnimStep(delay=0.3, face="happy", reaction="BOUNCE"),
        AnimStep(delay=0.3, particle="sparkle"),
    ], cooldown=600)

    # --- Head bob to music ---
    lib["head_bob"] = AnimSequence("head_bob", "activity", [
        AnimStep(delay=0.0, face="happy", particle="music"),
        AnimStep(delay=0.25, reaction="NOD"),
        AnimStep(delay=0.3, reaction="NOD", particle="music"),
        AnimStep(delay=0.3, reaction="NOD"),
        AnimStep(delay=0.3, reaction="NOD", particle="music"),
        AnimStep(delay=0.3, reaction="NOD"),
        AnimStep(delay=0.3, reaction="NOD", particle="music"),
        AnimStep(delay=0.3, face="content", blink="slow"),
    ], cooldown=600)

    # --- Being dramatic about mondays ---
    lib["monday_drama"] = AnimSequence("monday_drama", "daily_life", [
        AnimStep(delay=0.0, face="frustrated"),
        AnimStep(delay=0.4, reaction="HEAD_TILT"),
        AnimStep(delay=0.5, face="sleepy", blink="slow"),
        AnimStep(delay=0.6, face="bored", particle="dust"),
        AnimStep(delay=0.5, reaction="STRETCH"),
        AnimStep(delay=0.4, face="content"),
    ], cooldown=3600)

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
