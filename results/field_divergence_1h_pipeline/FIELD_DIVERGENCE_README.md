# Field Divergence Lab

- Per-time CSV: `field_divergence_per_time_lab.csv`
- Summary CSV: `field_divergence_summary_lab.csv`
- Metrics:
  - `lambda_l1_mean`: mean absolute difference between merged `lam` fields.
  - `lambda_l2_mean`: RMS difference between merged `lam` fields.
  - `suppressed_area_fraction`: fraction of cells where proposed `lam` is lower than prediction-only.
  - `hotspot_overlap_at_k`: matched hotspot overlap fraction at top-k.
  - `raw_patrol_candidate_overlap`: overlap of raw patrol candidates before assignment/admission.
  - `selected_patrol_overlap`: overlap of patrol tasks selected by assignment before persistence/queueing.
  - `patrol_overlap`: matched overlap fraction of active patrol tasks.
  - `recent_deterrence_patrol_fraction_*`: fraction of patrol tasks near recently completed deterrence actions.
  - `local_lambda_drop_mean_*`: average local `lam` drop after newly completed deterrence actions.
  - `local_excess_drop_mean_*`: average local `(lam-mu)` drop after newly completed deterrence actions.

Interpretation:
- If field divergence metrics remain near zero, the IA-SESTPP is not changing the prediction enough to matter.
- If hotspots diverge but raw patrol candidates do not, task generation is washing out the field difference.
- If raw patrol candidates diverge but selected patrol tasks do not, assignment/selection is washing out the difference.
- If selected patrol tasks diverge but active patrol queue does not, persistence/queueing is washing out the difference.
- If proposed local suppression drops are larger than prediction-only, intervention feedback is affecting the predicted field.