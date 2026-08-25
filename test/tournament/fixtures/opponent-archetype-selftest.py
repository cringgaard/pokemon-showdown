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


def opponent_active(position, team_id, species):
    return {
        "position": position,
        "apparent_species": species,
        "team_id": team_id,
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
        "field": {"weather": "snow", "conditions": {}},
        "request": {
            "kind": "turn",
            "slots": {
                "left": {"moves": [{"id": "protect", "base_power": 0, "category": "Status"}]},
                "right": {"moves": [{"id": "protect", "base_power": 0, "category": "Status"}]},
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
        "self": {
            "team": team,
            "active": {"left": "team_0", "right": "team_1"},
            "side_conditions": {},
        },
        "opponent": {"team": [], "active": {}},
        "field": {"weather": None, "conditions": {}},
        "request": {
            "kind": "turn",
            "slots": {
                "left": {"moves": [
                    {"id": "trickroom", "base_power": 0, "category": "Status"},
                    {"id": "psychic", "base_power": 90, "category": "Special"},
                ]},
                "right": {"moves": [{"id": "protect", "base_power": 0, "category": "Status"}]},
            },
            "legal_actions": [
                {"actions": {"left": {"type": "move", "move": "psychic", "target": "opponent_left"}, "right": {"type": "move", "move": "protect"}}},
                {"actions": {"left": {"type": "move", "move": "trickroom"}, "right": {"type": "move", "move": "protect"}}},
            ],
        },
    }


def fighting_focus_state():
    team = [
        pokemon("team_0", "Sneasler"), pokemon("team_1", "Blaziken"),
        pokemon("team_2", "Incineroar"), pokemon("team_3", "Urshifu"),
        pokemon("team_4", "Farigiraf"), pokemon("team_5", "Gholdengo"),
    ]
    opponent = [
        {"id": "opponent_0", "species": "Aggron"},
        {"id": "opponent_1", "species": "Glaceon"},
    ]
    return {
        "self": {
            "team": team,
            "active": {"left": "team_0", "right": "team_1"},
            "side_conditions": {},
        },
        "opponent": {
            "team": opponent,
            "active": {
                "left": opponent_active("left", "opponent_0", "Aggron"),
                "right": opponent_active("right", "opponent_1", "Glaceon"),
            },
        },
        "field": {"weather": None, "conditions": {}},
        "request": {
            "kind": "turn",
            "slots": {
                "left": {"moves": [{"id": "closecombat", "base_power": 120, "category": "Physical"}]},
                "right": {"moves": [{"id": "protect", "base_power": 0, "category": "Status"}]},
            },
            "legal_actions": [
                {"actions": {"left": {"type": "move", "move": "closecombat", "target": "opponent_right"}, "right": {"type": "move", "move": "protect"}}},
                {"actions": {"left": {"type": "move", "move": "closecombat", "target": "opponent_left"}, "right": {"type": "move", "move": "protect"}}},
            ],
        },
    }


def spread_scoring_state():
    own = pokemon("team_0", "Gholdengo")
    return own, {
        "self": {"team": [own], "active": {"left": "team_0"}, "side_conditions": {}},
        "opponent": {"team": [], "active": {}},
        "field": {"weather": None, "conditions": {}},
        "request": {
            "kind": "turn",
            "slots": {"left": {"moves": [
                {"id": "makeitrain", "base_power": 120, "category": "Special"},
                {"id": "shadowball", "base_power": 120, "category": "Special"},
            ]}},
            "legal_actions": [],
        },
    }


bot._POLICY = None
rain = bot.choose_action(rain_state())
assert rain["actions"]["left"] == {"type": "switch", "pokemon": "team_0"}, rain

bot._POLICY = None
trick_room = bot.choose_action(trick_room_state())
assert trick_room["actions"]["left"]["move"] == "trickroom", trick_room

active_trick_room = trick_room_state()
active_trick_room["field"]["conditions"] = {"trickroom": {"active": True, "started_turn": 1}}
bot._POLICY = None
trick_room_progress = bot.choose_action(active_trick_room)
assert trick_room_progress["actions"]["left"]["move"] == "psychic", trick_room_progress

bot._POLICY = None
fighting = bot.choose_action(fighting_focus_state())
assert fighting["actions"]["left"]["target"] == "opponent_left", fighting

spread_own, spread_state = spread_scoring_state()
spread = bot._score_move(
    spread_state, {"spread_move_bonus": 35}, "left",
    {"type": "move", "move": "makeitrain"}, spread_own,
)
single = bot._score_move(
    spread_state, {"spread_move_bonus": 35}, "left",
    {"type": "move", "move": "shadowball", "target": "opponent_left"}, spread_own,
)
assert spread == single + 35, (spread, single)

print("opponent archetype self-test passed")
