# Feedback Failure Slicing Diagnostic

## Parameters

- `runs`: `8`
- `seed_start`: `2026`
- `T_end`: `10800.0`
- `dt`: `5.0`
- `warmup_s`: `1800.0`
- `eval_period_s`: `30.0`
- `forecast_horizon_s`: `300.0`
- `sample_every_s`: `30.0`
- `bin_s`: `30.0`
- `task_replan_period_s`: `60.0`
- `hotspot_top_k`: `5`
- `match_radius_m`: `25.0`
- `support_radius_m`: `25.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `alpha_inhib`: `0.45`
- `omega_inhib`: `600.0`
- `mu_base`: `5e-05`
- `bg_ema`: `1e-06`
- `intervention_shuffle`: `none`

## Outcome Summary

- `exposure_improve_pct_mean`: `0.08583678992807103`
- `exposure_improve_pct_std`: `1.3197529901071368`
- `response_improve_pct_mean`: `-2.2043358597369953`
- `response_improve_pct_std`: `3.250163060580132`
- `comm_increase_pct_mean`: `54.71135903675142`
- `runs_exposure_positive`: `4`
- `runs_response_positive`: `2`
- `runs_both_positive`: `0`

## Top Exposure Correlates

- `hotspot_detection_count_delta`: pearson `-0.7946094996532426`, spearman `-0.880952380952381`, n `8`
- `p90_assign_lag_delta_s`: pearson `0.8704505691581417`, spearman `0.8571428571428572`, n `8`
- `hotspot_detection_hit_delta`: pearson `-0.8045256537008777`, spearman `-0.8434347122457898`, n `8`
- `detection_boundary_corr_delta`: pearson `-0.8161045105635594`, spearman `-0.5476190476190477`, n `8`
- `hotspot_overlap_mean`: pearson `-0.7789545481518738`, spearman `-0.6666666666666669`, n `8`

## Top Response Correlates

- `completion_lag_delta_s`: pearson `-0.890590803486654`, spearman `-0.7619047619047621`, n `8`
- `direct_completion_ratio_delta`: pearson `-0.7339907466817988`, spearman `-0.8333333333333335`, n `8`
- `active_patrol_truth_count_delta`: pearson `-0.5163137606977506`, spearman `-0.8095238095238096`, n `8`
- `active_patrol_truth_hit_delta`: pearson `-0.44548687073657417`, spearman `-0.8095238095238096`, n `8`
- `active_direct_fano_delta`: pearson `0.7892208299652667`, spearman `0.6904761904761906`, n `8`

## Conclusions

- Feedback-on proposed is not robust across seeds on exposure.
- Field-level feedback benefit remains positive on average across the same seeds.
- Strongest exposure correlate: `hotspot_detection_count_delta` (pearson `-0.7946094996532426`, spearman `-0.880952380952381`).
- Strongest response correlate: `completion_lag_delta_s` (pearson `-0.890590803486654`, spearman `-0.7619047619047621`).
