# Preventive Policy Diagnostic Report

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
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Comparison

- Exposure improvement vs `prediction_only`: `2.207%`
- Response improvement vs `prediction_only`: `4.975%`

## Preventive Task Quality

### model_scored_deterring

- `accepted_count`: `6`
- `completed_count`: `0`
- `dropped_count`: `6`
- `completion_rate`: `0.0`
- `future_truth_hit_rate`: `0.8333333333333334`
- `future_truth_count_mean`: `2.1666666666666665`
- `recent_truth_count_mean`: `1.5`
- `p_event_mean`: `0.9357211201778677`
- `p_event_hit_mean`: `0.9241342487749048`
- `p_event_miss_mean`: `0.9936554771926819`
- `predicted_deltaJ_mean`: `320085.17973791616`
- `deltaJ_per_cost_mean`: `3818091.2501001526`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.6666666666666666`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `nan`

### patrolling

- `accepted_count`: `1045`
- `completed_count`: `460`
- `dropped_count`: `581`
- `completion_rate`: `0.44019138755980863`
- `future_truth_hit_rate`: `0.6248803827751196`
- `future_truth_count_mean`: `1.199043062200957`
- `recent_truth_count_mean`: `0.784688995215311`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `9.01086956521739`

### direct_detection_deterring

- `accepted_count`: `465`
- `completed_count`: `307`
- `dropped_count`: `154`
- `completion_rate`: `0.6602150537634408`
- `future_truth_hit_rate`: `0.621505376344086`
- `future_truth_count_mean`: `1.2666666666666666`
- `recent_truth_count_mean`: `0.7720430107526882`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `71.25407166123779`

## Comparative Quality

- `model_scored_minus_patrolling_future_truth_hit_rate`: `0.20845295055821378`
- `model_scored_minus_patrolling_future_truth_count_mean`: `0.9676236044657096`

## Critical Recommendations

- Many accepted model-scored tasks do not complete; reduce ETA allowance or admit fewer preventive tasks so execution can keep up.
- The accepted-task chance score is not separating hits from misses; recalibrate the chance mapping or gate on a stronger local truth proxy.
