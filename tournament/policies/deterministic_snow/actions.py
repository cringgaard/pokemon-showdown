"""Canonical IDs for legal actions supplied by the tournament harness."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .serialization import canonical_json, parse_json

ACTION_CANONICAL_VERSION = 1
POSITIONS = ("left", "right")


@dataclass(frozen=True)
class CanonicalLegalAction:
	"""A stable representation of one harness-provided complete legal action."""

	action_id: str
	canonical_key: str
	payload_json: str

	@property
	def payload(self) -> dict[str, Any]:
		return parse_json(self.payload_json)

	def to_dict(self) -> dict[str, Any]:
		return {
			"action_id": self.action_id,
			"canonical_key": self.canonical_key,
			"payload": self.payload,
		}

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalLegalAction":
		payload = _required_mapping(value, "payload")
		kind = payload.get("kind")
		if kind == "team_preview":
			reconstructed = canonicalize_legal_action({"team": payload.get("team")})
		elif kind == "turn":
			actions = _required_mapping(payload, "actions")
			reconstructed = canonicalize_legal_action({
				"actions": {position: action for position, action in actions.items() if action is not None},
			})
		else:
			raise ValueError(f"Unknown canonical action kind: {kind!r}")
		if value.get("action_id", reconstructed.action_id) != reconstructed.action_id:
			raise ValueError("Canonical action ID does not match its payload")
		if value.get("canonical_key", reconstructed.canonical_key) != reconstructed.canonical_key:
			raise ValueError("Canonical action key does not match its payload")
		return reconstructed


def canonicalize_legal_actions(state_or_request: Mapping[str, Any]) -> tuple[CanonicalLegalAction, ...]:
	"""Canonicalize, but never generate or alter, the supplied complete legal actions."""
	request = state_or_request.get("request", state_or_request)
	if not isinstance(request, Mapping):
		raise ValueError("request must be an object")
	legal_actions = request.get("legal_actions")
	if not isinstance(legal_actions, Sequence) or isinstance(legal_actions, (str, bytes)):
		raise ValueError("request.legal_actions must be an array")
	result = tuple(canonicalize_legal_action(_mapping(action, "legal action")) for action in legal_actions)
	ids = [action.action_id for action in result]
	if len(ids) != len(set(ids)):
		raise ValueError("request.legal_actions contains duplicate canonical actions")
	return result


def canonicalize_legal_action(action: Mapping[str, Any]) -> CanonicalLegalAction:
	"""Normalize a schema-v2 Team Preview or joint action into a versioned ID."""
	if "team" in action:
		if set(action) != {"team"}:
			raise ValueError("Team Preview actions may contain only 'team'")
		team = action["team"]
		if not isinstance(team, Sequence) or isinstance(team, (str, bytes)) or not team:
			raise ValueError("Team Preview action.team must be a non-empty array")
		if not all(isinstance(pokemon, str) and pokemon for pokemon in team):
			raise ValueError("Team Preview action IDs must be non-empty strings")
		payload: dict[str, Any] = {"kind": "team_preview", "team": list(team)}
	elif "actions" in action:
		if set(action) != {"actions"}:
			raise ValueError("Turn actions may contain only 'actions'")
		actions = _required_mapping(action, "actions")
		unknown_positions = set(actions) - set(POSITIONS)
		if unknown_positions:
			raise ValueError(f"Unknown action positions: {sorted(unknown_positions)}")
		payload = {
			"kind": "turn",
			"actions": {position: _normalize_slot_action(actions.get(position)) for position in POSITIONS},
		}
	else:
		raise ValueError("Legal action must contain either 'team' or 'actions'")

	payload_json = canonical_json(payload)
	canonical_key = f"action-v{ACTION_CANONICAL_VERSION}:{payload_json}"
	digest = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()
	return CanonicalLegalAction(
		action_id=f"action-v{ACTION_CANONICAL_VERSION}-{digest}",
		canonical_key=canonical_key,
		payload_json=payload_json,
	)


def _normalize_slot_action(value: Any) -> dict[str, Any] | None:
	if value is None:
		return None
	action = _mapping(value, "slot action")
	action_type = action.get("type")
	if action_type == "move":
		allowed = {"type", "move", "target", "transformation"}
		if set(action) - allowed:
			raise ValueError(f"Unknown move action fields: {sorted(set(action) - allowed)}")
		move = _required_string(action, "move")
		normalized = {"type": "move", "move": move}
		for optional in ("target", "transformation"):
			if optional in action:
				normalized[optional] = _required_string(action, optional)
		return normalized
	if action_type in ("switch", "revive"):
		if set(action) != {"type", "pokemon"}:
			raise ValueError(f"{action_type} actions require only type and pokemon")
		return {"type": action_type, "pokemon": _required_string(action, "pokemon")}
	raise ValueError(f"Unknown slot action type: {action_type!r}")


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
	if key not in value:
		raise ValueError(f"Missing required field: {key}")
	return _mapping(value[key], key)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
	if not isinstance(value, Mapping):
		raise ValueError(f"{label} must be an object")
	return value


def _required_string(value: Mapping[str, Any], key: str) -> str:
	item = value.get(key)
	if not isinstance(item, str) or not item:
		raise ValueError(f"{key} must be a non-empty string")
	return item
