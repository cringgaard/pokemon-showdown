print("module initialization noise")


def choose_action(state):
    print("decision noise")
    return state["request"]["legal_actions"][0]
