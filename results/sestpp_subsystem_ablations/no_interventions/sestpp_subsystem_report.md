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
- `intervention_prob`: `0.0`
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
|         0 |   2026 |           4971 |                              0 |                              0 |                                 0.0296 |                          0.0296 |                                                      0 |           3.53217e+07 |    3.53217e+07 |                     0 |
|         1 |   2027 |           4767 |                              0 |                              0 |                                 0.0259 |                          0.0259 |                                                      0 |           3.39464e+07 |    3.39464e+07 |                     0 |
|         2 |   2028 |           5082 |                              0 |                              0 |                                 0.0295 |                          0.0295 |                                                      0 |           3.59109e+07 |    3.59109e+07 |                     0 |
|         3 |   2029 |           4971 |                              0 |                              0 |                                 0.0276 |                          0.0276 |                                                      0 |           3.52e+07    |    3.52e+07    |                     0 |
|         4 |   2030 |           5132 |                              0 |                              0 |                                 0.0295 |                          0.0295 |                                                      0 |           3.63566e+07 |    3.63566e+07 |                     0 |
|         5 |   2031 |           5009 |                              0 |                              0 |                                 0.0298 |                          0.0298 |                                                      0 |           3.55564e+07 |    3.55564e+07 |                     0 |
|         6 |   2032 |           4817 |                              0 |                              0 |                                 0.0277 |                          0.0277 |                                                      0 |           3.44146e+07 |    3.44146e+07 |                     0 |
|         7 |   2033 |           5044 |                              0 |                              0 |                                 0.0302 |                          0.0302 |                                                      0 |           3.57897e+07 |    3.57897e+07 |                     0 |

## Aggregate deltas (proposed - prediction_only unless noted)

- `delta_forecast_recall_at_k_proposed_minus_prediction`: mean=0.000000, std=0.000000, n=8
- `delta_forecast_precision_at_k_proposed_minus_prediction`: mean=0.000000, std=0.000000, n=8
- `delta_forecast_hit_rate_proposed_minus_prediction`: mean=0.000000, std=0.000000, n=8
- `delta_forecast_lead_time_s_proposed_minus_prediction`: mean=0.000000, std=0.000000, n=8
- `delta_nll_proposed_minus_prediction`: mean=0.000000, std=0.000000, n=8
- `nll_improvement_pct`: mean=0.000000, std=0.000000, n=8
- `delta_mean_log_lambda_at_events_proposed_minus_prediction`: mean=0.000000, std=0.000000, n=8
- `delta_mean_lambda_at_events_proposed_minus_prediction`: mean=0.000000, std=0.000000, n=8

## Critical interpretation

- Proposed SESTPP is not consistently better in isolation yet.
- This indicates parameter mismatch or intervention replay realism issues, not only task-generation issues.
- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.
