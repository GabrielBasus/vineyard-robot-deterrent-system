# Field Divergence Lab

- Per-time CSV: `field_divergence_per_time_lab.csv`
- Summary CSV: `field_divergence_summary_lab.csv`
- Metrics:
  - `lambda_l1_mean`: mean absolute difference between merged `lam` fields.
  - `lambda_l2_mean`: RMS difference between merged `lam` fields.
  - `suppressed_area_fraction`: fraction of cells where proposed `lam` is lower than prediction-only.
  - `hotspot_overlap_at_k`: matched hotspot overlap fraction at top-k.
  - `patrol_overlap`: matched overlap fraction of active patrol tasks.
  - `recent_deterrence_patrol_fraction_*`: fraction of patrol tasks near recently completed deterrence actions.
  - `local_lambda_drop_mean_*`: average local `lam` drop after newly completed deterrence actions.
  - `local_excess_drop_mean_*`: average local `(lam-mu)` drop after newly completed deterrence actions.

Interpretation:
- If field divergence metrics remain near zero, the IA-SESTPP is not changing the prediction enough to matter.
- If fields diverge but hotspot/patrol overlap remains high, hotspot extraction or planner logic is washing out the difference.
- If proposed local suppression drops are larger than prediction-only, intervention feedback is affecting the predicted field.