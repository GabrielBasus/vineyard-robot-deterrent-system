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
- `model_deterring_direct_conflict_radius_m`: `35.0`
- `model_deterring_direct_conflict_window_s`: `120.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Comparison

- Exposure improvement vs `prediction_only`: `-1.959%`
- Response improvement vs `prediction_only`: `0.013%`

## Preventive Task Quality

### model_scored_deterring

- `accepted_count`: `2`
- `completed_count`: `1`
- `dropped_count`: `1`
- `completion_rate`: `0.5`
- `future_truth_hit_rate`: `0.5`
- `future_truth_count_mean`: `2.0`
- `recent_truth_count_mean`: `0.5`
- `p_event_mean`: `0.6424107179861231`
- `p_event_hit_mean`: `0.39937370589953547`
- `p_event_miss_mean`: `0.8854477300727107`
- `predicted_deltaJ_mean`: `300170.48529272655`
- `deltaJ_per_cost_mean`: `497372.59430844744`
- `accept_with_preempt_rate`: `0.5`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `0.0`

### patrolling

- `accepted_count`: `1054`
- `completed_count`: `370`
- `dropped_count`: `680`
- `completion_rate`: `0.3510436432637571`
- `future_truth_hit_rate`: `0.6963946869070209`
- `future_truth_count_mean`: `1.3453510436432639`
- `recent_truth_count_mean`: `0.8377609108159393`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `0.0`

### direct_detection_deterring

- `accepted_count`: `379`
- `completed_count`: `334`
- `dropped_count`: `43`
- `completion_rate`: `0.8812664907651715`
- `future_truth_hit_rate`: `0.7282321899736148`
- `future_truth_count_mean`: `1.5013192612137203`
- `recent_truth_count_mean`: `1.970976253298153`
- `p_event_mean`: `0.0`
- `p_event_hit_mean`: `0.0`
- `p_event_miss_mean`: `0.0`
- `predicted_deltaJ_mean`: `0.0`
- `deltaJ_per_cost_mean`: `0.0`
- `accept_with_preempt_rate`: `0.0`
- `dropped_patrol_same_robot_at_accept_mean`: `0.0`
- `dropped_direct_detection_same_robot_at_accept_mean`: `0.0`
- `time_to_complete_mean_s`: `0.0`

## Comparative Quality

- `model_scored_minus_patrolling_future_truth_hit_rate`: `-0.1963946869070209`
- `model_scored_minus_patrolling_future_truth_count_mean`: `0.6546489563567361`

## Critical Recommendations

- Accepted model-scored tasks are landing in weaker locations than patrol tasks; tighten admission or re-rank preventive tasks by stronger future-event evidence.
- Many accepted model-scored tasks do not complete; reduce ETA allowance or admit fewer preventive tasks so execution can keep up.
- The accepted-task chance score is not separating hits from misses; recalibrate the chance mapping or gate on a stronger local truth proxy.
- Closed-loop exposure is still worse than prediction-only; the current preventive policy is too disruptive or is placing tasks in low-yield regions.
