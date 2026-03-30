# Core Regression References

These files freeze deterministic, seed-locked reference outputs for the core production simulator.

Primary harness:
- `run_core_regression_check.py`

Default reference:
- `core_default_proposed_seed123_t10_dt1.json`

Typical usage:

```powershell
python run_core_regression_check.py
```

Refresh the frozen reference only when you intentionally accept a behavior change:

```powershell
python run_core_regression_check.py --write-reference
```

Notes:
- The harness disables telemetry during the regression run to avoid file-system side effects.
- The reference captures a compact but behavior-sensitive fingerprint:
  - per-frame poses / goals / robot states
  - active and completed task ids
  - motion commands
  - selected stage counters
  - final `metrics_compact`
