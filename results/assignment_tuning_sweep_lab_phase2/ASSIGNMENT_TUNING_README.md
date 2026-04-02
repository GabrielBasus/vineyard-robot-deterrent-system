# Assignment Tuning Sweep Lab

## Thesis Workflow Stage
- Stage 4 of 6: Planner / Assignment Tuning
- Runner: `run_assignment_tuning_sweep_lab.py`
- Depends on: Field Divergence Confirm
- Sweep substage: `phase2`
- Relevance: required for the staged thesis evaluation flow.

## Stage Question
- Which planner, assignment, and gating settings preserve exposure gains without unacceptable response, communication, or solver regressions?

## Metrics That Matter
- `exp_improve_pct_mean / resp_improve_pct_mean / comm_increase_pct_mean`: Primary proposed-vs-prediction tradeoff metrics for selecting viable planner settings.
- `failures_mean / runtime_ms_mean`: Operational guardrails for solver feasibility and runtime stability.
- `proposed_yield_ratio_model_scored_mean / proposed_queue_depth_total_mean / proposed_stale_task_evictions_count_mean`: Checks that model-scored deterring remains productive and the planner is not saturating the queue.

## What Counts As Failure
- Any candidate produces assignment solver failures or other infeasible behavior.
- Communication cost rises sharply without corresponding exposure gain, or response time regresses enough to negate the exposure benefit.
- Model-scored deterring yield collapses or queue pressure becomes unstable in the finalist settings.

## Current Sweep Intent
- Hold the phase-1 Hungarian dispatch fixed and sweep persistence, ETA, budget, and support controls for robust planner behavior.
- Planner profile seed defaults: `manual`
- The proposed-vs-prediction CSV is built from matched seed/run pairs so the tradeoff rows stay comparable.

## Key Outputs
- Runs CSV: `assignment_tuning_runs_lab.csv`
- Summary CSV: `assignment_tuning_summary_lab.csv`
- Method deltas vs optional frozen baseline: `assignment_tuning_method_deltas_lab.csv`
- Proposed-vs-prediction deltas: `assignment_tuning_proposed_vs_prediction_lab.csv`
- Phase-1 summary: `assignment_tuning_phase1_summary_lab.csv`
- Phase-2 ranking: `assignment_tuning_phase2_ranking_lab.csv`
- Phase-4 ranking: `assignment_tuning_phase4_ranking_lab.csv`
- Calibration CSV: `model_deterring_calibration_lab.csv`
- Manifest: `assignment_tuning_manifest_lab.json`

## Hard Reject Logic
- Reject any scenario with assignment solver failures.
- In phase-1 selection, also reject scenarios with communication increase above 100% when exposure gain stays below 0.5%.

## Current Best Hungarian Scenario
- Scenario id: `d0.004_s0.5_rp105_tv0_gpsprt_capacity_sa0.05_sb0.2_ct0.15_ucr0.15_rho0.85_rt0.35_mp2_eta120_sm0.05_bh4_bmcph_bu5_dw90_mdj0_bt0.35`
- Exposure improve mean: 4.9243%
- Response improve mean: 4.0585%
- Communication increase mean: 77.1255%
- Runtime mean: 1.4592 ms

## Experiment Execution Order

1. **Model Calibration** (`run_sestpp_calibration_sweep.py`): Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.
2. **Field Divergence Lab** (`compare_field_divergence_lab.py`): Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.
3. **Field Divergence Confirm** (`run_field_divergence_confirm_lab.py`): Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.
4. **Planner / Assignment Tuning** (`run_assignment_tuning_sweep_lab.py`): Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.
5. **Assignment-Method Comparison** (`run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`): Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep.
6. **Robot Scaling / Long-Horizon Confirmation** (`run_robot_scaling_experiment.py`): Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.
