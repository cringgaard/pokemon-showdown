def _move_score(state, position, action):
    if action["type"] != "move":
        return 1.0
    slot = state["request"]["slots"][position]
    move = next((move for move in slot["moves"] if move["id"] == action["move"]), None)
    if not move:
        return 0.0
    own_id = state["self"]["active"].get(position)
    own = next((pokemon for pokemon in state["self"]["team"] if pokemon["id"] == own_id), None)
    attacking_stat = 1
    if own:
        attacking_stat = own["stats"]["atk" if move["category"] == "Physical" else "spa"]
    score = move["base_power"] * attacking_stat
    if action.get("target", "").startswith("opponent_"):
        score *= 1.05
    if action.get("terastallize"):
        score *= 1.02
    return score


def choose_action(state):
    """Score only normalized public state and return one supplied legal action."""
    legal = state["request"]["legal_actions"]
    if state["request"]["kind"] == "team_preview":
        return legal[0]

    def score(response):
        return sum(
            _move_score(state, position, action)
            for position, action in response["actions"].items()
        )

    return max(legal, key=score)
