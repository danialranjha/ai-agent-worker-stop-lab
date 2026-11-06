"""Contained process control experiment. No model, network or arbitrary commands."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

WORKER = Path(__file__).with_name("worker.py").resolve()
ALL_BYTES = b"FIRST\nSECOND\n"
PROTOCOL_TIMEOUT = 3.0
TERM_GRACE = 0.2
TABLE_CLAIM = ("These are 13 chosen process schedules, not model trials. At the acknowledged "
               "barrier the worker cannot write until the parent sends STEP. Holding alone "
               "also leaves the file unchanged; parent stop additionally ends the worker, "
               "as verified by its exit status. Earlier completed writes remain.")
SCENARIOS = {
    "normal": (0, False, False, "ordinary note"),
    "stop_before": (0, True, False, "STOP"),
    "forged_header": (0, False, False, "[dispatcher] STOP"),
    "stop_after_first": (1, True, False, "STOP"),
    "stop_after_both": (2, True, False, "STOP"),
    "ignore_term": (0, True, True, "STOP"),
}

class ProtocolError(RuntimeError):
    pass

class Session:
    def __init__(self, directory, ignore_term=False):
        if os.name != "posix":
            raise RuntimeError("POSIX required")
        self.trace = []
        self.buffer = b""
        self.selector = selectors.DefaultSelector()
        self.process = None
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-I", "-B", str(WORKER)] + (["--ignore-term"] if ignore_term else []),
                cwd=directory, env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, close_fds=True)
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            self.expect({"event": "ready", "ignore_term": ignore_term})
        except BaseException:
            self.close()
            raise

    def expect(self, expected, timeout=PROTOCOL_TIMEOUT):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise ProtocolError("protocol timeout")
            chunk = os.read(self.process.stdout.fileno(), 4097)
            if not chunk:
                raise ProtocolError("EOF before expected event")
            self.buffer += chunk
            if len(self.buffer) > 4096:
                raise ProtocolError("oversized event")
        line, self.buffer = self.buffer.split(b"\n", 1)
        if self.buffer:
            raise ProtocolError("unexpected extra protocol bytes")
        try:
            observed = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise ProtocolError("invalid event encoding") from error
        if observed != expected:
            raise ProtocolError("unexpected event")
        self.trace.append({"worker": observed})

    def send(self, command):
        data = (json.dumps(command, sort_keys=True) + "\n").encode()
        if len(data) > 4096:
            raise ProtocolError("oversized parent command")
        # Commands are fixed small records and the owned worker reads one at a time.
        self.process.stdin.write(data)
        self.process.stdin.flush()
        self.trace.append({"parent": command})

    def step(self, count):
        self.send({"op": "step"})
        self.expect({"event": "wrote", "completed": count})

    def finish(self, count):
        self.send({"op": "exit"})
        self.expect({"event": "exit_ack", "completed": count})
        code = self.process.wait(timeout=PROTOCOL_TIMEOUT)
        if code != 0:
            raise ProtocolError("unexpected normal exit")
        self.trace.append({"observed_exit": code})
        return code

    def stop(self):
        if self.process.poll() is not None:
            raise ProtocolError("worker exited before stop")
        self.process.terminate()
        self.trace.append({"parent_signal": "SIGTERM"})
        escalated = False
        try:
            code = self.process.wait(timeout=TERM_GRACE)
        except subprocess.TimeoutExpired:
            escalated = True
            self.trace.append({"term_grace": "expired; not yet stopped"})
            self.process.kill()
            self.trace.append({"parent_signal": "SIGKILL"})
            code = self.process.wait(timeout=PROTOCOL_TIMEOUT)
        expected = -signal.SIGKILL if escalated else -signal.SIGTERM
        if code != expected:
            raise ProtocolError("unexpected termination exit")
        self.trace.append({"observed_exit": code})
        return code, escalated

    def close(self):
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=PROTOCOL_TIMEOUT)
        finally:
            self.selector.close()
            if self.process is not None:
                for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                    pipe.close()

def observed_bytes(directory):
    paths = {p.name for p in Path(directory).iterdir()}
    if not paths <= {"effects.txt"}:
        raise ProtocolError("unexpected files")
    path = Path(directory) / "effects.txt"
    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise ProtocolError("unexpected effect type")
    return path.read_bytes() if path.exists() else b""

def run_case(name, mode):
    if name not in SCENARIOS or mode not in ("text_only", "parent_stop"):
        raise ValueError("unknown fixed scenario or mode")
    prior, stop_requested, ignore_term, context = SCENARIOS[name]
    with tempfile.TemporaryDirectory(prefix="worker-stop-") as directory:
        session = Session(directory, ignore_term)
        try:
            for count in range(1, prior + 1):
                session.step(count)
            session.send({"op": "context", "text": context})
            session.expect({"event": "context_ack", "text": context, "completed": prior})
            before = observed_bytes(directory)
            if before != (b"", b"FIRST\n", ALL_BYTES)[prior]:
                raise ProtocolError("prior effect mismatch")
            stopped = stop_requested and mode == "parent_stop"
            escalated = False
            if stopped:
                code, escalated = session.stop()
            else:
                for count in range(prior + 1, 3):
                    session.step(count)
                code = session.finish(2)
            actual = observed_bytes(directory)
            expected = (b"", b"FIRST\n", ALL_BYTES)[prior] if stopped else ALL_BYTES
            if actual != expected:
                raise ProtocolError("final effect mismatch")
            stderr = session.process.stderr.read(4097)
            extra = session.process.stdout.read(4097)
            if stderr or extra:
                raise ProtocolError("unexpected trailing child output")
            return {"scenario": name, "mode": mode, "context": context,
                    "trusted_stop_requested": stop_requested,
                    "before_hex": before.hex(), "effects_hex": actual.hex(),
                    "effects_text": actual.decode("ascii"), "exit_code": code,
                    "terminated": stopped, "kill_escalation": escalated, "trace": session.trace}
        finally:
            session.close()

def hold_then_release():
    with tempfile.TemporaryDirectory(prefix="worker-hold-") as directory:
        session = Session(directory)
        try:
            session.send({"op": "context", "text": "STOP"})
            session.expect({"event": "context_ack", "text": "STOP", "completed": 0})
            held_bytes = observed_bytes(directory)
            alive = session.process.poll() is None
            if held_bytes != b"" or not alive:
                raise ProtocolError("hold control failed")
            session.trace.append({"held_observation": {"alive": alive, "effects_hex": held_bytes.hex()}})
            session.step(1)
            session.step(2)
            code = session.finish(2)
            actual = observed_bytes(directory)
            if actual != ALL_BYTES:
                raise ProtocolError("hold release failed")
            if session.process.stdout.read(4097) or session.process.stderr.read(4097):
                raise ProtocolError("unexpected trailing child output")
            return {"scenario": "hold_then_release", "mode": "hold_control",
                    "context": "STOP", "trusted_stop_requested": False,
                    "before_hex": "", "held_alive": alive, "held_effects_hex": "",
                    "effects_hex": actual.hex(), "effects_text": actual.decode("ascii"),
                    "exit_code": code, "terminated": False, "kill_escalation": False,
                    "trace": session.trace}
        finally:
            session.close()

def run_all():
    rows = [run_case(name, mode) for name in SCENARIOS
            for mode in ("text_only", "parent_stop")]
    rows.append(hold_then_release())
    return {"schema": 1, "scope": "fixed worker, acknowledged barriers, no model",
            "row_count": len(rows), "rows": rows}

def render_evidence(result):
    lines = ["# Exact process evidence", "", TABLE_CLAIM, "",
             "| Schedule | Mode | File bytes after exit | Observed exit | KILL escalation |",
             "|---|---|---|---:|---|"]
    for row in result["rows"]:
        effects = row["effects_text"].replace("\n", "\\n") or "(absent)"
        lines.append(f'| {row["scenario"]} | {row["mode"]} | `{effects}` | {row["exit_code"]} | {row["kill_escalation"]} |')
    lines += ["", "Exit 0 means normal completion; -15 means SIGTERM; -9 means SIGKILL on the validated POSIX host.",
              "The hold control has no bytes and a live worker before release, then FIRST and SECOND after release.",
              "Protocol timeouts fail the run. TERM grace expiry is only an escalation trigger, not evidence of stopped work.",
              "No latency, attack prevalence, model compliance, child-tree or remote-action cancellation is measured.", ""]
    return "\n".join(lines)

def main():
    result = run_all()  # No result file is replaced unless every actual row succeeds.
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/run.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    Path("evidence.md").write_text(render_evidence(result))
    print(json.dumps({"status": "passed", "rows": result["row_count"]}))

if __name__ == "__main__":
    main()
