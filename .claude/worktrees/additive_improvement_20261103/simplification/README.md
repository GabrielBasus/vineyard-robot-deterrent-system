# Simplification Stages

This folder is the isolated workspace for testing the thesis system from its simplest useful state and then adding control layers back one family at a time.

The goal is not to replace the main simulator. It is to give you a clean, reproducible path for answering:

- what the core thesis system does without later planner protections,
- which added controls actually help,
- which layer reintroduces a failure mode.

## Stage Order

1. `s0_simple_tasks_core`
   Uses [`DeterrentSystem_simple_tasks.py`](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/DeterrentSystem_simple_tasks.py), which already exists in the repo as the simplest end-to-end task-management branch.
2. `s1_main_core`
   Switches back to the main runtime but keeps only the core thesis pieces: zone partitioning, intervention-aware SESTPP, hotspot task generation, basic dispatch, and heuristic preventive admission.
3. `s1_risk_open_core`
   Keeps the same stripped-down main runtime as `s1_main_core`, but fixes the heuristic preventive risk threshold at `0.0` so the preventive branch can actually be exercised and debugged.
4. `s1_capacity_aware_selection_core`
   Keeps the risk-open core, but adds a capacity-aware greedy selection stage between task extraction and assignment.
5. `s2_direct_conflict`
   Adds only direct-detection conflict protection.
6. `s3_persistence`
   Adds only preventive persistence and lock behavior.
7. `s4_capacity_budget`
   Adds budget, capacity, cycle-cap, and busy-robot throttling.
8. `s5_current_thesis_profile`
   Runs the current thesis-facing planner profile with frozen calibration.

## How To Run

List stages:

```powershell
python -m simplification.run_stage --list
```

Run the simplest stage:

```powershell
python -m simplification.run_stage --stage s0_simple_tasks_core --num-runs 1 --t-end 1800
```

Run the first three stages with the same seeds and horizon:

```powershell
python -m simplification.run_stage --stage s0_simple_tasks_core --stage s1_main_core --stage s2_direct_conflict --num-runs 3 --t-end 3600
```

Run the full staged ladder:

```powershell
python -m simplification.run_stage --all --num-runs 3 --t-end 3600
```

Aggregate every completed stage into one comparison table:

```powershell
python -m simplification.compare_stages
```

Choose which completed stage should count as the current full/main reference:

```powershell
python -m simplification.compare_stages --main-stage s5_current_thesis_profile
```

Run a full multi-worker performance comparison and generate next-step recommendations:

```powershell
python -m simplification.performance_compare --all --num-runs 3 --t-end 3600 --max-workers 4
```

Run a focused risk-gate sweep on top of `s1_main_core`:

```powershell
python -m simplification.risk_gate_sweep --num-runs 3 --t-end 3600 --max-workers 4
```

Run a temporal analysis on completed stage outputs to see how gains change with horizon length and across consecutive time bouts:

```powershell
python -m simplification.temporal_analysis --main-stage s5_current_thesis_profile
```

Run a matched multi-horizon sweep to see which stage holds up best as simulation length increases:

```powershell
python -m simplification.horizon_sweep --stage s1_risk_open_core --stage s5_current_thesis_profile --time-horizons-h 2,4,6 --num-runs 3 --max-workers 4
```

Outputs are written to `results/simplification/<stage>/`:

- `stage_manifest.json`: exact stage definition and run settings
- `comparison.csv`: baseline summary table from `run_baseline_suite`
- `comparison_over_time.csv`: time-series summary table written by the baseline runner
- `comparison_preview.txt`: small text preview of the comparison table

Cross-stage outputs written to `results/simplification/`:

- `stage_comparison.csv`: one summary row per simplification stage
- `stage_baseline_long.csv`: concatenated per-stage baseline summaries
- `stage_over_time_long.csv`: concatenated per-stage time-series summaries
- `stage_comparison.md`: compact human-readable summary with `proposed vs prediction_only`, `proposed vs reactive`, and `stage vs main/current` comparisons
- `performance_runtime.csv`: wall-clock runtime per stage for the parallel performance run
- `performance_compare_manifest.json`: exact settings, resolved main stage, and per-stage run status
- `performance_next_steps.md`: concrete recommendations based on exposure, preventive yield, communication, and planner-rejection deltas
- `temporal_horizon_summary.csv`: one summary row per stage describing final, best, and trend-over-time horizon metrics
- `temporal_horizon_long.csv`: cumulative horizon-by-horizon comparisons for each stage
- `temporal_bout_long.csv`: windowed time-bout comparisons for each stage
- `temporal_bout_summary.csv`: same stage summary table written for convenience under the bout-focused name
- `temporal_analysis.md`: compact interpretation of where gains appear, fade, or reverse over time
- `horizon_sweep_runtime.csv`: wall-clock runtime per stage x horizon job
- `horizon_sweep_summary.csv`: one summary row per stage x horizon, including birds-deterred percentage
- `horizon_sweep_baseline_long.csv`: concatenated baseline summary rows for every completed stage x horizon run
- `horizon_sweep_manifest.json`: exact sweep settings and per-job run status
- `horizon_sweep.md`: compact recommendation report for which stage remains strongest as horizon grows

Risk-gate sweep outputs written to `results/simplification/risk_gate_sweep/`:

- `risk_gate_runtime.csv`: wall-clock runtime per risk-gate variant
- `risk_gate_summary.csv`: one row per threshold/scale variant with candidate, rejection, generation, acceptance, and completion metrics
- `risk_gate_long.csv`: concatenated baseline summary rows for every variant
- `risk_gate_sweep.md`: focused interpretation of whether threshold/scale changes open the preventive branch
- `risk_gate_sweep_manifest.json`: exact sweep settings and per-variant run status

## What To Look For

When a stage changes behavior a lot, compare these first:

- value-weighted exposure
- response time
- communication increase
- model-scored preventive accepted/completed counts
- planner rejection counts

That usually tells you whether a newly added control layer is fixing a real bottleneck or just adding another filter.
