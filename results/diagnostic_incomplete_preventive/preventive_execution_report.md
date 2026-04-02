# Incomplete Preventive Task Diagnostic

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
- `model_deterring_chance_threshold`: `0.35`
- `model_deterring_min_deltaJ_per_cost`: `100000.0`
- `model_deterring_capacity_rho_max`: `0.85`
- `model_deterring_score_margin`: `0.1`
- `model_deterring_global_admission_cap_per_cycle`: `1`
- `model_deterring_require_idle_robot_for_admission`: `False`
- `model_deterring_prefer_idle_robots_for_assignment`: `True`
- `model_deterring_busy_fallback_p_event_min`: `0.9`
- `model_deterring_busy_fallback_deltaJ_per_cost_min`: `1000000.0`
- `model_deterring_busy_fallback_eta_s_max`: `1.25`
- `protect_direct_detection_from_model_deterring`: `True`
- `model_deterring_direct_conflict_radius_m`: `35.0`
- `model_deterring_direct_conflict_window_s`: `120.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Metrics

- `value_weighted_exposure`: `17821.51813289534`
- `mean_response_time_s`: `100.15587175048024`
- `boundary_message_count`: `539.0`
- `model_deterring_generated`: `17.0`
- `model_deterring_accepted`: `6.0`
- `deterring_actions_completed_model_scored`: `0.0`

## Accepted Model-Scored Summary

- `count`: `6`
- `future_truth_hit_rate`: `0.8333333333333334`
- `future_truth_count_mean`: `1.8333333333333333`
- `recent_truth_count_mean`: `0.5`
- `p_event_mean`: `0.9357211201778677`
- `deltaJ_per_cost_mean`: `3818091.2501001526`
- `command_match_fraction_mean`: `0.38461538461538464`
- `min_distance_mean_m`: `209.16196225086495`
- `time_in_system_mean_s`: `60.0`

## Completed Model-Scored Summary

- `count`: `0`
- `future_truth_hit_rate`: `nan`
- `future_truth_count_mean`: `nan`
- `recent_truth_count_mean`: `nan`
- `p_event_mean`: `nan`
- `deltaJ_per_cost_mean`: `nan`
- `command_match_fraction_mean`: `nan`
- `min_distance_mean_m`: `nan`
- `time_in_system_mean_s`: `nan`

## Incomplete Model-Scored Summary

- `count`: `6`
- `future_truth_hit_rate`: `0.8333333333333334`
- `future_truth_count_mean`: `1.8333333333333333`
- `recent_truth_count_mean`: `0.5`
- `p_event_mean`: `0.9357211201778677`
- `deltaJ_per_cost_mean`: `3818091.2501001526`
- `command_match_fraction_mean`: `0.38461538461538464`
- `min_distance_mean_m`: `209.16196225086495`
- `time_in_system_mean_s`: `60.0`

## Incomplete Reasons

- `dropped_for_patrol`: `3`
- `dropped_for_model_scored`: `2`
- `dropped_in_transit`: `1`

## Critical Recommendations

- Accepted preventive tasks are still being replaced by patrol work; patrol replacement is too aggressive for admitted preventive tasks.
- Several accepted preventive tasks are dropped before the robot gets close; ETA/travel assumptions or task persistence need tightening.
- Incomplete preventive tasks still have strong future-truth support; the remaining loss is execution/persistence, not candidate quality.
