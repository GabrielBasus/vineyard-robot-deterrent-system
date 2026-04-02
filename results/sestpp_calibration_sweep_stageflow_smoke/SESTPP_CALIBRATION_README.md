# SESTPP Calibration Sweep

## Thesis Workflow Stage
- Stage 1 of 6: Model Calibration
- Runner: `run_sestpp_calibration_sweep.py`
- Depends on: None
- Relevance: required for the staged thesis evaluation flow.

## Stage Question
- Which intervention-aware SESTPP hyperparameters best calibrate the proposed field before any planner conclusions are made?

## Metrics That Matter
- `proposed_field_logloss_mean / proposed_field_brier_mean / proposed_nll_mean`: Primary calibration errors for the proposed model; lower is better.
- `logloss_improvement_pct_mean / brier_improvement_pct_mean / nll_improvement_pct_mean`: Matched-seed improvement over prediction-only; positive values indicate a better calibrated proposed field.
- `*_ci95`: Ranking stability across seeds; wide intervals mean the selected configuration is not yet defensible.

## What Counts As Failure
- No configuration shows stable paired improvement over prediction-only on the main calibration metrics.
- The nominal winner still worsens log loss, Brier score, or NLL once CI95 uncertainty is considered.

## Key Outputs
- Per-run CSV: `sestpp_calibration_sweep_per_run.csv`
- Summary CSV: `sestpp_calibration_sweep_summary.csv`
- Ranking CSV: `sestpp_calibration_sweep_ranking.csv`
- Manifest: `sestpp_calibration_sweep_manifest.json`
- Ranking plot: `sestpp_calibration_sweep_tradeoff.png`

## Current Best-Ranked Config
- Config id: `C01`
- Proposed field log loss mean +/- CI95: 5.5507 +/- 0.000e+00
- Proposed field Brier mean +/- CI95: 0.4694 +/- 0.000e+00
- Proposed NLL mean +/- CI95: 373662.3437 +/- 0.000e+00
- NLL improvement mean: 9.3026%

## Experiment Execution Order

1. **Model Calibration** (`run_sestpp_calibration_sweep.py`): Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.
2. **Field Divergence Lab** (`compare_field_divergence_lab.py`): Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.
3. **Field Divergence Confirm** (`run_field_divergence_confirm_lab.py`): Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.
4. **Planner / Assignment Tuning** (`run_assignment_tuning_sweep_lab.py`): Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.
5. **Assignment-Method Comparison** (`run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`): Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep. Optional stage.
6. **Robot Scaling / Long-Horizon Confirmation** (`run_robot_scaling_experiment.py`): Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.
