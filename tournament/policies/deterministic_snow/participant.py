"""Tournament participant wrapper for the deterministic snow policy."""

from pathlib import Path
import sys


POLICY_PARENT = Path(__file__).resolve().parent.parent
if str(POLICY_PARENT) not in sys.path:
	sys.path.insert(0, str(POLICY_PARENT))

from deterministic_snow.policy import choose_action  # noqa: E402,F401
