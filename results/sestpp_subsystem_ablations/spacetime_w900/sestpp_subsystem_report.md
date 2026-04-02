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
- `shuffle_time_window_s`: `900.0`
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
|         0 |   2026 |           4867 |                            286 |                            286 |                                 0.0291 |                          0.029  |                                                -0.0001 |           3.45871e+07 |    3.23318e+07 |                6.5208 |
|         1 |   2027 |           4805 |                            285 |                            285 |                                 0.0282 |                          0.0284 |                                                 0.0002 |           3.40797e+07 |    3.18584e+07 |                6.5181 |
|         2 |   2028 |           5029 |                            285 |                            285 |                                 0.0287 |                          0.0282 |                                                -0.0005 |           3.5657e+07  |    3.33523e+07 |                6.4634 |
|         3 |   2029 |           4968 |                            289 |                            289 |                                 0.0313 |                          0.0305 |                                                -0.0007 |           3.53076e+07 |    3.3034e+07  |                6.4393 |
|         4 |   2030 |           5014 |                            288 |                            289 |                                 0.0267 |                          0.0269 |                                                 0.0002 |           3.55339e+07 |    3.32026e+07 |                6.5606 |
|         5 |   2031 |           4881 |                            285 |                            285 |                                 0.027  |                          0.0274 |                                                 0.0004 |           3.43337e+07 |    3.20646e+07 |                6.609  |
|         6 |   2032 |           4777 |                            284 |                            284 |                                 0.0297 |                          0.0295 |                                                -0.0001 |           3.38393e+07 |    3.16003e+07 |                6.6167 |
|         7 |   2033 |           4940 |                            287 |                            287 |                                 0.0293 |                          0.03   |                                                 0.0006 |           3.47469e+07 |    3.2481e+07  |                6.5211 |

## Aggregate deltas (proposed - prediction_only unless noted)

- `delta_forecast_recall_at_k_proposed_minus_prediction`: mean=0.000010, std=0.000425, n=8
- `delta_forecast_precision_at_k_proposed_minus_prediction`: mean=-0.000069, std=0.005312, n=8
- `delta_forecast_hit_rate_proposed_minus_prediction`: mean=0.002083, std=0.005851, n=8
- `delta_forecast_lead_time_s_proposed_minus_prediction`: mean=0.216684, std=1.230930, n=8
- `delta_nll_proposed_minus_prediction`: mean=-2270022.005861, std=32638.618273, n=8
- `nll_improvement_pct`: mean=6.531118, std=0.058793, n=8
- `delta_mean_log_lambda_at_events_proposed_minus_prediction`: mean=-0.516049, std=0.038276, n=8
- `delta_mean_lambda_at_events_proposed_minus_prediction`: mean=-0.000840, std=0.000042, n=8

## Critical interpretation

- Proposed SESTPP is not consistently better in isolation yet.
- This indicates parameter mismatch or intervention replay realism issues, not only task-generation issues.
- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.
