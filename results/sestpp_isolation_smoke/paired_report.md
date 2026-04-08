# SESTPP Isolation Benchmark

This benchmark compares the current mainline SESTPP against the sandbox copy in `sestpp_isolation/model.py`.
Both models receive the same truth stream, detections, and intervention replay on matched seeds.

## Configuration

- `W`: `500.0`
- `H`: `500.0`
- `NX`: `80`
- `NY`: `64`
- `dt`: `5.0`
- `T_end`: `900.0`
- `warmup_s`: `300.0`
- `eval_period_s`: `60.0`
- `forecast_horizon_s`: `180.0`
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
- `model_omega_inhib`: `900.0`
- `model_alpha_in`: `0.25`
- `model_alpha_cross`: `0.0`
- `model_alpha_inhib`: `0.45`
- `model_mu_base`: `5e-05`
- `model_bg_ema`: `1e-06`
- `runs`: `2`
- `seed_start`: `2026`

## Interpretation

- Negative `delta_*_sandbox_minus_mainline` is better for loss metrics such as Brier, log loss, rate L1, and NLL.
- Positive `delta_*_sandbox_minus_mainline` is better for recall, precision, and hit rate.
- Positive `*_improvement_pct` means the sandbox beat the current mainline model on that loss metric.

## Per-Run Snapshot

|   run_idx |   seed |   truth_events |   interventions_replayed |   mainline_field_logloss |   sandbox_field_logloss |   delta_field_logloss_sandbox_minus_mainline |   mainline_nll |   sandbox_nll |   delta_nll_sandbox_minus_mainline |   mainline_forecast_recall_at_k |   sandbox_forecast_recall_at_k |   delta_forecast_recall_at_k_sandbox_minus_mainline |
|----------:|-------:|---------------:|-------------------------:|-------------------------:|------------------------:|---------------------------------------------:|---------------:|--------------:|-----------------------------------:|--------------------------------:|-------------------------------:|----------------------------------------------------:|
|         0 |   2026 |            282 |                       21 |                  14.654  |                 14.654  |                                            0 |    1.16901e+06 |   1.16901e+06 |                                  0 |                          0.0531 |                         0.0531 |                                                   0 |
|         1 |   2027 |            297 |                       21 |                  14.6999 |                 14.6999 |                                            0 |    1.19546e+06 |   1.19546e+06 |                                  0 |                          0.033  |                         0.033  |                                                   0 |

## Aggregate Summary

| metric                                               |   mean |   std |   ci95 |   n |
|:-----------------------------------------------------|-------:|------:|-------:|----:|
| delta_field_brier_sandbox_minus_mainline             |      0 |     0 |      0 |   2 |
| delta_field_logloss_sandbox_minus_mainline           |      0 |     0 |      0 |   2 |
| delta_field_rate_l1_sandbox_minus_mainline           |      0 |     0 |      0 |   2 |
| delta_nll_sandbox_minus_mainline                     |      0 |     0 |      0 |   2 |
| delta_forecast_recall_at_k_sandbox_minus_mainline    |      0 |     0 |      0 |   2 |
| delta_forecast_precision_at_k_sandbox_minus_mainline |      0 |     0 |      0 |   2 |
| delta_forecast_hit_rate_sandbox_minus_mainline       |      0 |     0 |      0 |   2 |
| delta_forecast_lead_time_s_sandbox_minus_mainline    |      0 |     0 |      0 |   2 |
| field_brier_improvement_pct                          |      0 |     0 |      0 |   2 |
| field_logloss_improvement_pct                        |      0 |     0 |      0 |   2 |
| field_rate_l1_improvement_pct                        |      0 |     0 |      0 |   2 |
| nll_improvement_pct                                  |      0 |     0 |      0 |   2 |

## Readout

- The sandbox changes did not beat the mainline model on the primary isolated metrics in this run set.
- If the sandbox and mainline models are still identical, the deltas should stay near zero. Use that as a smoke check.

