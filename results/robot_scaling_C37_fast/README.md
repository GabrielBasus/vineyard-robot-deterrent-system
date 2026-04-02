# Robot Scaling Experiment

## Thesis Workflow Stage
- Stage 6 of 6: Robot Scaling / Long-Horizon Confirmation
- Runner: `run_robot_scaling_experiment.py`
- Depends on: Planner / Assignment Tuning
- Relevance: required for the staged thesis evaluation flow.

## Stage Question
- With the tuned planner fixed, do proposed-vs-prediction gains persist or grow as robot count and horizon increase?

## Metrics That Matter
- `delta_exp_improve_pct_mean with CI95`: Exposure improvement should grow or at least remain clearly positive as robot count rises.
- `delta_resp_improve_pct_mean with CI95`: Response improvement should not collapse as more robots are added.
- `delta_comm_increase_pct_mean with CI95`: Communication growth should remain controlled rather than exploding with fleet size.
- `delta_model_done_gain_mean with CI95`: Completed model-scored deterring gain should rise once planner bottlenecks are removed.

## What Counts As Failure
- Exposure improvement fails to grow or loses its positive trend as robot count rises.
- Response degrades enough to indicate a scaling collapse.
- Communication overhead becomes uncontrolled relative to the exposure benefit.
- Model-scored deterring gain stays flat or negative after planner bottlenecks were expected to be removed.

## Confirm Protocol
- Pair proposed and prediction-only runs on the same scenario, robot count, and seed before computing deltas.
- Report CI95 on every scaling delta so trend claims are supported by uncertainty bounds rather than single averages.
- Treat flat or negative paired scaling trends as failed long-horizon confirmation, even if one operating point looks favorable.

## Experiment Setup
- Robot counts: [2, 4, 6, 8, 10]
- Scenarios: ['S2_nominal', 'S3_high_pressure_long_range']
- Runs per setting: 5
- Horizon [h]: 24.0

## Key outputs
- `robot_scaling_baseline_summary.csv`
- `robot_scaling_run_metrics.csv`
- `robot_scaling_pairwise_deltas.csv`
- `robot_scaling_delta_summary.csv`
- `01_exposure_improvement_vs_robot_count.png`
- `02_response_improvement_vs_robot_count.png`
- `03_comm_increase_vs_robot_count.png`
- `04_model_done_gain_vs_robot_count.png`
- `05_absolute_exposure_by_baseline_vs_robot_count.png`

## Pairwise Scaling Interpretation
- Every scaling delta is a proposed-vs-prediction comparison on the same scenario, robot count, and seed before CI95 aggregation.
- Exposure improvement should grow with robot count or at least stay clearly positive.
- Response should not collapse as the fleet grows.
- Communication should stay controlled rather than expanding faster than the benefit.
- Model-scored deterring gain should rise with robot count if planner bottlenecks are removed.

## Experiment Execution Order

1. **Model Calibration** (`run_sestpp_calibration_sweep.py`): Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.
2. **Field Divergence Lab** (`compare_field_divergence_lab.py`): Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.
3. **Field Divergence Confirm** (`run_field_divergence_confirm_lab.py`): Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.
4. **Planner / Assignment Tuning** (`run_assignment_tuning_sweep_lab.py`): Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.
5. **Assignment-Method Comparison** (`run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`): Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep.
6. **Robot Scaling / Long-Horizon Confirmation** (`run_robot_scaling_experiment.py`): Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.