# Thesis Load Sweep Plan

## Goal

Test the reservation hypothesis in the load regimes where it could actually differentiate from mixed-greedy `unc`.

The immediate experiment compares:

- `unc`
- `res_0p25`
- `res_rand_0p25`

across:

- `6` robots
- `4` robots
- `3` robots
- `2` robots

The sweep uses the same field, duration, timing, and predictive infrastructure as the prior nominal 24-hour runs. Only robot count changes.

## Why This Pilot

This is the cleanest first pilot because:

1. `res_0p25` is the canonical reserved-capacity profile.
2. `res_rand_0p25` is already implemented as a matched random-selection ablation.
3. The pairing directly tests:
   - whether reservation helps as load rises
   - whether predictive scoring outperforms random once reservation matters

## Policy Set

### Baselines and pilot policies

- `unc`
  - true mixed-greedy unconstrained baseline with reactive urgency override
- `res_0p25`
  - hard reserved-capacity policy with `reservation_fraction = 0.25`
  - predictive tasks chosen by utility
- `res_rand_0p25`
  - same reservation mechanism as `res_0p25`
  - predictive choice randomized instead of utility-ranked

## Robot-count conditions

- `6` robots
  - low-load anchor
- `4` robots
  - moderate load
- `3` robots
  - near saturation
- `2` robots
  - overload

## Metrics to compare

### Primary metrics

- `native_value_weighted_exposure`
- `native_reactive_mean_response_time_s`
- `total_robot_distance_m`
- `native_reactive_completed_fraction`
- `native_predictive_completed_fraction`

### Supporting diagnostics

- `native_reactive_load_factor_estimate`
- `native_robot_idle_fraction_mean`
- `native_robot_predictive_fraction_mean`
- `native_urgent_reactive_override_total`
- `native_predictive_generated_total`
- `native_predictive_admitted_total`
- `native_predictive_completed_total`

## Ready-to-run pilot configs

- [thesis_load_sweep_pilot_6r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_pilot_6r.json)
- [thesis_load_sweep_pilot_4r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_pilot_4r.json)
- [thesis_load_sweep_pilot_3r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_pilot_3r.json)
- [thesis_load_sweep_pilot_2r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_pilot_2r.json)

Each pilot config uses:

- `2` seeds
- `86400 s` duration
- `21600 s` warmup
- same nominal predictive stack as the prior pipeline comparisons

## Ready-to-run full configs

- [thesis_load_sweep_full_6r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_full_6r.json)
- [thesis_load_sweep_full_4r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_full_4r.json)
- [thesis_load_sweep_full_3r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_full_3r.json)
- [thesis_load_sweep_full_2r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/thesis_load_sweep_full_2r.json)

Each full config uses:

- `5` seeds
- `86400 s` duration
- `21600 s` warmup

## Run commands

### Pilot

```powershell
python -m testbench.run_testbench --config testbench\thesis_load_sweep_pilot_6r.json --max-workers 3
python -m testbench.run_testbench --config testbench\thesis_load_sweep_pilot_4r.json --max-workers 3
python -m testbench.run_testbench --config testbench\thesis_load_sweep_pilot_3r.json --max-workers 3
python -m testbench.run_testbench --config testbench\thesis_load_sweep_pilot_2r.json --max-workers 3
```

### Full sweep

```powershell
python -m testbench.run_testbench --config testbench\thesis_load_sweep_full_6r.json --max-workers 3
python -m testbench.run_testbench --config testbench\thesis_load_sweep_full_4r.json --max-workers 3
python -m testbench.run_testbench --config testbench\thesis_load_sweep_full_3r.json --max-workers 3
python -m testbench.run_testbench --config testbench\thesis_load_sweep_full_2r.json --max-workers 3
```

## What to plot

Main plot:

- x-axis: realized `native_reactive_load_factor_estimate`
- y-axis: `native_value_weighted_exposure`
- one line each for `unc`, `res_0p25`, `res_rand_0p25`

Secondary plots:

- reactive completion fraction vs load factor
- reactive-only mean response time vs load factor
- predictive completion fraction vs load factor
- urgent reactive overrides vs load factor
- mean idle fraction vs load factor

## Reservation variants currently available

### Core reservation baselines

- `res_0p00`
  - reserved-capacity logic with zero reservation
- `res_0p10`
  - low reservation fraction
- `res_0p25`
  - nominal hard reservation fraction
- `res_0p40`
  - aggressive hard reservation fraction
- `res_rand_0p25`
  - same as `res_0p25`, but predictive selection is random

### Soft / adaptive reservation variants

- `res_soft_0p25`
  - reservation softens as reactive pressure rises
- `res_adaptive_0p25`
  - reservation softens with reactive pressure and reactive-task age
- `res_adaptive_leadtime_0p25`
  - adaptive reservation plus predictive future-event timing

### Feasibility / confidence variants

- `res_feasible_0p25`
  - predictive claims only if the task remains feasible
- `res_idle_feasible_0p25`
  - predictive claims only if the robot is idle, pressure is low, and the task is feasible
- `res_confidence_0p25`
  - predictive ranking uses a confidence-weighted score
- `res_idle_feasible_confidence_0p25`
  - combines idle/pressure/feasibility gating with confidence-weighted ranking
- `res_risk_adjusted_0p25`
  - predictive work treated as an optional investment with confidence/cost/opportunity-cost gating

### Later predictive-pipeline variants

- `res_time_score_0p25`
  - recomputes predictive deployment value at dispatch time
- `res_time_score_v2_0p25`
  - variant driven more directly by predicted delta-J
- `res_deferred_time_score_0p25`
  - defers action-mode resolution until dispatch time
- `res_centralized_global_0p25`
  - centralized predictive planning with one shared opportunity pool and soft zone assignment

## Recommended interpretation order

1. Run the pilot with `unc`, `res_0p25`, `res_rand_0p25`.
2. Check whether `native_reactive_load_factor_estimate` actually rises at `4`, `3`, and `2` robots.
3. If `res_0p25` starts to outperform `unc`, then reservation is being tested in the intended regime.
4. If `res_0p25` beats `res_rand_0p25`, then predictive scoring adds value beyond the reservation mechanism.
5. Only after that should you decide whether to substitute a stronger modern reservation variant such as `res_idle_feasible_confidence_0p25`.
