# Field Divergence Confirm

## Thesis Workflow Stage
- Stage 3 of 6: Field Divergence Confirm
- Runner: `run_field_divergence_confirm_lab.py`
- Depends on: Field Divergence Lab
- Relevance: required for the staged thesis evaluation flow.

## Stage Question
- Across matched seeds, is the proposed-vs-prediction field separation robust enough to support downstream planner claims?

## Metrics That Matter
- `final_exposure_improve_pct / final_response_improve_pct`: Pairwise proposed-vs-prediction end-of-run deltas on the same seeds.
- `suppressed_area_fraction_mean and pipeline-overlap means with CI95`: Aggregate evidence that divergence survives filtering, candidate generation, selection, and active patrol execution.
- `acceptance status table`: PASS/FAIL/WARN summary for whether each CI95 interval stays on the accepted side of its threshold.

## What Counts As Failure
- CI95 stays fully on the rejected side of a required acceptance threshold.
- CI95 straddles a threshold for a required claim, leaving the confirm stage inconclusive and blocking downstream interpretation.
- Pairwise exposure or response deltas are not robust when proposed is matched directly against prediction-only on the same seeds.

## Confirm Protocol
- Pair proposed and prediction-only runs on the same seed and summarize those deltas, not unmatched aggregate means.
- Report mean and CI95 for the paired deltas and the aggregate acceptance metrics in the confirm README/CSV outputs.
- Treat threshold-straddling CI95 intervals as inconclusive confirmation rather than a pass.

## Key Outputs
- Per-time CSV: `field_divergence_confirm_per_time.csv`
- Per-seed CSV: `field_divergence_confirm_per_seed.csv`
- Aggregate CSV: `field_divergence_confirm_aggregate.csv`
- Acceptance CSV: `field_divergence_confirm_acceptance.csv`
- Manifest: `field_divergence_confirm_manifest.json`

## Acceptance Summary
| Failure mode | Status | Evidence | Acceptance test | Note |
| --- | --- | --- | --- | --- |
| `no_meaningful_field_divergence` | PASS | `suppressed_area_fraction_mean`=0.4777 (CI95 [0.4249, 0.5304]) | `suppressed_area_fraction_mean` >= 0.1000 | Mean suppressed-area fraction clears the minimum field-divergence floor. |
| `filter_collapse` | PASS | `local_hotspots_score_filtered_overlap_mean`=0.1718 (CI95 [0.1164, 0.2272]) | `local_hotspots_score_filtered_overlap_mean` <= 0.8000 | Filtered local hotspots still differ enough across baselines. |
| `raw_patrol_candidate_collapse` | PASS | `raw_patrol_candidate_overlap_mean`=0.1615 (CI95 [0.1122, 0.2109]) | `raw_patrol_candidate_overlap_mean` <= 0.8000 | Raw patrol candidates remain distinct when the field differs. |
| `selected_patrol_collapse` | PASS | `selected_patrol_overlap_mean`=0.2915 (CI95 [0.2066, 0.3764]) | `selected_patrol_overlap_mean` <= 0.8000 | Selected patrol tasks still reflect the upstream field difference. |
| `active_patrol_collapse` | PASS | `patrol_overlap_mean`=0.2297 (CI95 [0.1321, 0.3273]) | `patrol_overlap_mean` <= 0.8000 | The active patrol queue still differs across baselines. |

## Interpretation
- Likely bottleneck: Spacing/thinning is the first stage that removes the hotspot difference.
- All confirm deltas are paired proposed-vs-prediction comparisons on the same seeds before aggregation.

## Aggregate Acceptance Logic
- `PASS` means the metric CI95 stays on the accepted side of the threshold.
- `FAIL` means the metric CI95 stays on the rejected side of the threshold.
- `WARN` means the CI95 straddles the threshold, or upstream field divergence is too weak to interpret downstream collapse.
- Field divergence requires `suppressed_area_fraction_mean >= 0.10`; downstream overlap means should stay at or below `0.80`.

## Key Interpretation
- `final_exposure_improve_pct > 0` means proposed lowered exposure relative to prediction-only.
- `final_response_improve_pct > 0` means proposed improved response time.
- Planner profile: `manual`
- Gate policy: `sprt_capacity`
- Low patrol-overlap metrics mean the proposed model is changing actual patrol behavior.
- Use the aggregate CSV CI95 values to judge whether single-seed improvements look robust.

## Experiment Execution Order

1. **Model Calibration** (`run_sestpp_calibration_sweep.py`): Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.
2. **Field Divergence Lab** (`compare_field_divergence_lab.py`): Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.
3. **Field Divergence Confirm** (`run_field_divergence_confirm_lab.py`): Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.
4. **Planner / Assignment Tuning** (`run_assignment_tuning_sweep_lab.py`): Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.
5. **Assignment-Method Comparison** (`run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`): Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep.
6. **Robot Scaling / Long-Horizon Confirmation** (`run_robot_scaling_experiment.py`): Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.