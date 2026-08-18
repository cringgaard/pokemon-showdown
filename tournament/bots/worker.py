"""JSONL bridge that reserves stdout for the tournament worker protocol."""

import contextlib
import importlib.util
import json
import os
import sys
import traceback


def emit(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def load_participant(path):
    spec = importlib.util.spec_from_file_location("tournament_participant", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load participant module: {path}")
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
    if not callable(getattr(module, "choose_action", None)):
        raise RuntimeError("Participant main.py must define choose_action(state)")
    return module


def main():
    if len(sys.argv) != 2:
        raise RuntimeError("Usage: worker.py PARTICIPANT_MAIN_PY")
    participant = load_participant(os.path.abspath(sys.argv[1]))
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if message.get("type") != "decision":
                raise ValueError("Expected a decision message")
            with contextlib.redirect_stdout(sys.stderr):
                response = participant.choose_action(message["state"])
            emit({
                "type": "result",
                "id": message["id"],
                "revision": message["revision"],
                "response": response,
            })
        except BaseException as error:  # Participant failures must cross JSONL, never kill the bridge.
            emit({
                "type": "error",
                "id": message.get("id") if isinstance(locals().get("message"), dict) else None,
                "revision": message.get("revision") if isinstance(locals().get("message"), dict) else None,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            })


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
