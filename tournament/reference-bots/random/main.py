import os
import random


_random = random.Random(os.environ.get("BOT_SEED", "tournament-random-bot"))


def choose_action(state):
    """Choose exclusively from the public complete-action list."""
    return _random.choice(state["request"]["legal_actions"])
