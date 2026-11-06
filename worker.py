"""Fixed inert worker. Context text is data; only parent protocol advances work."""
import json
import signal
import sys
from pathlib import Path

def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)

def main():
    if sys.argv[1:] not in ([], ["--ignore-term"]):
        return 2
    ignore_term = sys.argv[1:] == ["--ignore-term"]
    if ignore_term:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    emit("ready", ignore_term=ignore_term)
    count = 0
    for raw in sys.stdin.buffer:
        if len(raw) > 4096:
            return 2
        try:
            command = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return 2
        if not isinstance(command, dict):
            return 2
        if set(command) == {"op", "text"} and command["op"] == "context" and isinstance(command["text"], str):
            emit("context_ack", text=command["text"], completed=count)
        elif command == {"op": "step"} and count < 2:
            marker = (b"FIRST\n", b"SECOND\n")[count]
            with Path("effects.txt").open("ab") as stream:
                stream.write(marker)
            count += 1
            emit("wrote", completed=count)
        elif command == {"op": "exit"}:
            emit("exit_ack", completed=count)
            return 0
        else:
            return 2
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
