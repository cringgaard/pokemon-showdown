"""Tournament participant wrapper for the deterministic snow policy."""

import os
from pathlib import Path
import sys


POLICY_PARENT = Path(__file__).resolve().parent.parent
if str(POLICY_PARENT) not in sys.path:
	sys.path.insert(0, str(POLICY_PARENT))

from deterministic_snow.policy import (  # noqa: E402
	TRACE_STDERR_ENV,
	SnowPolicy,
	default_mechanics_path,
)
from deterministic_snow.trace import TraceLevel  # noqa: E402


_POLICY: SnowPolicy | None = None


def choose_action(state):
	"""Return one legal BotResponse; build traces only when stderr tracing is enabled."""
	global _POLICY
	trace_enabled = os.environ.get(TRACE_STDERR_ENV) == "1"
	if _POLICY is None:
		_POLICY = SnowPolicy.from_mechanics_path(
			default_mechanics_path(),
			trace_level=TraceLevel.TOP_CANDIDATES if trace_enabled else TraceLevel.NONE,
		)
	decision = _POLICY.decide(state)
	if trace_enabled and decision.trace is not None:
		sys.stderr.write(decision.trace.to_json() + "\n")
		sys.stderr.flush()
	return decision.response
