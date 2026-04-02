# Reproduce This Checkpoint

## Inputs copied into this folder
- `baseline_comparison_24h_sweep_parallel_fast_planner_tune_s2.csv`
- `baseline_comparison_24h_sweep_parallel_fast_planner_tune_s3.csv`
- `baseline_runs_24h_sweep_parallel_fast_planner_tune_s2.csv`
- `baseline_runs_24h_sweep_parallel_fast_planner_tune_s3.csv`
- `experiment_manifest_24h_sweep_parallel_fast_planner_tune_s2.csv`
- `experiment_manifest_24h_sweep_parallel_fast_planner_tune_s3.csv`
- `parameter_comparison_ground_truth_vs_proposed.csv`
- `planner_tune_improvement_summary.csv`
- `thesis_summary_24h_sweep_parallel_fast_planner_tune.csv`
- `thesis_summary_24h_sweep_parallel_fast_planner_tune_s2.csv`
- `thesis_summary_24h_sweep_parallel_fast_planner_tune_s3.csv`

## Core commands used
- `python -m py_compile DeterrentSystem.py TaskGenerator.py run_24h_experiment_parallel.py`
- `python diagnostic_compare_systems.py --T-end 10800 --outdir results\diagnostics_planner_dispatch_verify_10800 --seed 123`
- `python run_24h_experiment_parallel.py --profile fast --tune-preset planner_tune --scenario-scope s23 --num-runs 1 --limit-settings 2 --max-workers 4 --time-horizons-h 6 --seed-start 5000`

## Note
- The 6h run is a smoke test and should not be used as final thesis evidence.