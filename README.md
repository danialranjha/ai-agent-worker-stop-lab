# AI-agent worker stop: text versus parent control

Sending STOP as ordinary context and ending a worker process are different operations. This independent, contained experiment uses a fixed Python worker that acknowledges context without interpreting it. It is **not an agentctl reproduction, AI model test or prompt-injection attack**.

## Hypothesis and threat model

A worker that ignores text can continue when its parent supplies the next work step. A trusted parent can end its owned child at an acknowledged synchronization barrier without that child's agreement. Effects completed before termination remain.

Assume the worker does not obey STOP text. A forged dispatcher header is also ordinary data. The parent, fixed worker code, Python, OS, protocol and independent file observer remain trusted. The parent already owns the child process handle; this lab does not implement authentication or protect against a malicious program running as the same OS user.

Only the parent can send protocol commands. Context text cannot select an operation or a signal. The worker writes only `FIRST\n` and `SECOND\n` to `effects.txt` in a fresh temporary directory. It spawns no descendants and uses no shell, network, credentials, external targets or real agent.

## Setup and exact commands

Python 3.10+ on POSIX, standard library only. Validated with Python 3.13.5 on macOS. From this directory:

```sh
python3 -B -m unittest -v test_experiment
python3 -B experiment.py
python3 -B check_mutations.py
```

The runner writes [artifacts/run.json](artifacts/run.json) and [evidence.md](evidence.md) only after all observed cases pass. Failed runs exit nonzero; an older saved artifact is not evidence of a failed rerun succeeding. The mutation checker uses disposable copies and prints its evidence as JSON. Temporary workers are killed/reaped and directories removed on success and failure. No package installation is needed.

## Results

Thirteen chosen process schedules completed; twelve focused tests passed. These are deterministic fixtures, not rates or independent attack samples.

In the main pair, the worker first writes FIRST, acknowledges the same STOP data, and waits for another parent command:

- **Text request:** The parent continues the fixed work. The worker writes SECOND and exits normally.
- **Parent stop:** The parent sends SIGTERM and waits for the child's signal exit. FIRST remains; SECOND is absent.

A held-live control is essential. Withholding the next step alone also leaves the file unchanged. That worker is still alive and writes both markers when released. Parent stop is distinguished by **observed process termination**, not missing bytes alone.

Normal work and forged-header controls finish both writes in both modes. A stop after both writes preserves both. A worker explicitly configured to ignore SIGTERM requires SIGKILL; a TERM grace timeout alone is not counted as a stop. Exact bytes, protocol traces, exit codes and escalation are in [the evidence table](evidence.md) and [run JSON](artifacts/run.json).

## Technical walkthrough

The [agentctl maintainer issue](https://github.com/blsmth/agentctl/issues/1) reports a worker refusing a correction delivered through hook context. It provides no transcript or model reproduction. That report motivates our separate engineering question about control placement; the issue's proposed preamble/header change is not tested here.

Python documents that [Popen.terminate sends SIGTERM on POSIX and negative return codes record signal termination](https://docs.python.org/3/library/subprocess.html). Our parent retains its own process handle, sends termination, and waits for the exit code. It never takes a PID from context text.

1. Launch a fixed worker with isolated Python mode, no inherited credentials and an owned temporary working directory.
2. Require READY, optionally issue prior STEP commands and check their WROTE acknowledgements.
3. Send context and require its exact acknowledgement. The child is now waiting for the parent's next command.
4. Continue with fixed steps, hold and later release, or terminate the owned child and require its observed exit.
5. Read exact file bytes from the parent after exit, independently of worker-reported write events.

[worker.py](worker.py) treats context text as data by construction. This is an assumption under test conditions, not a discovered model refusal. The parent alone chooses `step`, `exit` and whether to send a signal.

[experiment.py](experiment.py) reads protocol output with selectors, bounded raw byte reads and deadlines. Invalid, missing, partial, extra or oversized events fail the run. An unexpected exit fails the run. TERM grace expiry has a separate meaning: try KILL and still require actual exit. A timeout never establishes successful cancellation.

[test_experiment.py](test_experiment.py) checks every exact row, forged headers, prior effects, late stop, held-live release, signal ordering, protocol errors and cleanup. [check_mutations.py](check_mutations.py) tries two incorrect copies: ignore parent-stop requests, and erase earlier effects after stopping. Both must be detected. No faulty variant is presented as a product implementation.

## Limits and supported engineering check

The worker is deliberately paused at a barrier. Therefore this experiment does not measure racing with an already executing instruction, stop latency, CPU starvation, or arbitrary worker cooperation. It proves the recorded lifecycle/byte behavior for this small protocol, not a secure supervisor implementation.

Stopping one child does not cancel grandchildren, already queued remote actions or work in another service. It does not undo file writes. The SIGKILL control establishes termination of this owned child only. Parent compromise, same-user interference, persistent crashes and production containment are outside scope.

For an agent system whose stop control must not depend on model agreement, route the authorized stop to the trusted worker owner, end the owned process and verify exit. Test with a worker that ignores text, a held-but-live control and an already-completed-effect case; handle descendant and remote work separately.
