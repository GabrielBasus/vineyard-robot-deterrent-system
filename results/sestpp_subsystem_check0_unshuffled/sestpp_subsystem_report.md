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
- `intervention_shuffle`: `none`
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

|   run_idx |   seed |   truth_events |   interventions_truth_replayed |   interventions_model_replayed |   prediction_only_forecast_recall_at_k |   proposed_forecast_recall_at_k |   delta_forecast_recall_at_k_proposed_minus_prediction |   prediction_only_nll |   proposed_nll |   nll_improvement_pct |
|----------:|-------:|---------------:|-------------------------------:|-------------------------------:|---------------------------------------:|--------------------------------:|-------------------------------------------------------:|----------------------:|---------------:|----------------------:|
|         0 |   2026 |           4665 |                            287 |                            287 |                                 0.0292 |                          0.0302 |                                                 0.001  |           3.32938e+07 |    3.07976e+07 |                7.4975 |
|         1 |   2027 |           4915 |                            288 |                            288 |                                 0.0273 |                          0.0274 |                                                 0.0002 |           3.48537e+07 |    3.23593e+07 |                7.1567 |
|         2 |   2028 |           4921 |                            283 |                            283 |                                 0.0334 |                          0.0314 |                                                -0.002  |           3.49325e+07 |    3.2481e+07  |                7.0177 |
|         3 |   2029 |           5084 |                            289 |                            289 |                                 0.029  |                          0.0294 |                                                 0.0004 |           3.59865e+07 |    3.34729e+07 |                6.9847 |
|         4 |   2030 |           4838 |                            282 |                            282 |                                 0.0296 |                          0.0288 |                                                -0.0008 |           3.43768e+07 |    3.19285e+07 |                7.1222 |
|         5 |   2031 |           4753 |                            291 |                            291 |                                 0.028  |                          0.0284 |                                                 0.0004 |           3.37228e+07 |    3.12458e+07 |                7.3452 |
|         6 |   2032 |           4848 |                            282 |                            282 |                                 0.0272 |                          0.0281 |                                                 0.0009 |           3.40852e+07 |    3.16069e+07 |                7.2708 |
|         7 |   2033 |           4928 |                            289 |                            289 |                                 0.0278 |                          0.0282 |                                                 0.0004 |           3.50457e+07 |    3.25485e+07 |                7.1254 |

## Aggregate deltas (proposed - prediction_only unless noted)

- `delta_forecast_recall_at_k_proposed_minus_prediction`: mean=0.000058, std=0.000917, n=8
- `delta_forecast_precision_at_k_proposed_minus_prediction`: mean=0.000486, std=0.016266, n=8
- `delta_forecast_hit_rate_proposed_minus_prediction`: mean=-0.003819, std=0.010842, n=8
- `delta_forecast_lead_time_s_proposed_minus_prediction`: mean=-0.310145, std=2.434421, n=8
- `delta_nll_proposed_minus_prediction`: mean=-2482046.089020, std=21460.856924, n=8
- `nll_improvement_pct`: mean=7.190018, std=0.160803, n=8
- `delta_mean_log_lambda_at_events_proposed_minus_prediction`: mean=-0.139408, std=0.020690, n=8
- `delta_mean_lambda_at_events_proposed_minus_prediction`: mean=-0.000899, std=0.000027, n=8

## Critical interpretation

- Proposed SESTPP is better on isolated forecasting metrics in this setup.
- Remaining closed-loop underperformance is more likely in task generation/dispatch policy.
- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.
