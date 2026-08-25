from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BOT_PATH = ROOT / "tournament/evaluation/opponents/archetype_bot.py"
spec = importlib.util.spec_from_file_location("benchmark_archetype_bot", BOT_PATH)
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


def pokemon(pid, species, hp=100):
    return {
        "id": pid,
        "species": species,
        "health": {"current": hp, "max": 100, "exact": True},
        "stats": {"atk": 100, "spa": 100},
    }


def rain_state():
    team = [
        pokemon("team_0", "Pelipper"), pokemon("team_1", "Archaludon"),
        pokemon("team_2", "Sneasler"), pokemon("team_3", "Basculegion"),
        pokemon("team_4", "Dragonite"), pokemon("team_5", "Meganium"),
    ]
    return {
        "self": {"team": team, "active": {"left": "team_2", "right": "team_1"}},
        "opponent": {"team": [], "active": {}},
        "field": {"weather": {"id": "snow"}},
        "request": {
            "kind": "turn",
            "slots": {
                "left": {"moves": [{"id": "protect", "base_power": 0, "category": "Status", "target": "self"}]},
                "right": {"moves": [{"id": "protect", "base_power": 0, "category": "Status", "target": "self"}]},
            },
            "legal_actions": [
                {"actions": {"left": {"type": "move", "move": "protect"}, "right": {"type": "move", "move": "protect"}}},
                {"actions": {"left": {"type": "switch", "pokemon": "team_0"}, "right": {"type": "move", "move": "protect"}}},
            ],
        },
    }


def trick_room_state():
    team = [
        pokemon("team_0", "Farigiraf"), pokemon("team_1", "Armarouge"),
        pokemon("team_2", "Ursaluna"), pokemon("team_3", "Sinistcha"),
        pokemon("team_4", "Incineroar"), pokemon("team_5", "Kingambit"),
    ]
    team[0]["stats"]["spa"] = 60
    return {
        "self": {"team": team, "active": {"left": "team_0", "right": "team_1"}},
        "opponent": {"team": [], "active": {}},
        "field": {"weather": None},
        "request": {
            "kind": "turn",
            "slots": {
                "left": {"moves": [
                    {"id": "trickroom", "base_power": 0, "category": "Status", "target": "all"},
                    {"id": "psychic", "base_power": 90, "category": "Special", "target": "normal"},
                ]},
                "right": {"moves": [{"id": "protect", "base_power": 0, "category": "Status", "target": "self"}]},
            },
            "legal_actions": [
                {"actions": {"left": {"type": "move", "move": "psychic", "target": "opponent_left"}, "right": {"type": "move", "move": "protect"}}},
                {"actions": {"left": {"type": "move", "move": "trickroom"}, "right": {"type": "move", "move": "protect"}}},
            ],
        },
    }


bot._POLICY = None
rain = bot.choose_action(rain_state())
assert rain["actions"]["left"] == {"type": "switch", "pokemon": "team_0"}, rain

bot._POLICY = None
trick_room = bot.choose_action(trick_room_state())
assert trick_room["actions"]["left"]["move"] == "trickroom", trick_room

print("opponent archetype self-test passed")
