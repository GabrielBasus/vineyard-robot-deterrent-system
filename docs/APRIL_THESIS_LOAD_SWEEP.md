# April Thesis Load Sweep

## Purpose

This package sets up the reserved-capacity load-sweep experiment using the **core system described in** [AprilThesisGabriel.md](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/docs/AprilThesisGabriel.md).

It intentionally uses the April-style policy family:

- `unc`
- `res_0p25`
- `res_rand_0p25`

and does **not** use the later confidence-weighted, deferred-action, centralized, or risk-adjusted variants.

It also disables model-scored preventive deterring. Predictive work is patrol-based, and deterring actions are created only from direct detections. This keeps the experiment aligned with the April thesis framing:

```text
predictive field -> patrol target -> detection -> reactive deterring task
```

## Why This Matches The April Thesis

The April document frames the thesis around:

- a mixed-greedy unconstrained baseline `unc`
- a hard reserved-capacity policy `res(ρ)`
- a random reservation ablation `res-rand(ρ)`
- a load-regime experiment where robot count changes and the predictive infrastructure stays fixed

This setup follows that framing directly.

## Load Points

The configured robot counts are:

- `6` robots: low-load anchor
- `4` robots: nominal / moderate load probe
- `3` robots: saturation probe
- `2` robots: overload probe

This is slightly broader than the advisor email because it keeps both `3` and `2` robots instead of choosing only one saturation point.

## Policy Set

- `unc`
  - dispatch policy `unc`
  - mixed-greedy unconstrained baseline with reactive urgency override
- `res_0p25`
  - planner profile `res_0p25`
  - fixed reservation fraction `ρ = 0.25`
  - predictive tasks selected by utility
- `res_rand_0p25`
  - planner profile `res_rand_0p25`
  - same reservation mechanism as `res_0p25`
  - predictive tasks selected uniformly at random

## Shared Scenario Assumptions

All configs hold fixed:

- same field geometry
- same 24-hour duration
- same warmup
- same predictive infrastructure
- model-scored preventive deterring disabled
- same `thesis_calibrated_selective_proposed` scenario baseline

Only the robot count changes.

## Metrics

### Primary metrics

- `native_value_weighted_exposure`
- `native_reactive_mean_response_time_s`
- `total_robot_distance_m`
- `native_reactive_completed_fraction`
- `native_predictive_completed_fraction`

### Supporting diagnostics

- `native_reactive_generated_total`
- `native_predictive_generated_total`
- `native_reactive_admitted_total`
- `native_predictive_admitted_total`
- `native_reactive_completed_total`
- `native_predictive_completed_total`
- `native_reactive_load_factor_estimate`
- `native_robot_idle_fraction_mean`
- `native_robot_reactive_fraction_mean`
- `native_robot_predictive_fraction_mean`
- `native_urgent_reactive_override_total`

## Config Files

### Pilot: 2 seeds each

- [april_thesis_load_sweep_pilot_6r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_pilot_6r.json)
- [april_thesis_load_sweep_pilot_4r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_pilot_4r.json)
- [april_thesis_load_sweep_pilot_3r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_pilot_3r.json)
- [april_thesis_load_sweep_pilot_2r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_pilot_2r.json)

### Full: 5 seeds each

- [april_thesis_load_sweep_full_6r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_full_6r.json)
- [april_thesis_load_sweep_full_4r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_full_4r.json)
- [april_thesis_load_sweep_full_3r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_full_3r.json)
- [april_thesis_load_sweep_full_2r.json](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/testbench/april_thesis_load_sweep_full_2r.json)

## Runner

Use:

- [run_april_thesis_load_sweep.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/experiments/run_april_thesis_load_sweep.py)

### Pilot sweep

```powershell
python -m experiments.run_april_thesis_load_sweep --max-workers 3
```

### Full sweep

```powershell
python -m experiments.run_april_thesis_load_sweep --full --max-workers 3
```

### Subset example

```powershell
python -m experiments.run_april_thesis_load_sweep --robot-counts 6 3 --max-workers 3
```

## Intended Interpretation

This package is meant to answer the exact April-thesis question:

1. Does `res_0p25` beat `unc` as load rises?
2. If it does, does `res_0p25` also beat `res_rand_0p25`?

If the answer to (1) is no at all tested robot counts, the April reservation hypothesis is weakened.
If the answer to (1) is yes only at `3` or `2` robots, then the regime boundary is simply higher.
If the answer to (1) is yes and the answer to (2) is also yes, then predictive scoring is adding value beyond reservation alone.
