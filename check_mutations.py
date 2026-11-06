"""Focused negative checks in temporary copies; source checkout is unchanged."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parent
source = (root / 'experiment.py').read_text()
mutations = {
    'ignore_parent_stop': ('stopped = stop_requested and mode == "parent_stop"', 'stopped = False'),
    'erase_prior_effect': ('code, escalated = session.stop()', 'code, escalated = session.stop()\n                Path(directory, "effects.txt").write_bytes(b"")'),
}
test = r'''
import unittest
import experiment
class FaultProbe(unittest.TestCase):
    def test_prior_effect_and_signal_exit(self):
        try:
            row = experiment.run_case("stop_after_first", "parent_stop")
        except experiment.ProtocolError as error:
            if str(error) != "final effect mismatch":
                raise
            self.fail("Independent byte oracle rejected erased prior effect")
        self.assertEqual(row["effects_text"], "FIRST\n")
        self.assertEqual(row["exit_code"], -15)
if __name__ == "__main__":
    unittest.main()
'''
results = []
for name, (old, new) in mutations.items():
    if source.count(old) != 1:
        raise RuntimeError('mutation anchor mismatch')
    with tempfile.TemporaryDirectory(prefix='worker-stop-fault-') as temp:
        target = Path(temp)
        for file in ('worker.py', 'experiment.py'):
            shutil.copyfile(root / file, target / file)
        (target / 'experiment.py').write_text(source.replace(old, new))
        (target / 'test_fault.py').write_text(test)
        proc = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-v', 'test_fault'],
                              cwd=target, capture_output=True, text=True, timeout=30)
        if proc.returncode != 1 or 'FAILED (failures=1)' not in proc.stderr:
            raise RuntimeError('fault not detected by expected assertion: ' + name + '\n' + proc.stderr)
        results.append({'fault': name, 'exit_code': proc.returncode,
                        'failures': 1, 'errors': 0, 'output': proc.stderr})
print(json.dumps(results, indent=2))
