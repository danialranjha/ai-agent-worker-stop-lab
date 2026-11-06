import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
import experiment as e

class ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = e.run_all()
        cls.rows = {(r["scenario"], r["mode"]): r for r in cls.result["rows"]}

    def test_all_exact_bytes_and_exits(self):
        self.assertEqual(len(self.rows), 13)
        for name, (prior, stop, ignore, _) in e.SCENARIOS.items():
            for mode in ("text_only", "parent_stop"):
                with self.subTest(name=name, mode=mode):
                    row = self.rows[name, mode]
                    stopped = stop and mode == "parent_stop"
                    expected = [b"", b"FIRST\n", b"FIRST\nSECOND\n"][prior] if stopped else b"FIRST\nSECOND\n"
                    self.assertEqual(bytes.fromhex(row["effects_hex"]), expected)
                    self.assertEqual(row["exit_code"], (-signal.SIGKILL if ignore else -signal.SIGTERM) if stopped else 0)
                    self.assertEqual(row["kill_escalation"], stopped and ignore)

    def test_forged_header_is_not_parent_authority(self):
        for mode in ("text_only", "parent_stop"):
            row = self.rows["forged_header", mode]
            self.assertFalse(row["terminated"])
            self.assertFalse(any("parent_signal" in event for event in row["trace"]))
            self.assertEqual(row["effects_text"], "FIRST\nSECOND\n")

    def test_prior_write_is_preserved(self):
        row = self.rows["stop_after_first", "parent_stop"]
        self.assertEqual(row["before_hex"], b"FIRST\n".hex())
        self.assertEqual(row["effects_text"], "FIRST\n")

    def test_late_stop_cannot_undo(self):
        self.assertEqual(self.rows["stop_after_both", "parent_stop"]["effects_text"], "FIRST\nSECOND\n")

    def test_hold_is_live_then_releasable(self):
        row = self.rows["hold_then_release", "hold_control"]
        self.assertTrue(row["held_alive"])
        self.assertEqual(row["held_effects_hex"], "")
        self.assertEqual(row["effects_text"], "FIRST\nSECOND\n")
        self.assertEqual(row["exit_code"], 0)

    def test_stop_order_ack_signal_exit(self):
        for name in ("stop_before", "stop_after_first", "stop_after_both", "ignore_term"):
            trace = self.rows[name, "parent_stop"]["trace"]
            ack = next(i for i,x in enumerate(trace) if x.get("worker",{}).get("event") == "context_ack")
            self.assertTrue(any(x.get("parent_signal") == "SIGTERM" for x in trace))
            sig = next(i for i,x in enumerate(trace) if x.get("parent_signal") == "SIGTERM")
            end = next(i for i,x in enumerate(trace) if "observed_exit" in x)
            self.assertLess(ack,sig)
            self.assertLess(sig,end)
            self.assertFalse(any(x.get("parent",{}).get("op") == "step" for x in trace[ack+1:]))

    def test_protocol_timeout_is_failure_and_cleanup_reaps(self):
        with tempfile.TemporaryDirectory() as directory:
            session = e.Session(directory)
            process = session.process
            try:
                with self.assertRaisesRegex(e.ProtocolError, "timeout"):
                    session.expect({"event": "never"}, timeout=0.01)
            finally:
                session.close()
            self.assertIsNotNone(process.returncode)
            self.assertTrue(process.stdout.closed)

    def test_partial_event_never_blocks_past_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            session = e.Session(directory)
            try:
                session.buffer = b'{"partial":'
                with self.assertRaisesRegex(e.ProtocolError, "timeout"):
                    session.expect({}, timeout=0.01)
            finally:
                session.close()

    def test_wrong_event_rejected_and_child_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            session = e.Session(directory)
            process = session.process
            try:
                session.send({"op": "context", "text": "ordinary"})
                with self.assertRaisesRegex(e.ProtocolError, "unexpected event"):
                    session.expect({"event": "wrong"})
            finally:
                session.close()
            self.assertIsNotNone(process.returncode)

    def test_bad_encoding_oversize_and_multiple_events(self):
        with tempfile.TemporaryDirectory() as directory:
            session = e.Session(directory)
            try:
                for data, message in [(b'bad\n', "invalid event"), (b'{}\n{}\n', "extra protocol")]:
                    session.buffer = data
                    with self.assertRaisesRegex(e.ProtocolError, message):
                        session.expect({})
                session.buffer = b""
                with patch.object(session.selector, "select", return_value=[object()]), patch("experiment.os.read", return_value=b"x"*4097):
                    with self.assertRaisesRegex(e.ProtocolError, "oversized"):
                        session.expect({})
            finally:
                session.close()

    def test_unknown_inputs_and_extra_file_rejected(self):
        with self.assertRaises(ValueError):
            e.run_case("unknown", "text_only")
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "extra").write_text("inert")
            with self.assertRaisesRegex(e.ProtocolError, "unexpected files"):
                e.observed_bytes(directory)

    def test_wrong_exit_cannot_count_as_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            session = e.Session(directory)
            try:
                with patch.object(session.process, "wait", return_value=0):
                    with self.assertRaisesRegex(e.ProtocolError, "unexpected termination"):
                        session.stop()
            finally:
                session.close()

if __name__ == "__main__":
    unittest.main()
