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
- Prediction-only stage summary CSV: `sestpp_prediction_only_calibration_summary.csv`
- Proposed stage summary CSV: `sestpp_proposed_calibration_summary.csv`
- Joint pairing stage summary CSV: `sestpp_joint_calibration_summary.csv`
- Canonical per-run CSV: `sestpp_calibration_sweep_per_run.csv`
- Canonical summary CSV: `sestpp_calibration_sweep_summary.csv`
- Canonical ranking CSV: `sestpp_calibration_sweep_ranking.csv`
- Manifest: `sestpp_calibration_sweep_manifest.json`
- Ranking plot: `sestpp_calibration_sweep_tradeoff.png`
- Divergence-rerank summary CSV: `sestpp_divergence_rerank_summary.csv`

## Best Prediction-Only Config
- Config id: `P01`
- Prediction-only field log loss mean +/- CI95: 18.9911 +/- 0.0574
- Prediction-only field Brier mean +/- CI95: 0.9716 +/- 3.238e-04
- Prediction-only NLL mean +/- CI95: 15684559.4381 +/- 254998.9268

## Best Proposed Config
- Config id: `R27`
- Proposed field log loss mean +/- CI95: 16.3764 +/- 0.1270
- Proposed field Brier mean +/- CI95: 0.8611 +/- 0.0043
- Proposed NLL mean +/- CI95: 12609086.5371 +/- 237415.6086

## Best Joint Pair
- Config id: `C001`
- Prediction-only config id: `P01`
- Proposed config id: `R27`
- Guardrail satisfied: `True`
- Proposed field log loss mean +/- CI95: 16.3764 +/- 0.1270
- Proposed field Brier mean +/- CI95: 0.8611 +/- 0.0043
- Proposed NLL mean +/- CI95: 12609086.5371 +/- 237415.6086
- NLL improvement mean: 19.6152%

### Saved Parameter Blocks
- Prediction-only sigma/omega/alpha_in/mu_base: `10.0000` / `450.0000` / `0.1500` / `2.500e-05`
- Proposed sigma/omega/alpha_in/alpha_inhib/mu_base: `10.0000` / `450.0000` / `0.1500` / `0.9000` / `2.500e-05`

## Deployment Recommendation
- Selection policy: `divergence_rerank`
- Recommended config id: `C004`
- Calibration rank: `2`
- Divergence status: `PASS`
- Suppressed-area mean +/- CI95: 0.9948 +/- 0.0013
- Final exposure improve mean +/- CI95: 0.7172 +/- 2.4959
- Final response improve mean +/- CI95: -22.9894 +/- 19.5826

## Guardrail
- Any full config satisfied paired non-worsening guardrails: `True`

## Experiment Execution Order

1. **Model Calibration** (`run_sestpp_calibration_sweep.py`): Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.
2. **Field Divergence Lab** (`compare_field_divergence_lab.py`): Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.
3. **Field Divergence Confirm** (`run_field_divergence_confirm_lab.py`): Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.
4. **Planner / Assignment Tuning** (`run_assignment_tuning_sweep_lab.py`): Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.
5. **Assignment-Method Comparison** (`run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`): Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep.
6. **Robot Scaling / Long-Horizon Confirmation** (`run_robot_scaling_experiment.py`): Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.
