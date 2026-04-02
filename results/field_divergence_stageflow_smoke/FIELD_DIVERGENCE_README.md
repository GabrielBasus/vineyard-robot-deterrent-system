# Field Divergence Lab

## Thesis Workflow Stage
- Stage 2 of 6: Field Divergence Lab
- Runner: `compare_field_divergence_lab.py`
- Depends on: Model Calibration
- Relevance: required for the staged thesis evaluation flow.

## Stage Question
- Does the calibrated proposed field diverge from prediction-only strongly enough to survive local hotspot filtering and patrol generation?

## Metrics That Matter
- `suppressed_area_fraction_mean`: Minimum evidence that the proposed field is meaningfully different from prediction-only.
- `local_hotspots_score_filtered_overlap_mean / local_hotspots_spaced_overlap_mean`: Whether filtering and thinning preserve the upstream field difference.
- `raw_patrol_candidate_overlap_mean / selected_patrol_overlap_mean / patrol_overlap_mean`: Whether task generation, assignment, and queueing collapse the divergence before execution.

## What Counts As Failure
- suppressed_area_fraction_mean stays below the field-divergence floor, so downstream planner interpretation is not justified.
- Any downstream overlap metric rises above the collapse threshold, indicating the planner pipeline is washing out the field difference.

## Key Outputs
- Per-time CSV: `field_divergence_per_time_lab.csv`
- Summary CSV: `field_divergence_summary_lab.csv`
- Acceptance CSV: `field_divergence_acceptance_lab.csv`
- Resolved config: `field_divergence_resolved_config.json`

## Exported Metrics
- `lambda_l1_mean`: mean absolute difference between merged `lam` fields.
- `lambda_l2_mean`: RMS difference between merged `lam` fields.
- `suppressed_area_fraction`: fraction of cells where proposed `lam` is lower than prediction-only.
- `hotspot_overlap_at_k`: matched hotspot overlap fraction at top-k.
- `local_hotspot_filter_threshold_mean_*`: average local hotspot score threshold applied across robots.
- `local_hotspots_raw_score_p50/p90/max_*`: score distribution diagnostics for local raw hotspots.
- `local_hotspots_raw_overlap`: overlap of zone-masked local hotspots before score filtering.
- `local_hotspots_score_filtered_overlap`: overlap after local hotspot score thresholding.
- `local_hotspots_spaced_overlap`: overlap after spacing / thinning.
- `raw_patrol_candidate_overlap`: overlap of raw patrol candidates before assignment/admission.
- `selected_patrol_overlap`: overlap of patrol tasks selected by assignment before persistence/queueing.
- `patrol_overlap`: matched overlap fraction of active patrol tasks.
- `recent_deterrence_patrol_fraction_*`: fraction of patrol tasks near recently completed deterrence actions.
- `local_lambda_drop_mean_*`: average local `lam` drop after newly completed deterrence actions.
- `local_excess_drop_mean_*`: average local `(lam-mu)` drop after newly completed deterrence actions.

## Acceptance Summary
| Failure mode | Status | Evidence | Acceptance test | Note |
| --- | --- | --- | --- | --- |
| `no_meaningful_field_divergence` | PASS | `suppressed_area_fraction_mean`=0.3293 | `suppressed_area_fraction_mean` >= 0.1000 | Mean suppressed-area fraction clears the minimum field-divergence floor. |
| `filter_collapse` | PASS | `local_hotspots_score_filtered_overlap_mean`=0.000e+00 | `local_hotspots_score_filtered_overlap_mean` <= 0.8000 | Filtered local hotspots still differ enough across baselines. |
| `spacing_collapse` | PASS | `local_hotspots_spaced_overlap_mean`=0.000e+00 | `local_hotspots_spaced_overlap_mean` <= 0.8000 | Spacing/thinning keeps the filtered hotspot difference visible. |
| `raw_patrol_candidate_collapse` | PASS | `raw_patrol_candidate_overlap_mean`=0.000e+00 | `raw_patrol_candidate_overlap_mean` <= 0.8000 | Raw patrol candidates remain distinct when the field differs. |
| `selected_patrol_collapse` | FAIL | `selected_patrol_overlap_mean`=1.0000 | `selected_patrol_overlap_mean` <= 0.8000 | Assignment/selection leaves the selected patrol tasks too similar. |
| `active_patrol_collapse` | FAIL | `patrol_overlap_mean`=1.0000 | `patrol_overlap_mean` <= 0.8000 | The active patrol queue collapses back to near-identical patrols. |

## Interpretation
- Likely bottleneck: Assignment/selection is re-merging patrol options that were distinct upstream.

## Acceptance Logic
- `suppressed_area_fraction_mean >= 0.10` establishes that the proposed field differs enough to interpret downstream planner stages.
- Each downstream overlap mean should remain at or below `0.80`; higher overlap means that stage is collapsing a difference that should still be visible.

## Additional Interpretation
- If field divergence metrics remain near zero, the IA-SESTPP is not changing the prediction enough to matter.
- If global hotspots diverge but local hotspot overlaps remain high, the zone-masked local planning view is washing out the global difference.
- If the local raw score p90 stays below the applied threshold, the score threshold is too strict for the local patrol generator.
- If local raw hotspots diverge but score-filtered or spaced hotspots do not, local filtering/thinning is collapsing the difference.
- If local spaced hotspots diverge but raw patrol candidates do not, the patrol candidate creation stage is collapsing the difference.
- If hotspots diverge but raw patrol candidates do not, task generation is washing out the field difference.
- If raw patrol candidates diverge but selected patrol tasks do not, assignment/selection is washing out the difference.
- If selected patrol tasks diverge but active patrol queue does not, persistence/queueing is washing out the difference.
- If proposed local suppression drops are larger than prediction-only, intervention feedback is affecting the predicted field.

## Experiment Execution Order

1. **Model Calibration** (`run_sestpp_calibration_sweep.py`): Freeze the intervention-aware SESTPP settings that every downstream stage will reuse.
2. **Field Divergence Lab** (`compare_field_divergence_lab.py`): Run a diagnostic single-seed or small-scale lab check before claiming robust downstream planner effects.
3. **Field Divergence Confirm** (`run_field_divergence_confirm_lab.py`): Only advance once the same-seed proposed-vs-prediction comparisons remain favorable across seeds with defensible CI95 bounds.
4. **Planner / Assignment Tuning** (`run_assignment_tuning_sweep_lab.py`): Tune dispatch and gating only after the field-divergence mechanism is confirmed, otherwise planner fixes may optimize around a model artifact.
5. **Assignment-Method Comparison** (`run_assignment_method_comparison_lab.py / plot_assignment_method_comparison_lab.py`): Use this as an optional solver-ablation stage if method choice still matters after the main tuning sweep. Optional stage.
6. **Robot Scaling / Long-Horizon Confirmation** (`run_robot_scaling_experiment.py`): Finish with the tuned planner on matched proposed-vs-prediction pairs to confirm that gains scale with fleet size and horizon.