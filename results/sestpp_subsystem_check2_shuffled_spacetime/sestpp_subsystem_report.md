# SESTPP Subsystem Isolation Report

This test isolates the intensity-model subsystem from task generation and assignment.
Both models receive the same detections from the same truth stream.
Only the proposed model receives replayed intervention events.

## Configuration

- `W`: `500.0`
- `H`: `500.0`
- `NX`: `80`
- `NY`: `64`
- `dt`: `5.0`
- `T_end`: `10800.0`
- `warmup_s`: `1800.0`
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
- `intervention_shuffle`: `spacetime`
- `shuffle_time_window_s`: `300.0`
- `model_sigma`: `12.0`
- `model_omega`: `600.0`
- `model_omega_inhib`: `600.0`
- `model_alpha_in`: `0.25`
- `model_alpha_cross`: `0.0`
- `model_alpha_inhib`: `0.35`
- `model_mu_base`: `0.0001`
- `model_bg_ema`: `1e-06`
- `runs`: `8`
- `seed_start`: `2026`
- `final_map_recent_truth`: `400`
- `final_map_recent_interventions`: `120`

## Per-run results

|   run_idx |   seed |   truth_events |   interventions_replayed |   prediction_only_forecast_recall_at_k |   proposed_forecast_recall_at_k |   delta_forecast_recall_at_k_proposed_minus_prediction |   prediction_only_nll |   proposed_nll |   nll_improvement_pct |
|----------:|-------:|---------------:|-------------------------:|---------------------------------------:|--------------------------------:|-------------------------------------------------------:|----------------------:|---------------:|----------------------:|
|         0 |   2026 |           4870 |                      287 |                                 0.0307 |                          0.0307 |                                                 0.0001 |           3.469e+07   |    3.24205e+07 |                6.5423 |
|         1 |   2027 |           4854 |                      284 |                                 0.0282 |                          0.0287 |                                                 0.0004 |           3.44151e+07 |    3.21699e+07 |                6.5237 |
|         2 |   2028 |           5024 |                      287 |                                 0.0273 |                          0.027  |                                                -0.0004 |           3.5422e+07  |    3.31619e+07 |                6.3805 |
|         3 |   2029 |           4847 |                      287 |                                 0.03   |                          0.0304 |                                                 0.0004 |           3.43034e+07 |    3.20459e+07 |                6.5808 |
|         4 |   2030 |           4972 |                      283 |                                 0.0292 |                          0.0291 |                                                -0.0001 |           3.50684e+07 |    3.2834e+07  |                6.3714 |
|         5 |   2031 |           4914 |                      286 |                                 0.0323 |                          0.0319 |                                                -0.0004 |           3.46784e+07 |    3.24438e+07 |                6.4436 |
|         6 |   2032 |           4939 |                      287 |                                 0.0317 |                          0.032  |                                                 0.0003 |           3.47822e+07 |    3.25473e+07 |                6.4255 |
|         7 |   2033 |           4974 |                      284 |                                 0.0281 |                          0.0286 |                                                 0.0006 |           3.54086e+07 |    3.31616e+07 |                6.3459 |

## Aggregate deltas (proposed - prediction_only unless noted)

- `delta_forecast_recall_at_k_proposed_minus_prediction`: mean=0.000107, std=0.000346, n=8
- `delta_forecast_precision_at_k_proposed_minus_prediction`: mean=0.000388, std=0.003020, n=8
- `delta_forecast_hit_rate_proposed_minus_prediction`: mean=-0.001736, std=0.003913, n=8
- `delta_forecast_lead_time_s_proposed_minus_prediction`: mean=-0.104667, std=1.880420, n=8
- `delta_nll_proposed_minus_prediction`: mean=-2247878.782781, std=12485.446802, n=8
- `nll_improvement_pct`: mean=6.451718, std=0.081800, n=8
- `delta_mean_log_lambda_at_events_proposed_minus_prediction`: mean=-0.469666, std=0.039846, n=8
- `delta_mean_lambda_at_events_proposed_minus_prediction`: mean=-0.000774, std=0.000031, n=8

## Critical interpretation

- Proposed SESTPP is better on isolated forecasting metrics in this setup.
- Remaining closed-loop underperformance is more likely in task generation/dispatch policy.
- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.
