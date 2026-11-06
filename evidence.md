# Exact process evidence

These are 13 chosen process schedules, not model trials. At the acknowledged barrier the worker cannot write until the parent sends STEP. Holding alone also leaves the file unchanged; parent stop additionally ends the worker, as verified by its exit status. Earlier completed writes remain.

| Schedule | Mode | File bytes after exit | Observed exit | KILL escalation |
|---|---|---|---:|---|
| normal | text_only | `FIRST\nSECOND\n` | 0 | False |
| normal | parent_stop | `FIRST\nSECOND\n` | 0 | False |
| stop_before | text_only | `FIRST\nSECOND\n` | 0 | False |
| stop_before | parent_stop | `(absent)` | -15 | False |
| forged_header | text_only | `FIRST\nSECOND\n` | 0 | False |
| forged_header | parent_stop | `FIRST\nSECOND\n` | 0 | False |
| stop_after_first | text_only | `FIRST\nSECOND\n` | 0 | False |
| stop_after_first | parent_stop | `FIRST\n` | -15 | False |
| stop_after_both | text_only | `FIRST\nSECOND\n` | 0 | False |
| stop_after_both | parent_stop | `FIRST\nSECOND\n` | -15 | False |
| ignore_term | text_only | `FIRST\nSECOND\n` | 0 | False |
| ignore_term | parent_stop | `(absent)` | -9 | True |
| hold_then_release | hold_control | `FIRST\nSECOND\n` | 0 | False |

Exit 0 means normal completion; -15 means SIGTERM; -9 means SIGKILL on the validated POSIX host.
The hold control has no bytes and a live worker before release, then FIRST and SECOND after release.
Protocol timeouts fail the run. TERM grace expiry is only an escalation trigger, not evidence of stopped work.
No latency, attack prevalence, model compliance, child-tree or remote-action cancellation is measured.
