# Adaptive Capacity-Aware Reservation

## Purpose

This change adds a new thesis dispatch mode, `res-adaptive`, to address the main failure mode observed in the earlier reserved-capacity policies:

- hard `res` reserved predictive work too aggressively
- `res-soft` reduced that effect under reactive pressure, but it could still claim predictive work while reactive detections had already aged significantly

The adaptive mode keeps the capacity-aware framing, but makes the predictive claim depend on both:

- current reactive competition
- current reactive waiting age

## Compatibility

All existing modes remain unchanged:

- `unc`
- `react`
- `res`
- `res-soft`

The new mode is additive:

- `res-adaptive`

Existing configs and profiles continue to work without modification.

## New Equation

The effective reservation target is now:

```text
rho_eff = rho / (1 + alpha * reactive_pressure + beta * reactive_age_norm)
```

Where:

- `rho` is `reservation_fraction`
- `alpha` is `reservation_softening_alpha`
- `beta` is `reservation_age_softening_beta`
- `reactive_pressure = reactive_task_count / (reactive_task_count + predictive_task_count)`
- `reactive_age_norm = max_reactive_age_s / reactive_override_slack_s`

The predictive claim for `res-adaptive` is allowed only when:

```text
predictive_share < rho_eff
and reactive_age_norm < reservation_age_gate
```

This means the policy now softens reservation in two ways:

1. It shrinks the predictive target as reactive competition rises.
2. It stops claiming predictive work once reactive detections have aged too close to the override horizon.

## New Parameters

The following new runtime parameters were added:

- `reservation_age_softening_beta`
- `reservation_age_gate`

Recommended starting values in the new planner profile:

- `reservation_softening_alpha = 2.0`
- `reservation_age_softening_beta = 2.0`
- `reservation_age_gate = 0.5`

These are exposed in structured outputs and config summaries.

## New Planner Profile

A new profile alias was added:

- `res_adaptive_0p25`

Canonical profile id:

- `thesis_dispatch_res_adaptive_0p25`

It resolves to:

```python
{
    "dispatch_policy": "res-adaptive",
    "reservation_fraction": 0.25,
    "reservation_window_s": 600.0,
    "reactive_override_slack_s": 90.0,
    "reservation_softening_alpha": 2.0,
    "reservation_age_softening_beta": 2.0,
    "reservation_age_gate": 0.5,
    "predictive_selection_policy": "utility",
}
```

## Files Changed

- [DeterrentSystem.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/DeterrentSystem.py)
  Added `res-adaptive`, the age-aware reservation equation, new runtime parameters, and config/metric plumbing.
- [planner_profiles.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/planner_profiles.py)
  Added the adaptive thesis profile alias.
- [system_structure.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/system_structure.py)
  Added the new adaptive parameters to production config and structured outputs.
- [tests/test_thesis_dispatch_reframe.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_thesis_dispatch_reframe.py)
  Added acceptance, behavior, and runtime-export tests for the adaptive mode.
- [tests/test_planner_profiles.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_planner_profiles.py)
  Added planner profile alias coverage for `res_adaptive_0p25`.

## How To Compare It

Compare these four modes directly:

- `unc`
- `res`
- `res-soft`
- `res-adaptive`

Example runtime kwargs:

```python
dispatch_policy="res-adaptive"
reservation_fraction=0.25
reservation_softening_alpha=2.0
reservation_age_softening_beta=2.0
reservation_age_gate=0.5
```

Or use:

```python
planner_profile="res_adaptive_0p25"
```

## Tests

Focused unit/runtime checks:

```powershell
python -m unittest tests.test_thesis_dispatch_reframe tests.test_planner_profiles
```

If you want a broader regression pass:

```powershell
python -m unittest tests.test_action_schema tests.test_dispatch_priority_ordering tests.test_tracking_state_exports tests.test_thesis_dispatch_reframe tests.test_planner_profiles
```

## Interpretation

This change does not prove the adaptive policy is better than `unc`.

What it does provide is a cleaner comparison:

- hard threshold reservation
- load-softened reservation
- load-and-age adaptive reservation

That lets you explain whether the earlier negative result came from the capacity-aware idea itself, or from the original reservation equation being too aggressive.
