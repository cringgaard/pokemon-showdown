from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow.mechanics import MechanicsSnapshot, UnresolvedMechanicError


def assert_unresolved(callback, message: str) -> None:
	try:
		callback()
	except UnresolvedMechanicError:
		return
	raise AssertionError(message)


def verify(snapshot_path: Path) -> None:
	mechanics = MechanicsSnapshot.load(snapshot_path).require_champions_format()

	assert mechanics.showdown_commit == "test-commit"
	assert mechanics.semantic_version == 1
	assert mechanics.move_multiplier("Freeze-Dry", ["Water", "Flying"]) == 4.0
	assert mechanics.is_immune("Body Press", ["Ghost"])

	assert mechanics.wide_guard_blocks("Heat Wave")
	assert not mechanics.wide_guard_blocks("Weather Ball")
	heat_wave = mechanics.move("Heat Wave")
	assert not mechanics.wide_guard_blocks(replace(heat_wave, flags=tuple(flag for flag in heat_wave.flags if flag != "protect")))
	assert_unresolved(
		lambda: mechanics.wide_guard_blocks(replace(heat_wave, flags=heat_wave.flags + ("contact",))),
		"Contact spread protection must stay unresolved without attacker context",
	)

	assert mechanics.weather_grants_perfect_accuracy("Blizzard", "snowscape")
	assert mechanics.weather_grants_perfect_accuracy("Blizzard", "hail")
	assert not mechanics.weather_grants_perfect_accuracy("Blizzard", "raindance")
	assert mechanics.weather_grants_perfect_accuracy("Thunder", "raindance")
	assert mechanics.weather_grants_perfect_accuracy("Thunder", "primordialsea")
	assert not mechanics.weather_grants_perfect_accuracy("Thunder", "sunnyday")
	assert mechanics.weather_grants_perfect_accuracy("Hurricane", "raindance")
	assert not mechanics.weather_grants_perfect_accuracy("Thunderbolt", "raindance")
	assert_unresolved(
		lambda: mechanics.weather_grants_perfect_accuracy("Bleakwind Storm", "raindance"),
		"Unannotated onModifyMove weather behavior must fail closed",
	)

	assert mechanics.ability_bypasses_accuracy("No Guard")
	assert mechanics.form_after_item_transformation("Aggron", "Aggronite").name == "Aggron-Mega"
	assert mechanics.species("Aggron").types == ("Steel", "Rock")
	assert mechanics.species("Aggron-Mega").types == ("Steel",)

	snow_cloak = mechanics.semantic("abilities", "Snow Cloak")["incoming_accuracy_modifier_in_weather"]
	assert snow_cloak["snowscape"] == [3277, 4096]
	assert snow_cloak["hail"] == [3277, 4096]
	assert mechanics.semantic("abilities", "Snow Warning")["entry_weather"] == "snowscape"
	assert mechanics.semantic("items", "Bright Powder")["incoming_accuracy_modifier"] == [3686, 4096]
	assert mechanics.semantic("items", "Icy Rock")["weather_extension_turns"] == {"hail": 8, "snowscape": 8}
	assert mechanics.semantic("items", "Chople Berry")["super_effective_type_damage_multiplier"] == {"Fighting": 0.5}
	assert mechanics.semantic("items", "Colbur Berry")["super_effective_type_damage_multiplier"] == {"Dark": 0.5}
	assert mechanics.semantic("moves", "Aurora Veil")["requires_weather"] == ["hail", "snowscape"]

	gravity = mechanics.semantic("field", "Gravity")
	assert gravity["accuracy_multiplier_ratio"] == [6840, 4096]
	assert gravity["grounds_flying"] is True
	assert "suppresses_evasion" not in gravity
	assert mechanics.semantic("moves", "Mud-Slap")["target_accuracy_change"] == -1

	assert_unresolved(
		lambda: mechanics.move_multiplier("Weather Ball", ["Grass"]),
		"Weather Ball's callback-driven type must not be treated as statically resolved",
	)


if __name__ == "__main__":
	if len(sys.argv) != 2:
		raise SystemExit("usage: verify_mechanics_snapshot.py <snapshot-json>")
	verify(Path(sys.argv[1]))
