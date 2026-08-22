from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow.mechanics import MechanicsSnapshot, UnresolvedMechanicError


def verify(snapshot_path: Path) -> None:
	mechanics = MechanicsSnapshot.load(snapshot_path).require_champions_format()

	assert mechanics.showdown_commit == "test-commit"
	assert mechanics.semantic_version == 1
	assert mechanics.move_multiplier("Freeze-Dry", ["Water", "Flying"]) == 4.0
	assert mechanics.is_immune("Body Press", ["Ghost"])
	assert mechanics.wide_guard_blocks("Heat Wave")
	assert not mechanics.wide_guard_blocks("Weather Ball")
	assert mechanics.weather_grants_perfect_accuracy("Blizzard", "snow")
	assert mechanics.ability_bypasses_accuracy("No Guard")
	assert mechanics.form_after_item_transformation("Aggron", "Aggronite").name == "Aggron-Mega"
	assert mechanics.species("Aggron").types == ("Steel", "Rock")
	assert mechanics.species("Aggron-Mega").types == ("Steel",)
	assert mechanics.semantic("abilities", "Snow Cloak")["incoming_accuracy_multiplier_in_weather"]["snow"] == 0.8
	assert mechanics.semantic("items", "Bright Powder")["incoming_accuracy_multiplier"] == 0.9
	assert mechanics.semantic("moves", "Mud-Slap")["target_accuracy_change"] == -1

	try:
		mechanics.move_multiplier("Weather Ball", ["Grass"])
	except UnresolvedMechanicError:
		pass
	else:
		raise AssertionError("Weather Ball's callback-driven type must not be treated as statically resolved")


if __name__ == "__main__":
	if len(sys.argv) != 2:
		raise SystemExit("usage: verify_mechanics_snapshot.py <snapshot-json>")
	verify(Path(sys.argv[1]))
