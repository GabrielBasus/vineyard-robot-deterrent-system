# Experiment Runner Guide

This repo includes these maintained experiment runners:

- `experiments/run_24h_experiment.py` (sequential, baseline/stable)
- `experiments/run_24h_experiment_parallel.py` (multiprocessing, faster)
- `demos/demo_live_day_vineyard.py` (single-file, audience-friendly visual demo)
- `experiments/run_habituation_stl_production_ladder.py` (production B0-B5 habituation/STL ladder)
- `experiments/run_habituation_stl_fair_tuning.py` (equal-budget tuning plus held-out confirmation for B1-B5 and dispatcher-matched B5)
- `experiments/diagnose_habituation_stl_production.py` (short-run STL/habituation diagnostic)
- `experiments/summarize_habituation_stl_ladder.py` (paired CSV summaries and `THESIS_RESULTS_SUMMARY.md`)

The first two are designed for 24-hour simulated vineyard experiments and export CSVs for thesis analysis.
The demo script is for live visualization and presentation.

For the April thesis dispatch reframe, use `docs/THESIS_DISPATCH_RUNBOOK.md` for the dedicated demo configs, batch testbench configs, and thesis dispatch suite commands.

## Thesis Staged Workflow Checklist

- [ ] Stage 1, model calibration: `python -m experiments.run_sestpp_calibration_sweep`
- [ ] Stage 2, field divergence lab: `python -m experiments.compare_field_divergence_lab --config configs/compare_field_divergence_lab.yaml`
- [ ] Stage 3, field divergence confirm: `python -m experiments.run_field_divergence_confirm_lab --config configs/run_field_divergence_confirm_lab.yaml`
- [ ] Stage 4, planner / assignment tuning: `python -m experiments.run_assignment_tuning_sweep_lab --config configs/run_assignment_tuning_sweep_lab.yaml`
- [ ] Stage 5, assignment-method comparison if still needed: `python -m experiments.run_assignment_method_comparison_lab --with-smoke-check` then `python -m plots.plot_assignment_method_comparison_lab`
- [ ] Stage 6, robot scaling / long-horizon confirmation: `python -m experiments.run_robot_scaling_experiment --profile fast`
- [ ] STL addendum, habituation-aware value: run the B0-B4 ladder, B1/B2/B3/B4 confirmatory batch, and B5 supplemental cue-rotation baseline documented below.
- Use the README written into each stage output directory to decide whether the next stage is justified.
- The concise thesis-methods version of this order is in `docs/EXPERIMENT_EXECUTION_ORDER.md`.


## Habituation-Aware STL Experiments

Use these runners for the proposal STL integration. They do not modify command runners or dispatcher commands; they select existing simulator kwargs such as `predictive_utility_mode="stl_robustness"`, `stl_active_clauses`, and `enable_habituation`.

### B0-B4 revised ladder

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_revised_b0_b4_900s_10seed --duration-s 900 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --systems B0_reactive B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue --max-workers 2
```

### Revised confirmatory B1/B2/B3/B4 batch

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --reservation-fraction 0.25 --mu-true 2e-05 --deterrence-beta-scale 4.0 --deterrence-sigma-scale 4.0 --deterrence-omega-scale 3.0 --habituation-kappa 0.5 --systems B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue --max-workers 4
```

### Supplemental B5 cue-rotation baseline

Run only B5 and merge it with the existing B1-B4 raw rows:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --reservation-fraction 0.25 --mu-true 2e-05 --deterrence-beta-scale 4.0 --deterrence-sigma-scale 4.0 --deterrence-omega-scale 3.0 --habituation-kappa 0.5 --systems B5_greedy_habcue --merge-existing-raw --max-workers 4
```

### Model-mismatch robustness check

This run keeps the planner's assumed habituation model at the proposal default while making truth recover faster, generalize habituation across cues, and use an additive drop after each cue instead of the proposal multiplicative update:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_model_mismatch_b1_b5_1800s_10seed --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --reservation-fraction 0.25 --mu-true 2e-05 --deterrence-beta-scale 4.0 --deterrence-sigma-scale 4.0 --deterrence-omega-scale 3.0 --habituation-kappa 0.5 --truth-habituation-t-rec-s 900 --truth-habituation-gamma 0.35 --truth-habituation-update-model additive_drop --planner-habituation-t-rec-s 1800 --planner-habituation-gamma 0.0 --planner-habituation-update-model multiplicative --systems B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue B5_greedy_habcue --max-workers 4
```

### Summarize a ladder run

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\summarize_habituation_stl_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed
```

Primary outputs:

- `ladder_manifest.json`
- raw per-run JSON under `raw/`
- `THESIS_RESULTS_SUMMARY.md` for thesis-facing summaries

Primary metrics:

- `value_weighted_exposure`
- `mean_response_time_s`
- `predictive_completion_ratio`
- `predictive_expired_fraction`
- `predictive_deadline_feasible_fraction`
- `travel_distance_total`
- `tasks_per_unit_distance`
- `truth_suppression_rate`
- `truth_suppression_effect_sum`
- `habituation_eta_at_apply_mean`
- `habituation_variety_index`
- `stl_robustness_global_mean`
- `stl_robustness_exp`, `stl_robustness_cov`, `stl_robustness_hab`

Current result summary: `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`.

### Fair equal-budget tuning and held-out confirmation

Use this when the thesis question is whether B4 still wins after each baseline receives comparable tuning effort. The runner tunes each requested system on one seed set, freezes the best setting per system, then confirms those frozen winners on held-out seeds. It also adds `B5_res_habcue_multicue`, a reserved-dispatch non-STL cue-rotation baseline, so B4 can be compared against cue rotation under the same dispatcher class.

Dry-run the protocol first:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_fair_tuning.py --dry-run --phase tune --outdir results\testbench\habituation_stl_fair_tuning_dryrun --trial-budget 36
```

Run tuning only:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_fair_tuning.py --phase tune --outdir results\testbench\habituation_stl_fair_tuning --trial-budget 36 --tune-duration-s 900 --tune-num-runs 3 --tune-seed-start 100 --max-workers 4
```

Run held-out confirmation after tuning:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_fair_tuning.py --phase confirm --outdir results\testbench\habituation_stl_fair_tuning --confirm-duration-s 1800 --confirm-num-runs 10 --confirm-seed-start 125 --max-workers 4
```

Confirm-only mode reads `selected_configs.json` and reuses the saved scenario arguments from `tuning_protocol.json`. The command above only changes confirmation run controls such as duration, seed range, output path, and worker count.

Or run the full tune-and-confirm protocol in one command:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_fair_tuning.py --phase tune_confirm --outdir results\testbench\habituation_stl_fair_tuning --trial-budget 36 --tune-duration-s 900 --tune-num-runs 3 --tune-seed-start 100 --confirm-duration-s 1800 --confirm-num-runs 10 --confirm-seed-start 125 --max-workers 4
```

Use `--trial-budget 12` only as a screening run. The thesis-facing fair run should use `--trial-budget 36`, which exhausts the common grid of budget, score margin, max ETA, and horizon settings. Reserved baselines then receive a balanced reservation-fraction schedule across that full common grid.

Primary fair-tuning outputs:

- `tuning_protocol.json`
- `tuning_trials.csv`
- `tuning_summary_by_trial.csv`
- `selected_configs.json`
- `confirm_per_run_metrics.csv`
- `confirm_summary_by_system.csv`
- `confirm_comparisons.csv`
- `FAIR_TUNING_PROTOCOL.md`

Fairness controls:

- Every baseline receives the same common grid over predictive budget, score margin, max ETA, and horizon.
- Fixed-cue baselines B1/B2/B3 tune the fixed cue over `formation`, `laser`, and `biosonic`; the selected cue is frozen into confirmation.
- Reserved baselines B2/B3/B4/B5-res tune `rho` over `0.10`, `0.25`, and `0.40` with a balanced schedule across the common grid.
- Multi-cue baselines B4/B5 keep automatic cue selection, as required by their mechanism definition.
- Final thesis claims must use held-out confirmation seeds, not tuning seeds.

Interpretation rule: cite this as the fair comparison because every tuned baseline receives the same trial budget and final claims use held-out seeds only. Keep the STL mission thresholds fixed unless the thesis explicitly reframes them as tunable design variables.

### Fair-tuned sensitivity sweeps

After fair tuning has produced `selected_configs.json`, use the frozen winners for sensitivity checks. These sweeps vary only the named stress variable while keeping each baseline's tuned settings fixed.

Kappa response curve:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_kappa_sweep.py --outdir results\testbench\habituation_stl_kappa_sweep_fair_tuned --selection-path results\testbench\habituation_stl_fair_tuning\selected_configs.json --kappa-values 0 0.10 0.25 0.40 0.50 0.65 0.80 --mu-true 2e-05 --duration-s 1800 --num-runs 10 --seed-start 125 --nx 60 --ny 48 --nrobots 4 --systems B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue B5_greedy_habcue B5_res_habcue_multicue --max-workers 4
```

Load-regime sweep:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_load_sweep.py --outdir results\testbench\habituation_stl_load_sweep_fair_tuned --selection-path results\testbench\habituation_stl_fair_tuning\selected_configs.json --mu-values 1e-05 1.5e-05 2e-05 2.5e-05 3e-05 --duration-s 1800 --num-runs 10 --seed-start 125 --nx 60 --ny 48 --nrobots 4 --habituation-kappa 0.5 --systems B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue B5_greedy_habcue B5_res_habcue_multicue --max-workers 4
```

Both summary CSVs include exposure, response time, predictive completion/expiration, deadline feasibility, travel distance, STL robustness, eta-bar at apply, variety index, and realized suppression effect.

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
python -m experiments.run_24h_experiment
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
python -m experiments.run_24h_experiment_parallel --profile fast --max-workers 12
```

### Final profile (higher fidelity)

```powershell
python -m experiments.run_24h_experiment_parallel --profile final --max-workers 8
```

### Quick smoke test

```powershell
python -m experiments.run_24h_experiment_parallel --profile fast --limit-settings 4 --num-runs 2
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
python -m demos.demo_live_day_vineyard
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
python -m demos.demo_live_day_vineyard --sim-speed 30

# custom map and robot marker size
python -m demos.demo_live_day_vineyard --W 500 --H 500 --robot-radius-m 0.9
```

Notes:

- `--sim-speed 1.0` is real-time (default).
- Use experiment runners for CSV-based analysis; use demo script for presentations.
