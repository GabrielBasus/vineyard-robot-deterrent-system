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
- `model_deterring_chance_threshold`: `0.35`
- `model_deterring_min_deltaJ_per_cost`: `100000.0`
- `model_deterring_min_selection_weight`: `0.25`
- `model_deterring_capacity_rho_max`: `0.85`
- `model_deterring_score_margin`: `0.1`
- `model_deterring_global_admission_cap_per_cycle`: `1`
- `model_deterring_require_idle_robot_for_admission`: `False`
- `model_deterring_prefer_idle_robots_for_assignment`: `True`
- `model_deterring_busy_fallback_p_event_min`: `0.9`
- `model_deterring_busy_fallback_deltaJ_per_cost_min`: `1000000.0`
- `model_deterring_busy_fallback_eta_s_max`: `1.25`
- `protect_direct_detection_from_model_deterring`: `True`
- `protect_locked_model_deterring_from_patrol_assignment`: `True`
- `protect_active_model_deterring_persistence`: `True`
- `model_deterring_min_persistence_lifetime_s`: `180.0`
- `model_deterring_persistence_eta_multiplier`: `2.0`
- `model_deterring_persistence_buffer_s`: `60.0`
- `model_deterring_max_persistence_lifetime_s`: `420.0`
- `model_deterring_lock_near_goal_radius_m`: `10.0`
- `protect_active_model_deterring_goal_preemption`: `True`
- `model_deterring_direct_conflict_radius_m`: `35.0`
- `model_deterring_direct_conflict_window_s`: `120.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Comparison

- Exposure improvement vs `prediction_only`: `-1.561%`
- Response improvement vs `prediction_only`: `2.704%`

## Preventive Task Quality

### model_scored_deterring

- `accepted_count`: `2`
- `completed_count`: `2`
- `dropped_count`: `0`
- `completion_rate`: `1.0`
- `future_truth_hit_rate`: `0.5`
- `future_truth_count_mean`: `1.0`
- `recent_truth_count_mean`: `2.5`
- `p_event_mean`: `0.6424107179861231`
- `p_event_hit_mean`: `0.39937370589953547`
- `p_event_miss_mean`: `0.8854477300727107`
- `predicted_deltaJ_mean`: `300170.48529272655`
- `deltaJ_per_cost_mean`: `497372.59430844744`
- `selection_weight_mean`: `0.43299102312802346`
- `posterior_h1_mean`: `0.8665532923131827`
- `count_excess_ratio_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `0.0`

### patrolling

- `accepted_count`: `1054`
- `completed_count`: `378`
- `dropped_count`: `671`
- `completion_rate`: `0.3586337760910816`
- `future_truth_hit_rate`: `0.7172675521821632`
- `future_truth_count_mean`: `1.396584440227704`
- `recent_truth_count_mean`: `0.8481973434535104`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `selection_weight_mean`: `1.0`
- `posterior_h1_mean`: `nan`
- `count_excess_ratio_mean`: `nan`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `0.0`

### direct_detection_deterring

- `accepted_count`: `382`
- `completed_count`: `332`
- `dropped_count`: `46`
- `completion_rate`: `0.8691099476439791`
- `future_truth_hit_rate`: `0.725130890052356`
- `future_truth_count_mean`: `1.4528795811518325`
- `recent_truth_count_mean`: `1.9214659685863875`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `selection_weight_mean`: `1.0`
- `posterior_h1_mean`: `nan`
- `count_excess_ratio_mean`: `nan`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `0.0`

## Comparative Quality

- `model_scored_minus_patrolling_future_truth_hit_rate`: `-0.2172675521821632`
- `model_scored_minus_patrolling_future_truth_count_mean`: `-0.3965844402277039`

## Critical Recommendations

- Accepted model-scored tasks are landing in weaker locations than patrol tasks; tighten admission or re-rank preventive tasks by stronger future-event evidence.
- The accepted-task chance score is not separating hits from misses; recalibrate the chance mapping or gate on a stronger local truth proxy.
- Closed-loop exposure is still worse than prediction-only; the current preventive policy is too disruptive or is placing tasks in low-yield regions.
