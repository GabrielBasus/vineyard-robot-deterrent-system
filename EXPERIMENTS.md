# Experiment Runner Guide

This repo includes two experiment runners:

- `run_24h_experiment.py` (sequential, baseline/stable)
- `run_24h_experiment_parallel.py` (multiprocessing, faster)

Both are designed for 24-hour simulated vineyard experiments and export CSVs for thesis analysis.

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

Parallel outputs (suffix depends on profile):

- `baseline_comparison_24h_sweep_parallel_fast.csv` or `_final.csv`
- `baseline_runs_24h_sweep_parallel_fast.csv` or `_final.csv`
- `experiment_manifest_24h_sweep_parallel_fast.csv` or `_final.csv`

## Suggested Thesis Workflow

1. Run fast profile to identify promising parameter regions.
2. Run final profile for selected settings (or full final sweep).
3. Report:
   - per-run metrics from `baseline_runs...csv`
   - mean/variance comparisons from `baseline_comparison...csv`
   - experiment configuration traceability from `experiment_manifest...csv`
   - final meeting-ready summary from `thesis_summary_24h_sweep.*` (sequential run)

## Performance Notes (i9-13900HX)

- Start with `--max-workers 8`, then test `12`.
- If system becomes memory/CPU saturated, reduce worker count.
- Keep visualization tools (animation/Streamlit) off during large sweeps.

## Reproducibility

- Keep `seed_start` fixed for comparable reruns.
- Commit experiment scripts and CSV outputs (or archive outputs with commit hash).
- Save the manifest CSV with every run for exact parameter traceability.
