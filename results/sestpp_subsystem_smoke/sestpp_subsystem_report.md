# SESTPP Subsystem Isolation Report

This test isolates the intensity-model subsystem from task generation and assignment.
Both models receive the same detections from the same truth stream.
Only the proposed model receives replayed intervention events.

## Configuration

- `W`: `500.0`
- `H`: `500.0`
- `NX`: `80`
- `NY`: `64`
- `dt`: `10.0`
- `T_end`: `1800.0`
- `warmup_s`: `600.0`
- `eval_period_s`: `30.0`
- `forecast_horizon_s`: `300.0`
- `forecast_top_k`: `5`
- `match_radius_m`: `20.0`
- `mu_true`: `1e-06`
- `alpha_true`: `0.3`
- `omega_true`: `600.0`
- `sigma_true`: `12.0`
- `beta_true`: `0.3`
- `row_spacing_m`: `4.8`
- `row_gain`: `1.5`
- `edge_gain`: `0.6`
- `edge_scale_m`: `35.0`
- `intervention_prob`: `0.45`
- `intervention_cooldown_s`: `40.0`
- `intervention_delay_s`: `10.0`
- `intervention_sigma`: `12.0`
- `intervention_omega`: `600.0`
- `model_sigma`: `12.0`
- `model_omega`: `600.0`
- `model_omega_inhib`: `600.0`
- `model_alpha_in`: `0.25`
- `model_alpha_cross`: `0.0`
- `model_alpha_inhib`: `0.35`
- `model_mu_base`: `0.0001`
- `model_bg_ema`: `1e-06`
- `runs`: `2`
- `seed_start`: `2026`
- `final_map_recent_truth`: `400`
- `final_map_recent_interventions`: `120`

## Per-run results

|   run_idx |   seed |   truth_events |   interventions_replayed |   prediction_only_forecast_recall_at_k |   proposed_forecast_recall_at_k |   delta_forecast_recall_at_k_proposed_minus_prediction |   prediction_only_nll |   proposed_nll |   nll_improvement_pct |
|----------:|-------:|---------------:|-------------------------:|---------------------------------------:|--------------------------------:|-------------------------------------------------------:|----------------------:|---------------:|----------------------:|
|         0 |   2026 |            623 |                       54 |                                 0.0314 |                           0.035 |                                                 0.0036 |           3.73467e+06 |    3.37771e+06 |                9.5579 |
|         1 |   2027 |            635 |                       52 |                                 0.0306 |                           0.031 |                                                 0.0005 |           3.76822e+06 |    3.42952e+06 |                8.9882 |

## Aggregate deltas (proposed - prediction_only unless noted)

- `delta_forecast_recall_at_k_proposed_minus_prediction`: mean=0.002024, std=0.001549, n=2
- `delta_forecast_precision_at_k_proposed_minus_prediction`: mean=0.019722, std=0.009722, n=2
- `delta_forecast_hit_rate_proposed_minus_prediction`: mean=0.000000, std=0.033333, n=2
- `delta_forecast_lead_time_s_proposed_minus_prediction`: mean=2.921387, std=5.195855, n=2
- `delta_nll_proposed_minus_prediction`: mean=-347824.634563, std=9131.162023, n=2
- `nll_improvement_pct`: mean=9.273029, std=0.284866, n=2
- `delta_mean_log_lambda_at_events_proposed_minus_prediction`: mean=-0.523831, std=0.009959, n=2
- `delta_mean_lambda_at_events_proposed_minus_prediction`: mean=-0.000839, std=0.000034, n=2

## Critical interpretation

- Proposed SESTPP is better on isolated forecasting metrics in this setup.
- Remaining closed-loop underperformance is more likely in task generation/dispatch policy.
- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.
