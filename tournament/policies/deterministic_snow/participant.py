"""Tournament participant wrapper for the deterministic snow policy."""

import os
from pathlib import Path
import sys
import traceback


POLICY_PARENT = Path(__file__).resolve().parent.parent
if str(POLICY_PARENT) not in sys.path:
	sys.path.insert(0, str(POLICY_PARENT))

from deterministic_snow.policy import (  # noqa: E402
	TRACE_STDERR_ENV,
	SnowPolicy,
	default_mechanics_path,
)
from deterministic_snow.trace import TraceLevel  # noqa: E402


TRACE_FILE_ENV = "DETERMINISTIC_SNOW_TRACE_FILE"
_POLICY: SnowPolicy | None = None


def choose_action(state):
	"""Return one legal BotResponse and optionally emit a structured decision trace."""
	global _POLICY
	stderr_trace = os.environ.get(TRACE_STDERR_ENV) == "1"
	trace_file = os.environ.get(TRACE_FILE_ENV)
	trace_level = (
		TraceLevel.FULL if trace_file else
		TraceLevel.TOP_CANDIDATES if stderr_trace else
		TraceLevel.NONE
	)
	try:
		if _POLICY is None:
			_POLICY = SnowPolicy.from_mechanics_path(
				default_mechanics_path(),
				trace_level=trace_level,
			)
		decision = _POLICY.decide(state)
		if trace_level is not TraceLevel.NONE and decision.trace is not None:
			line = decision.trace.to_json() + "\n"
			if stderr_trace:
				sys.stderr.write(line)
				sys.stderr.flush()
			if trace_file:
				path = Path(trace_file).expanduser().resolve()
				path.parent.mkdir(parents=True, exist_ok=True)
				with path.open("a", encoding="utf-8") as handle:
					handle.write(line)
		return decision.response
	except BaseException:
		# The generic JSONL bridge transports the exception to BotController, but
		# match artifacts otherwise lose its traceback after retries/fallback. Keep
		# participant failures visible on stderr without affecting successful turns.
		traceback.print_exc(file=sys.stderr)
		raise
