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
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Comparison

- Exposure improvement vs `prediction_only`: `-7.059%`
- Response improvement vs `prediction_only`: `-11.783%`

## Preventive Task Quality

### model_scored_deterring

- `accepted_count`: `4`
- `completed_count`: `3`
- `dropped_count`: `1`
- `completion_rate`: `0.75`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.9877456722596447`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.9877456722596447`
- `predicted_deltaJ_mean`: `323712.467682465`
- `deltaJ_per_cost_mean`: `5630460.617190587`
- `accept_with_preempt_rate`: `0.25`
- `dropped_patrol_same_robot_at_accept_mean`: `0.25`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `96.66666666666667`

### patrolling

- `accepted_count`: `173`
- `completed_count`: `55`
- `dropped_count`: `114`
- `completion_rate`: `0.3179190751445087`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.10982658959537572`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `14.454545454545455`

### direct_detection_deterring

- `accepted_count`: `110`
- `completed_count`: `69`
- `dropped_count`: `34`
- `completion_rate`: `0.6272727272727273`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.00909090909090909`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `75.65217391304348`

## Comparative Quality

- `model_scored_minus_patrolling_future_truth_hit_rate`: `0.0`
- `model_scored_minus_patrolling_future_truth_count_mean`: `0.0`

## Critical Recommendations

- Preventive tasks are frequently taking over robot goals while response worsens; limit model-scored preemption or raise its score threshold.
- Closed-loop exposure is still worse than prediction-only; the current preventive policy is too disruptive or is placing tasks in low-yield regions.
