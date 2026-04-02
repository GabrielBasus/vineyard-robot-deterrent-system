# Field Divergence Lab

- Per-time CSV: `field_divergence_per_time_lab.csv`
- Summary CSV: `field_divergence_summary_lab.csv`
- Acceptance CSV: `field_divergence_acceptance_lab.csv`
- Resolved config: `field_divergence_resolved_config.json`
- Metrics:
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

Acceptance summary:
| Failure mode | Status | Evidence | Acceptance test | Note |
| --- | --- | --- | --- | --- |
| `no_meaningful_field_divergence` | FAIL | `suppressed_area_fraction_mean`=0.000e+00 | `suppressed_area_fraction_mean` >= 0.1000 | Mean suppressed-area fraction stays below the minimum field-divergence floor. |
| `filter_collapse` | WARN | `local_hotspots_score_filtered_overlap_mean`=0.000e+00 | `local_hotspots_score_filtered_overlap_mean` <= 0.8000 | Upstream field divergence is below the acceptance floor, so this downstream collapse check is inconclusive. |
| `spacing_collapse` | WARN | `local_hotspots_spaced_overlap_mean`=0.000e+00 | `local_hotspots_spaced_overlap_mean` <= 0.8000 | Upstream field divergence is below the acceptance floor, so this downstream collapse check is inconclusive. |
| `raw_patrol_candidate_collapse` | WARN | `raw_patrol_candidate_overlap_mean`=0.000e+00 | `raw_patrol_candidate_overlap_mean` <= 0.8000 | Upstream field divergence is below the acceptance floor, so this downstream collapse check is inconclusive. |
| `selected_patrol_collapse` | WARN | `selected_patrol_overlap_mean`=1.0000 | `selected_patrol_overlap_mean` <= 0.8000 | Upstream field divergence is below the acceptance floor, so this downstream collapse check is inconclusive. |
| `active_patrol_collapse` | WARN | `patrol_overlap_mean`=1.0000 | `patrol_overlap_mean` <= 0.8000 | Upstream field divergence is below the acceptance floor, so this downstream collapse check is inconclusive. |

- Likely bottleneck: The proposed field is not separating enough from prediction-only before the local patrol pipeline.

Acceptance logic:
- `suppressed_area_fraction_mean >= 0.10` establishes that the proposed field differs enough to interpret downstream planner stages.
- Each downstream overlap mean should remain at or below `0.80`; higher overlap means that stage is collapsing a difference that should still be visible.

Interpretation:
- If field divergence metrics remain near zero, the IA-SESTPP is not changing the prediction enough to matter.
- If global hotspots diverge but local hotspot overlaps remain high, the zone-masked local planning view is washing out the global difference.
- If the local raw score p90 stays below the applied threshold, the score threshold is too strict for the local patrol generator.
- If local raw hotspots diverge but score-filtered or spaced hotspots do not, local filtering/thinning is collapsing the difference.
- If local spaced hotspots diverge but raw patrol candidates do not, the patrol candidate creation stage is collapsing the difference.
- If hotspots diverge but raw patrol candidates do not, task generation is washing out the field difference.
- If raw patrol candidates diverge but selected patrol tasks do not, assignment/selection is washing out the difference.
- If selected patrol tasks diverge but active patrol queue does not, persistence/queueing is washing out the difference.
- If proposed local suppression drops are larger than prediction-only, intervention feedback is affecting the predicted field.