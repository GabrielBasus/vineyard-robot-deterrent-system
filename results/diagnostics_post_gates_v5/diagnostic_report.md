# Proposed vs Prediction-Only Diagnostic Report

## Parameters Used

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
- `task_replan_period_s`: `45.0`
- `model_deterring_window_s`: `90.0`
- `model_deterring_risk_threshold`: `0.35`
- `model_deterring_budget_per_robot_per_hr`: `4`
- `model_deterring_min_recent_points`: `1`
- `forecast_horizon_s`: `300.0`
- `forecast_match_radius_m`: `20.0`
- `forecast_top_k`: `5`
- `forecast_eval_period_s`: `30.0`
- `telemetry_clear_on_start`: `False`
- `telemetry_prompt_save`: `False`

## Critical Recommendations

- Proposed communication is much higher: tighten boundary broadcast conditions or raise deterrence task admission threshold.
