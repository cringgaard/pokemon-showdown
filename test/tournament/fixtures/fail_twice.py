attempts = 0


def choose_action(state):
    global attempts
    attempts += 1
    if attempts <= 2:
        return {"invalid": True}
    return state["request"]["legal_actions"][0]
