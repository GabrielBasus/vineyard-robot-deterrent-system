# Assignment Method Comparison Lab - Plot Summary

## Thesis Workflow Stage
- Stage 5 of 6: Assignment-Method Comparison
- Runner: `run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`
- Depends on: Planner / Assignment Tuning
- Relevance: optional; run this only if solver choice is still a thesis question after tuning.

## Stage Question
- If solver choice is still open, does another assignment method outperform the tuned default without breaking feasibility, response, or communication?

## Metrics That Matter
- `proposed-minus-prediction exposure / response / communication by method`: Method-level tradeoffs after controlling for baseline pairing.
- `assignment_solver_failures / assignment_solver_runtime_ms`: Feasibility and computational cost checks for each method.
- `winner-selection manifest rule`: Documents the tie-break order used if the stage remains relevant.

## What Counts As Failure
- A method shows infeasible or unstable assignments.
- No method improves the pairwise exposure-response tradeoff enough to justify replacing the tuned default.

## Scope
- Selected winner (from manifest rule): `frozen_greedy`
- Baselines: reactive, prediction_only, proposed
- Methods: frozen_greedy, hungarian

## Proposed minus Prediction-only (mean %) by method

| method | n pairs | exposure improve % +/- CI95 | response improve % +/- CI95 | comm increase % +/- CI95 |
|---|---:|---:|---:|---:|
| frozen_greedy | 1 | 0.000 +/- nan | 0.000 +/- nan | 12.500 +/- nan |
| hungarian | 1 | 0.000 +/- nan | 0.000 +/- nan | 29.412 +/- nan |

## Generated Plots

- `exposure_by_method.png`
- `response_by_method.png`
- `comm_by_method.png`
- `proposed_minus_prediction_by_method.png`
- `tradeoff_scatter_exposure_comm.png`
- `rank_heatmap_reactive.png`
- `rank_heatmap_prediction_only.png`
- `rank_heatmap_proposed.png`

## Experiment Execution Order

1. **Model Calibration** (`run_sestpp_calibration_sweep.py`): Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.
2. **Field Divergence Lab** (`compare_field_divergence_lab.py`): Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.
3. **Field Divergence Confirm** (`run_field_divergence_confirm_lab.py`): Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.
4. **Planner / Assignment Tuning** (`run_assignment_tuning_sweep_lab.py`): Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.
5. **Assignment-Method Comparison** (`run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`): Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep.
6. **Robot Scaling / Long-Horizon Confirmation** (`run_robot_scaling_experiment.py`): Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.
