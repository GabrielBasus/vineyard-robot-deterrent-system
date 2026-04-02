# Rejected Preventive Candidate Diagnostic

## Parameters

- `T_end`: `10800.0`
- `dt`: `5.0`
- `seed`: `2026`
- `W`: `500.0`
- `H`: `500.0`
- `NX`: `80`
- `NY`: `64`
- `Nrobots`: `6`
- `uav_fraction`: `0.0`
- `warmup_s`: `1800.0`
- `task_replan_period_s`: `60.0`
- `event_viz_window_s`: `60.0`
- `model_deterring_window_s`: `120.0`
- `model_deterring_gate_policy`: `sprt_capacity`
- `model_deterring_sprt_alpha`: `0.25`
- `model_deterring_sprt_beta`: `0.4`
- `model_deterring_sprt_patch_radius_m`: `30.0`
- `model_deterring_chance_threshold`: `0.25`
- `model_deterring_min_deltaJ_per_cost`: `100000.0`
- `model_deterring_capacity_rho_max`: `0.85`
- `model_deterring_score_margin`: `0.1`
- `model_deterring_global_admission_cap_per_cycle`: `1`
- `model_deterring_require_idle_robot_for_admission`: `False`
- `model_deterring_prefer_idle_robots_for_assignment`: `True`
- `model_deterring_busy_fallback_p_event_min`: `0.95`
- `model_deterring_busy_fallback_deltaJ_per_cost_min`: `2000000.0`
- `model_deterring_busy_fallback_eta_s_max`: `1.25`
- `protect_direct_detection_from_model_deterring`: `True`
- `model_deterring_direct_conflict_radius_m`: `35.0`
- `model_deterring_direct_conflict_window_s`: `120.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `emit_rejected_model_det_debug`: `True`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Accepted Model-Scored Summary

- `count`: `6`
- `future_truth_hit_rate`: `0.8333333333333334`
- `future_truth_count_mean`: `2.1666666666666665`
- `recent_truth_count_mean`: `1.5`
- `p_event_mean`: `0.9357211201778677`
- `predicted_deltaJ_mean`: `320085.17973791616`
- `deltaJ_per_cost_mean`: `3818091.2501001526`
- `eta_s_mean`: `1.2784685065235293`

## Rejected Model-Scored Summary

- `count`: `284`
- `future_truth_hit_rate`: `0.778169014084507`
- `future_truth_count_mean`: `1.5140845070422535`
- `recent_truth_count_mean`: `0.8309859154929577`
- `p_event_mean`: `0.7944720452983648`
- `predicted_deltaJ_mean`: `319904.2229153563`
- `deltaJ_per_cost_mean`: `672359.0071977339`
- `eta_s_mean`: `1.314822869329476`

## Rejected By Reason

### budget

- `count`: `4`
- `future_truth_hit_rate`: `1.0`
- `future_truth_count_mean`: `3.25`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.539067937993353`
- `predicted_deltaJ_mean`: `325489.75080660824`
- `deltaJ_per_cost_mean`: `492078.9893515309`
- `eta_s_mean`: `1.0780268200895424`

### busy_fallback_quality

- `count`: `258`
- `future_truth_hit_rate`: `0.7751937984496124`
- `future_truth_count_mean`: `1.434108527131783`
- `recent_truth_count_mean`: `0.875968992248062`
- `p_event_mean`: `0.8075271417395973`
- `predicted_deltaJ_mean`: `319627.5181277676`
- `deltaJ_per_cost_mean`: `450356.2450565842`
- `eta_s_mean`: `1.3517615231181246`

### cycle_cap

- `count`: `12`
- `future_truth_hit_rate`: `0.5833333333333334`
- `future_truth_count_mean`: `1.3333333333333333`
- `recent_truth_count_mean`: `0.75`
- `p_event_mean`: `0.7425605463498627`
- `predicted_deltaJ_mean`: `321520.83217858657`
- `deltaJ_per_cost_mean`: `364109.64351525716`
- `eta_s_mean`: `1.3148039842989319`

### direct_conflict

- `count`: `6`
- `future_truth_hit_rate`: `1.0`
- `future_truth_count_mean`: `2.5`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.7826462174996514`
- `predicted_deltaJ_mean`: `321370.39721825114`
- `deltaJ_per_cost_mean`: `10915109.71346184`
- `eta_s_mean`: `0.4481018064518602`

### task_cap

- `count`: `4`
- `future_truth_hit_rate`: `1.0`
- `future_truth_count_mean`: `4.0`
- `recent_truth_count_mean`: `0.25`
- `p_event_mean`: `0.3812956706874615`
- `predicted_deltaJ_mean`: `325117.06457953417`
- `deltaJ_per_cost_mean`: `732439.214799359`
- `eta_s_mean`: `0.469213998609634`

## Critical Recommendations

- Rejected `busy_fallback_quality` candidates have meaningful future-truth support; this filter may be too strict.
- Rejected `direct_conflict` candidates have meaningful future-truth support; this filter may be too strict.
- Rejected `cycle_cap` candidates have meaningful future-truth support; this filter may be too strict.
- Rejected `budget` candidates have meaningful future-truth support; this filter may be too strict.
