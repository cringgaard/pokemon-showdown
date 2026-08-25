"""Reusable public-state opponent bot for deterministic snow benchmark suites.

The bot selects one policy from policies.json by matching its own six-species
roster. It never reads opponent-private information and always returns one of
the harness-supplied legal actions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


_ROOT = Path(__file__).resolve().parent
_POLICIES = json.loads((_ROOT / "policies.json").read_text(encoding="utf-8"))
_POLICY: Mapping[str, Any] | None = None


def _id(value: object) -> str:
    return "".join(char for char in str(value).lower() if char.isalnum())


def _roster_key(species: list[str]) -> tuple[str, ...]:
    return tuple(sorted(_id(item) for item in species))


def _policy_for_state(state: Mapping[str, Any]) -> Mapping[str, Any]:
    global _POLICY
    if _POLICY is not None:
        return _POLICY
    team = state.get("self", {}).get("team", [])
    roster = _roster_key([pokemon.get("species", "") for pokemon in team])
    matches = [
        policy for policy in _POLICIES.get("policies", [])
        if _roster_key(policy.get("roster", [])) == roster
    ]
    if len(matches) != 1:
        raise ValueError(f"benchmark archetype bot expected one policy for roster {roster}, got {len(matches)}")
    _POLICY = matches[0]
    return _POLICY


def _health_fraction(pokemon: Mapping[str, Any] | None) -> float:
    if not pokemon:
        return 1.0
    health = pokemon.get("health")
    if not isinstance(health, Mapping):
        return 1.0
    current = health.get("current")
    maximum = health.get("max")
    if isinstance(current, (int, float)) and isinstance(maximum, (int, float)) and maximum > 0:
        return max(0.0, min(1.0, float(current) / float(maximum)))
    return 1.0


def _team_maps(state: Mapping[str, Any]):
    team = state.get("self", {}).get("team", [])
    by_id = {str(pokemon.get("id")): pokemon for pokemon in team}
    by_species = {_id(pokemon.get("species", "")): str(pokemon.get("id")) for pokemon in team}
    return by_id, by_species


def _preview_action(state: Mapping[str, Any], policy: Mapping[str, Any]):
    legal = state["request"]["legal_actions"]
    _, by_species = _team_maps(state)
    order = policy.get("preview_species_order", [])
    selected = [by_species.get(_id(species)) for species in order]
    selected = [pokemon_id for pokemon_id in selected if pokemon_id]
    if len(selected) >= 4:
        preferred = {"team": selected[:4]}
        if preferred in legal:
            return preferred
    return legal[0]


def _opponent_species_at_target(state: Mapping[str, Any], target: str) -> str | None:
    if not target.startswith("opponent_"):
        return None
    position = target.removeprefix("opponent_")
    opponent = state.get("opponent", {})
    active = opponent.get("active", {}).get(position)
    if not isinstance(active, Mapping):
        return None
    team_id = active.get("team_id")
    if team_id:
        for pokemon in opponent.get("team", []):
            if pokemon.get("id") == team_id:
                return _id(pokemon.get("species", ""))
    apparent = active.get("apparent_species")
    return _id(apparent) if apparent else None


def _move_for_slot(state: Mapping[str, Any], position: str, move_id: str):
    slot = state.get("request", {}).get("slots", {}).get(position, {})
    return next((move for move in slot.get("moves", []) if move.get("id") == move_id), None)


def _score_move(
    state: Mapping[str, Any], policy: Mapping[str, Any], position: str,
    action: Mapping[str, Any], own: Mapping[str, Any] | None,
) -> float:
    move_id = _id(action.get("move", ""))
    move = _move_for_slot(state, position, move_id)
    score = float(policy.get("move_weights", {}).get(move_id, 0.0))
    if move:
        base_power = float(move.get("base_power", 0) or 0)
        category = move.get("category")
        attacking_stat = 100.0
        if own:
            stats = own.get("stats", {})
            stat_id = "atk" if category == "Physical" else "spa"
            value = stats.get(stat_id)
            if isinstance(value, (int, float)):
                attacking_stat = float(value)
        score += base_power * attacking_stat / 100.0
        # Canonical legal actions omit target for non-selectable spread attacks,
        # while ordinary single-target attacks carry opponent_left/right.
        if base_power > 0 and category != "Status" and not action.get("target"):
            score += float(policy.get("spread_move_bonus", 0.0))
    target_species = _opponent_species_at_target(state, str(action.get("target", "")))
    if target_species:
        score += float(policy.get("target_species_weights", {}).get(target_species, 0.0))
    hp = _health_fraction(own)
    if move_id in {"protect", "detect", "spikyshield", "kingsshield"}:
        threshold = float(policy.get("protect_below_hp", 0.0))
        if hp <= threshold:
            score += float(policy.get("protect_low_hp_bonus", 0.0))
    if action.get("transformation"):
        score += float(policy.get("transformation_bonus", 0.0))
    return score


def _score_switch(
    state: Mapping[str, Any], policy: Mapping[str, Any], position: str,
    action: Mapping[str, Any], own: Mapping[str, Any] | None, by_id: Mapping[str, Mapping[str, Any]],
) -> float:
    target = by_id.get(str(action.get("pokemon", "")))
    target_species = _id(target.get("species", "")) if target else ""
    score = float(policy.get("switch_species_weights", {}).get(target_species, 0.0))
    weather_rule = policy.get("weather_reset")
    if isinstance(weather_rule, Mapping) and target_species == _id(weather_rule.get("species", "")):
        weather = state.get("field", {}).get("weather")
        weather_id = _id(weather.get("id", weather.get("value", ""))) if isinstance(weather, Mapping) else _id(weather)
        desired = _id(weather_rule.get("weather", ""))
        if weather_id != desired:
            score += float(weather_rule.get("bonus", 0.0))
    preserve = {_id(species) for species in policy.get("preserve_species", [])}
    if own and _id(own.get("species", "")) in preserve:
        threshold = float(policy.get("preserve_below_hp", 0.35))
        if _health_fraction(own) <= threshold:
            score += float(policy.get("preserve_switch_bonus", 0.0))
    return score


def _response_score(state: Mapping[str, Any], policy: Mapping[str, Any], response: Mapping[str, Any]) -> float:
    by_id, _ = _team_maps(state)
    active = state.get("self", {}).get("active", {})
    total = 0.0
    for position, action in response.get("actions", {}).items():
        if not isinstance(action, Mapping):
            continue
        own = by_id.get(str(active.get(position, "")))
        if action.get("type") == "move":
            total += _score_move(state, policy, position, action, own)
        elif action.get("type") == "switch":
            total += _score_switch(state, policy, position, action, own, by_id)
        else:
            total += float(policy.get("other_action_bonus", 0.0))
    return total


def choose_action(state):
    """Return one supplied legal action using only normalized public BotState."""
    legal = state["request"]["legal_actions"]
    if not legal:
        raise ValueError("benchmark archetype bot received no legal actions")
    policy = _policy_for_state(state)
    if state["request"].get("kind") == "team_preview":
        return _preview_action(state, policy)
    scored = [(_response_score(state, policy, response), index, response) for index, response in enumerate(legal)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][2]
