"""Deterministic JSON helpers shared by policy foundation modules."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping


def to_primitive(value: Any) -> Any:
	"""Convert policy values into JSON primitives without losing ordering semantics."""
	if isinstance(value, Enum):
		return value.value
	if hasattr(value, "to_dict") and callable(value.to_dict):
		return to_primitive(value.to_dict())
	if is_dataclass(value):
		return {field.name: to_primitive(getattr(value, field.name)) for field in fields(value)}
	if isinstance(value, Mapping):
		return {str(key): to_primitive(item) for key, item in value.items()}
	if isinstance(value, (tuple, list)):
		return [to_primitive(item) for item in value]
	if isinstance(value, (str, int, float, bool)) or value is None:
		return value
	raise TypeError(f"Unsupported policy serialization value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
	"""Serialize with stable object-key order and no insignificant whitespace."""
	return json.dumps(
		to_primitive(value),
		allow_nan=False,
		ensure_ascii=False,
		separators=(",", ":"),
		sort_keys=True,
	)


def parse_json(value: str) -> Any:
	return json.loads(value)
