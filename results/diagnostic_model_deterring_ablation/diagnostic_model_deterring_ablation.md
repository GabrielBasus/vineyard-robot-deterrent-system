# Model-Scored Deterring Ablation

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
- `model_deterring_window_s`: `120.0`
- `model_deterring_gate_policy`: `sprt_capacity`
- `model_deterring_sprt_alpha`: `0.25`
- `model_deterring_sprt_beta`: `0.4`
- `model_deterring_sprt_patch_radius_m`: `30.0`
- `model_deterring_min_sprt_margin`: `1.25`
- `model_deterring_chance_threshold`: `0.35`
- `model_deterring_min_deltaJ_per_cost`: `100000.0`
- `model_deterring_min_selection_weight`: `0.0`
- `model_deterring_capacity_rho_max`: `0.85`
- `model_deterring_global_admission_cap_per_cycle`: `1`
- `model_deterring_prefer_idle_robots_for_assignment`: `True`
- `model_deterring_busy_fallback_p_event_min`: `0.9`
- `model_deterring_busy_fallback_deltaJ_per_cost_min`: `1000000.0`
- `model_deterring_busy_fallback_eta_s_max`: `1.25`
- `protect_direct_detection_from_model_deterring`: `True`
- `protect_locked_model_deterring_from_patrol_assignment`: `True`
- `model_deterring_persistence_eta_multiplier`: `2.0`
- `model_deterring_persistence_buffer_s`: `60.0`
- `model_deterring_max_persistence_lifetime_s`: `420.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `forecast_horizon_s`: `300.0`
- `forecast_match_radius_m`: `20.0`
- `forecast_top_k`: `5`
- `forecast_eval_period_s`: `30.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Final Metrics

### prediction_only

- `value_weighted_exposure`: `17525.534809250283`
- `mean_response_time_s`: `119.57028302052986`
- `boundary_message_count`: `297.0`
- `forecast_recall_at_k`: `nan`
- `forecast_precision_at_k`: `0.0`
- `model_deterring_generated`: `0.0`
- `model_deterring_accepted`: `0.0`
- `deterring_actions_completed_model_scored`: `0.0`
- `deterring_actions_completed_total`: `360.0`
- `patrolling_actions_completed`: `nan`

### proposed_no_model_deterring

- `value_weighted_exposure`: `17489.887312961637`
- `mean_response_time_s`: `116.786271936854`
- `boundary_message_count`: `616.0`
- `forecast_recall_at_k`: `nan`
- `forecast_precision_at_k`: `0.0`
- `model_deterring_generated`: `0.0`
- `model_deterring_accepted`: `0.0`
- `deterring_actions_completed_model_scored`: `0.0`
- `deterring_actions_completed_total`: `392.0`
- `patrolling_actions_completed`: `nan`

### proposed_full

- `value_weighted_exposure`: `17651.60344924305`
- `mean_response_time_s`: `119.19761741526192`
- `boundary_message_count`: `455.0`
- `forecast_recall_at_k`: `nan`
- `forecast_precision_at_k`: `0.0`
- `model_deterring_generated`: `2.0`
- `model_deterring_accepted`: `0.0`
- `deterring_actions_completed_model_scored`: `0.0`
- `deterring_actions_completed_total`: `377.0`
- `patrolling_actions_completed`: `nan`

## Pairwise Comparisons

### proposed_full_vs_prediction_only

- `exposure_improve_pct`: `-0.7193426127357198`
- `response_improve_pct`: `0.31167075618944107`
- `comm_increase_pct`: `53.1986531986532`

### proposed_no_model_deterring_vs_prediction_only

- `exposure_improve_pct`: `0.20340318670235705`
- `response_improve_pct`: `2.3283469883548267`
- `comm_increase_pct`: `107.4074074074074`

### proposed_full_vs_proposed_no_model_deterring

- `exposure_improve_pct`: `-0.9246265192433127`
- `response_improve_pct`: `-2.064750795120609`
- `comm_increase_pct`: `-26.136363636363637`

## Conclusions

- The intervention-aware field helps on its own, but model-scored preventive deterring is reducing net exposure performance.
- Model-scored preventive deterring is currently hurting response time relative to the same proposed field without it.
