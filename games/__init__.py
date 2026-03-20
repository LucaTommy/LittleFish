# Desktop games — cursor-based, fish physically moves
from games.catch_snack import CatchSnackGame      # noqa: F401
from games.whack_a_bubble import WhackABubbleGame  # noqa: F401
from games.flappy import FlappyGame                # noqa: F401

GAME_LIST = [
    ("Catch & Snack", "Catch falling food!", CatchSnackGame),
    ("Whack-a-Bubble", "Pop the bubbles!", WhackABubbleGame),
    ("Flappy Swim", "Flap through pipes!", FlappyGame),
]
