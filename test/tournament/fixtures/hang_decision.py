import time


def choose_action(state):
    if state["runtime"]["decision_id"] == 7:
        time.sleep(60)
    return state["request"]["legal_actions"][0]
