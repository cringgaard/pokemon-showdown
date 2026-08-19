import os


def choose_action(state):
    os.write(2, b"diagnostic-spam-" * 8192)
    return state["request"]["legal_actions"][0]
