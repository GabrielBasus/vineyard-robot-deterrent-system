# Field Divergence Confirm

- Per-time CSV: `field_divergence_confirm_per_time.csv`
- Per-seed CSV: `field_divergence_confirm_per_seed.csv`
- Aggregate CSV: `field_divergence_confirm_aggregate.csv`
- Acceptance CSV: `field_divergence_confirm_acceptance.csv`
- Manifest: `field_divergence_confirm_manifest.json`

Aggregate acceptance summary:
| Failure mode | Status | Evidence | Acceptance test | Note |
| --- | --- | --- | --- | --- |
| `no_meaningful_field_divergence` | FAIL | `suppressed_area_fraction_mean`=0.000e+00 (CI95 [0.000e+00, 0.000e+00]) | `suppressed_area_fraction_mean` >= 0.1000 | Mean suppressed-area fraction stays below the minimum field-divergence floor. |
| `filter_collapse` | WARN | `local_hotspots_score_filtered_overlap_mean`=1.0000 (CI95 [1.0000, 1.0000]) | `local_hotspots_score_filtered_overlap_mean` <= 0.8000 | Aggregate field-divergence evidence is not yet robust enough to interpret this downstream stage. |
| `raw_patrol_candidate_collapse` | WARN | `raw_patrol_candidate_overlap_mean`=1.0000 (CI95 [1.0000, 1.0000]) | `raw_patrol_candidate_overlap_mean` <= 0.8000 | Aggregate field-divergence evidence is not yet robust enough to interpret this downstream stage. |
| `selected_patrol_collapse` | WARN | `selected_patrol_overlap_mean`=1.0000 (CI95 [1.0000, 1.0000]) | `selected_patrol_overlap_mean` <= 0.8000 | Aggregate field-divergence evidence is not yet robust enough to interpret this downstream stage. |
| `active_patrol_collapse` | WARN | `patrol_overlap_mean`=1.0000 (CI95 [1.0000, 1.0000]) | `patrol_overlap_mean` <= 0.8000 | Aggregate field-divergence evidence is not yet robust enough to interpret this downstream stage. |

- Likely bottleneck: The proposed field is not separating enough from prediction-only before the local patrol pipeline.

Aggregate acceptance logic:
- `PASS` means the metric CI95 stays on the accepted side of the threshold.
- `FAIL` means the metric CI95 stays on the rejected side of the threshold.
- `WARN` means the CI95 straddles the threshold, or upstream field divergence is too weak to interpret downstream collapse.
- Field divergence requires `suppressed_area_fraction_mean >= 0.10`; downstream overlap means should stay at or below `0.80`.

Key interpretation:
- `final_exposure_improve_pct > 0` means proposed lowered exposure relative to prediction-only.
- `final_response_improve_pct > 0` means proposed improved response time.
- Planner profile: `manual`
- Gate policy: `heuristic`
- Low patrol-overlap metrics mean the proposed model is changing actual patrol behavior.
- Use the aggregate CSV CI95 values to judge whether single-seed improvements look robust.