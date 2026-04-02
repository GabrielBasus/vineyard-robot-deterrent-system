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
- `intervention_shuffle`: `space`
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
|         0 |   2026 |           4872 |                            289 |                            289 |                                 0.0295 |                          0.0296 |                                                 0      |           3.46782e+07 |    3.23412e+07 |                6.739  |
|         1 |   2027 |           4914 |                            286 |                            286 |                                 0.0274 |                          0.0271 |                                                -0.0002 |           3.48141e+07 |    3.25618e+07 |                6.4694 |
|         2 |   2028 |           4882 |                            285 |                            285 |                                 0.0275 |                          0.0279 |                                                 0.0004 |           3.44845e+07 |    3.22071e+07 |                6.6041 |
|         3 |   2029 |           4915 |                            286 |                            286 |                                 0.032  |                          0.0333 |                                                 0.0012 |           3.47528e+07 |    3.24883e+07 |                6.5162 |
|         4 |   2030 |           4907 |                            292 |                            292 |                                 0.0321 |                          0.0307 |                                                -0.0014 |           3.4658e+07  |    3.23506e+07 |                6.6577 |
|         5 |   2031 |           4896 |                            288 |                            288 |                                 0.031  |                          0.0318 |                                                 0.0009 |           3.47122e+07 |    3.24051e+07 |                6.6462 |
|         6 |   2032 |           4973 |                            288 |                            288 |                                 0.0301 |                          0.0311 |                                                 0.001  |           3.50871e+07 |    3.27972e+07 |                6.5264 |
|         7 |   2033 |           4995 |                            287 |                            287 |                                 0.0279 |                          0.0283 |                                                 0.0003 |           3.52852e+07 |    3.30274e+07 |                6.3985 |

## Aggregate deltas (proposed - prediction_only unless noted)

- `delta_forecast_recall_at_k_proposed_minus_prediction`: mean=0.000298, std=0.000789, n=8
- `delta_forecast_precision_at_k_proposed_minus_prediction`: mean=0.000394, std=0.009814, n=8
- `delta_forecast_hit_rate_proposed_minus_prediction`: mean=0.005208, std=0.003788, n=8
- `delta_forecast_lead_time_s_proposed_minus_prediction`: mean=-0.376977, std=1.238838, n=8
- `delta_nll_proposed_minus_prediction`: mean=-2286666.015992, std=27348.791609, n=8
- `nll_improvement_pct`: mean=6.569700, std=0.104620, n=8
- `delta_mean_log_lambda_at_events_proposed_minus_prediction`: mean=-0.500682, std=0.045523, n=8
- `delta_mean_lambda_at_events_proposed_minus_prediction`: mean=-0.000837, std=0.000029, n=8

## Critical interpretation

- Proposed SESTPP is better on isolated forecasting metrics in this setup.
- Remaining closed-loop underperformance is more likely in task generation/dispatch policy.
- This subsystem test is necessary but not sufficient for thesis claims; keep full baseline experiments.
