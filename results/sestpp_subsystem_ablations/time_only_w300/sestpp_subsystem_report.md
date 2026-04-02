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
- `intervention_shuffle`: `time`
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
|         0 |   2026 |           4704 |                            287 |                            287 |                                 0.0271 |                          0.0277 |                                                 0.0006 |           3.33861e+07 |    3.09166e+07 |                7.3968 |
|         1 |   2027 |           5005 |                            288 |                            288 |                                 0.0272 |                          0.0271 |                                                -0.0001 |           3.52739e+07 |    3.27628e+07 |                7.1188 |
|         2 |   2028 |           4935 |                            288 |                            288 |                                 0.0291 |                          0.0293 |                                                 0.0002 |           3.48815e+07 |    3.23838e+07 |                7.1607 |
|         3 |   2029 |           5132 |                            289 |                            290 |                                 0.0287 |                          0.0292 |                                                 0.0005 |           3.62717e+07 |    3.37638e+07 |                6.9141 |
|         4 |   2030 |           4840 |                            285 |                            285 |                                 0.0294 |                          0.0292 |                                                -0.0002 |           3.42829e+07 |    3.18085e+07 |                7.2175 |
|         5 |   2031 |           5048 |                            283 |                            283 |                                 0.0324 |                          0.0323 |                                                -0.0001 |           3.58586e+07 |    3.34224e+07 |                6.794  |
|         6 |   2032 |           4791 |                            286 |                            286 |                                 0.0303 |                          0.0306 |                                                 0.0003 |           3.38756e+07 |    3.14295e+07 |                7.2206 |
|         7 |   2033 |           4946 |                            284 |                            284 |                                 0.0314 |                          0.0309 |                                                -0.0006 |           3.50919e+07 |    3.26136e+07 |                7.0622 |

## Aggregate deltas (proposed - prediction_only unless noted)

- `delta_forecast_recall_at_k_proposed_minus_prediction`: mean=0.000086, std=0.000370, n=8
- `delta_forecast_precision_at_k_proposed_minus_prediction`: mean=-0.002008, std=0.009852, n=8
- `delta_forecast_hit_rate_proposed_minus_prediction`: mean=0.000694, std=0.011002, n=8
- `delta_forecast_lead_time_s_proposed_minus_prediction`: mean=-0.002773, std=2.812448, n=8
- `delta_nll_proposed_minus_prediction`: mean=-2477638.958723, std=25566.289449, n=8
- `nll_improvement_pct`: mean=7.110599, std=0.176493, n=8
- `delta_mean_log_lambda_at_events_proposed_minus_prediction`: mean=-0.171116, std=0.010692, n=8
- `delta_mean_lambda_at_events_proposed_minus_prediction`: mean=-0.000901, std=0.000036, n=8

## Critical interpretation

- Proposed SESTPP is not consistently better in isolation yet.
- This indicates parameter mismatch or intervention replay realism issues, not only task-generation issues.
- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.
