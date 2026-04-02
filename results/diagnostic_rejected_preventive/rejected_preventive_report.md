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

- `count`: `300`
- `future_truth_hit_rate`: `0.6933333333333334`
- `future_truth_count_mean`: `0.9266666666666666`
- `recent_truth_count_mean`: `1.2233333333333334`
- `p_event_mean`: `0.8667467097430184`
- `predicted_deltaJ_mean`: `319178.4519242228`
- `deltaJ_per_cost_mean`: `2523614.07773713`
- `eta_s_mean`: `0.9862495282383259`

## Rejected By Reason

### busy_primary

- `count`: `292`
- `future_truth_hit_rate`: `0.6883561643835616`
- `future_truth_count_mean`: `0.9212328767123288`
- `recent_truth_count_mean`: `1.2191780821917808`
- `p_event_mean`: `0.8675708842574311`
- `predicted_deltaJ_mean`: `318884.6845468366`
- `deltaJ_per_cost_mean`: `2582450.3927743975`
- `eta_s_mean`: `0.981880940060323`

### task_cap

- `count`: `8`
- `future_truth_hit_rate`: `0.875`
- `future_truth_count_mean`: `1.125`
- `recent_truth_count_mean`: `1.375`
- `p_event_mean`: `0.8366643399669528`
- `predicted_deltaJ_mean`: `329900.9611988183`
- `deltaJ_per_cost_mean`: `376088.57887686347`
- `eta_s_mean`: `1.1457029967354337`

## Critical Recommendations

- Rejected `busy_primary` candidates have meaningful future-truth support; this filter may be too strict.
