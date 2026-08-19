import subprocess
import sys
import time


def choose_action(state):
    if state["runtime"]["decision_id"] != 7:
        return state["request"]["legal_actions"][0]
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(f"spawned-child-pid={child.pid}", file=sys.stderr, flush=True)
    time.sleep(60)
