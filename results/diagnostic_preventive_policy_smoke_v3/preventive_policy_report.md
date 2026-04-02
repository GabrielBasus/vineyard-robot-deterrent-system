# Preventive Policy Diagnostic Report

## Parameters

- `T_end`: `1800.0`
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
- `model_deterring_require_idle_robot_for_admission`: `True`
- `protect_direct_detection_from_model_deterring`: `True`
- `model_deterring_direct_conflict_radius_m`: `35.0`
- `model_deterring_direct_conflict_window_s`: `120.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Comparison

- Exposure improvement vs `prediction_only`: `-6.224%`
- Response improvement vs `prediction_only`: `-7.232%`

## Preventive Task Quality

### model_scored_deterring

- `accepted_count`: `0`
- `completed_count`: `0`
- `dropped_count`: `0`
- `completion_rate`: `nan`
- `future_truth_hit_rate`: `nan`
- `future_truth_count_mean`: `nan`
- `recent_truth_count_mean`: `nan`
- `p_event_mean`: `nan`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `nan`
- `predicted_deltaJ_mean`: `nan`
- `deltaJ_per_cost_mean`: `nan`
- `accept_with_preempt_rate`: `nan`
- `dropped_patrol_same_robot_at_accept_mean`: `nan`
- `dropped_direct_detection_same_robot_at_accept_mean`: `nan`
- `time_to_complete_mean_s`: `nan`

### patrolling

- `accepted_count`: `173`
- `completed_count`: `58`
- `dropped_count`: `112`
- `completion_rate`: `0.3352601156069364`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.03468208092485549`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `11.89655172413793`

### direct_detection_deterring

- `accepted_count`: `98`
- `completed_count`: `62`
- `dropped_count`: `34`
- `completion_rate`: `0.6326530612244898`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `74.11290322580645`

## Comparative Quality

- `model_scored_minus_patrolling_future_truth_hit_rate`: `nan`
- `model_scored_minus_patrolling_future_truth_count_mean`: `nan`

## Critical Recommendations

- No model-scored preventive tasks were accepted; the bottleneck is still admission, not task quality.
