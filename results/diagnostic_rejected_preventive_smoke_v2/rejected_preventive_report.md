# Rejected Preventive Candidate Diagnostic

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
- `emit_rejected_model_det_debug`: `True`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Accepted Model-Scored Summary

- `count`: `0`
- `future_truth_hit_rate`: `nan`
- `future_truth_count_mean`: `nan`
- `recent_truth_count_mean`: `nan`
- `p_event_mean`: `nan`
- `predicted_deltaJ_mean`: `nan`
- `deltaJ_per_cost_mean`: `nan`
- `eta_s_mean`: `nan`

## Rejected Model-Scored Summary

- `count`: `107`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.9258749673857469`
- `predicted_deltaJ_mean`: `321166.5040028721`
- `deltaJ_per_cost_mean`: `4662902.8606095305`
- `eta_s_mean`: `1.169439048324167`

## Rejected By Reason

### busy_primary

- `count`: `106`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.9251756746252353`
- `predicted_deltaJ_mean`: `321047.64541054395`
- `deltaJ_per_cost_mean`: `4704997.374746768`
- `eta_s_mean`: `1.1647971448090975`

### task_cap

- `count`: `1`
- `future_truth_hit_rate`: `0.0`
- `future_truth_count_mean`: `0.0`
- `recent_truth_count_mean`: `0.0`
- `p_event_mean`: `0.9999999999999842`
- `predicted_deltaJ_mean`: `333765.5147896675`
- `deltaJ_per_cost_mean`: `200884.36206236045`
- `eta_s_mean`: `1.661480820921525`

## Critical Recommendations

- Rejected preventive candidates are not obviously higher-yield than accepted ones; keeping the conservative filters is justified for now.
