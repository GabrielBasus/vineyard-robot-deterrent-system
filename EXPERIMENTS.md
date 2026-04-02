# Experiment Runner Guide

This repo includes two experiment runners:

- `run_24h_experiment.py` (sequential, baseline/stable)
- `run_24h_experiment_parallel.py` (multiprocessing, faster)
- `demo_live_day_vineyard.py` (single-file, audience-friendly visual demo)

The first two are designed for 24-hour simulated vineyard experiments and export CSVs for thesis analysis.
The demo script is for live visualization and presentation.

## Thesis Staged Workflow Checklist

- [ ] Stage 1, model calibration: `python run_sestpp_calibration_sweep.py`
- [ ] Stage 2, field divergence lab: `python compare_field_divergence_lab.py --config configs/compare_field_divergence_lab.yaml`
- [ ] Stage 3, field divergence confirm: `python run_field_divergence_confirm_lab.py --config configs/run_field_divergence_confirm_lab.yaml`
- [ ] Stage 4, planner / assignment tuning: `python run_assignment_tuning_sweep_lab.py --config configs/run_assignment_tuning_sweep_lab.yaml`
- [ ] Stage 5, assignment-method comparison if still needed: `python run_assignment_method_comparison_lab.py --with-smoke-check` then `python plot_assignment_method_comparison_lab.py`
- [ ] Stage 6, robot scaling / long-horizon confirmation: `python run_robot_scaling_experiment.py --profile fast`
- Use the README written into each stage output directory to decide whether the next stage is justified.
- The concise thesis-methods version of this order is in `EXPERIMENT_EXECUTION_ORDER.md`.

## Requirements

- Python 3.10+
- Install project dependencies (at minimum: `numpy`, `pandas`, `matplotlib`, `scipy` if used in your env)

From the repo root:

```powershell
python -m py_compile run_24h_experiment.py run_24h_experiment_parallel.py
```

## 1) Sequential Runner (Recommended First)

Run:

```powershell
python run_24h_experiment.py
```

Outputs:

- `baseline_comparison_24h_sweep.csv`
- `baseline_runs_24h_sweep.csv`
- `experiment_manifest_24h_sweep.csv`
- `thesis_summary_24h_sweep.csv`
- `thesis_summary_24h_sweep.md`

Use this when you want a single stable run with built-in thesis summary artifacts.

## 2) Parallel Runner (Faster Sweeps)

### Fast profile (screening)

```powershell
python run_24h_experiment_parallel.py --profile fast --max-workers 12
```

### Final profile (higher fidelity)

```powershell
python run_24h_experiment_parallel.py --profile final --max-workers 8
```

### Quick smoke test

```powershell
python run_24h_experiment_parallel.py --profile fast --limit-settings 4 --num-runs 2
```

### Useful CLI options

- `--profile fast|final`
- `--max-workers <int>`
- `--num-runs <int>`
- `--seed-start <int>`
- `--dt <float>`
- `--nx <int>`
- `--ny <int>`
- `--limit-settings <int>`

Parallel outputs:

- Fast profile (`--profile fast`)
  - `baseline_comparison_24h_sweep_parallel_fast.csv`
  - `baseline_runs_24h_sweep_parallel_fast.csv`
  - `experiment_manifest_24h_sweep_parallel_fast.csv`
  - `thesis_summary_24h_sweep_parallel_fast.csv`
  - `thesis_summary_24h_sweep_parallel_fast.md`
- Final profile (`--profile final`, default)
  - `baseline_comparison_24h_sweep_parallel.csv`
  - `baseline_runs_24h_sweep_parallel.csv`
  - `experiment_manifest_24h_sweep_parallel.csv`
  - `thesis_summary_24h_sweep_parallel.csv`
  - `thesis_summary_24h_sweep_parallel.md`

## Running Suggestion

1. Run fast profile to identify promising parameter regions.
2. Run final profile for selected settings (or full final sweep).
3. Report:
   - per-run metrics from `baseline_runs...csv`
   - mean/variance comparisons from `baseline_comparison...csv`
   - experiment configuration traceability from `experiment_manifest...csv`
   - final meeting-ready summary from `thesis_summary_24h_sweep.*` (sequential) or `thesis_summary_24h_sweep_parallel.*` (parallel)

## Reproducibility

- Keep `seed_start` fixed for comparable reruns.
- Commit experiment scripts and CSV outputs (or archive outputs with commit hash).
- Save the manifest CSV with every run for exact parameter traceability.

## 3) Live Demo Script (Presentation Mode)

Run:

```powershell
python demo_live_day_vineyard.py
```

What it does:

- Runs a full 24h simulated day in a live visualization.
- Uses low-pressure ground-truth defaults for a readable non-technical demo.
- Shows separate visuals for:
  - ground truth birds (green X),
  - detections (red X),
  - active deterring tasks (orange circles),
  - active patrol tasks (blue diamonds),
  - completed tasks (gray dots).

Useful options:

```powershell
# faster-than-realtime playback
python demo_live_day_vineyard.py --sim-speed 30

# custom map and robot marker size
python demo_live_day_vineyard.py --W 500 --H 500 --robot-radius-m 0.9
```

Notes:

- `--sim-speed 1.0` is real-time (default).
- Use experiment runners for CSV-based analysis; use demo script for presentations.
