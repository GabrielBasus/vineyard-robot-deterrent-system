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
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Comparison

- Exposure improvement vs `prediction_only`: `2.735%`
- Response improvement vs `prediction_only`: `4.364%`

## Preventive Task Quality

### model_scored_deterring

- `accepted_count`: `8`
- `completed_count`: `5`
- `dropped_count`: `3`
- `completion_rate`: `0.625`
- `future_truth_hit_rate`: `0.5`
- `future_truth_count_mean`: `0.875`
- `recent_truth_count_mean`: `1.125`
- `p_event_mean`: `0.8117365433276134`
- `p_event_hit_mean`: `0.9165839865938384`
- `p_event_miss_mean`: `0.7068891000613884`
- `predicted_deltaJ_mean`: `317197.4766799898`
- `deltaJ_per_cost_mean`: `2963844.650893191`
- `accept_with_preempt_rate`: `0.25`
- `dropped_patrol_same_robot_at_accept_mean`: `0.25`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.125`
- `time_to_complete_mean_s`: `72.0`

### patrolling

- `accepted_count`: `1053`
- `completed_count`: `394`
- `dropped_count`: `656`
- `completion_rate`: `0.3741690408357075`
- `future_truth_hit_rate`: `0.6087369420702754`
- `future_truth_count_mean`: `1.2070275403608737`
- `recent_truth_count_mean`: `0.7559354226020892`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `10.596446700507615`

### direct_detection_deterring

- `accepted_count`: `530`
- `completed_count`: `350`
- `dropped_count`: `180`
- `completion_rate`: `0.660377358490566`
- `future_truth_hit_rate`: `0.6264150943396226`
- `future_truth_count_mean`: `1.3867924528301887`
- `recent_truth_count_mean`: `0.8188679245283019`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `70.94285714285714`

## Comparative Quality

- `model_scored_minus_patrolling_future_truth_hit_rate`: `-0.1087369420702754`
- `model_scored_minus_patrolling_future_truth_count_mean`: `-0.3320275403608737`

## Critical Recommendations

- Accepted model-scored tasks are landing in weaker locations than patrol tasks; tighten admission or re-rank preventive tasks by stronger future-event evidence.
