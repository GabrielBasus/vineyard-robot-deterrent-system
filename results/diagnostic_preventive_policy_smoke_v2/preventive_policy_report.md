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
- `protect_direct_detection_from_model_deterring`: `True`
- `model_deterring_direct_conflict_radius_m`: `35.0`
- `model_deterring_direct_conflict_window_s`: `120.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Comparison

- Exposure improvement vs `prediction_only`: `-5.830%`
- Response improvement vs `prediction_only`: `-5.210%`

## Preventive Task Quality

### model_scored_deterring

- `accepted_count`: `6`
- `completed_count`: `0`
- `dropped_count`: `6`
- `completion_rate`: `0.0`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.9042611112105696`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.9042611112105696`
- `predicted_deltaJ_mean`: `326740.39530875563`
- `deltaJ_per_cost_mean`: `4223208.850671715`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.3333333333333333`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.3333333333333333`
- `time_to_complete_mean_s`: `nan`

### patrolling

- `accepted_count`: `173`
- `completed_count`: `59`
- `dropped_count`: `109`
- `completion_rate`: `0.34104046242774566`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.06358381502890173`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `10.508474576271187`

### direct_detection_deterring

- `accepted_count`: `94`
- `completed_count`: `59`
- `dropped_count`: `27`
- `completion_rate`: `0.6276595744680851`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.010638297872340425`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `nan`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `73.64406779661017`

## Comparative Quality

- `model_scored_minus_patrolling_future_truth_hit_rate`: `0.0`
- `model_scored_minus_patrolling_future_truth_count_mean`: `0.0`

## Critical Recommendations

- Many accepted model-scored tasks do not complete; reduce ETA allowance or admit fewer preventive tasks so execution can keep up.
- Closed-loop exposure is still worse than prediction-only; the current preventive policy is too disruptive or is placing tasks in low-yield regions.
