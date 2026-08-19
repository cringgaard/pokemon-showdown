import os


def choose_action(state):
    os.write(1, b"x" * (64 * 1024))
    return state["request"]["legal_actions"][0]
