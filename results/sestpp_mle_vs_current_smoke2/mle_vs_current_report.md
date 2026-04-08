# SESTPP MLE vs Current

This benchmark fits a maximum-likelihood-style version of the current SESTPP on the warmup segment, then compares held-out realism metrics against the current fixed-parameter model.
Both models use the same SESTPP structure from `SESTPP.py`; only the parameter estimation method differs.

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
- `mle_maxiter`: `8`
- `mle_restarts`: `1`

## Interpretation

- Better training NLL alone is not enough; realism should be judged mainly by held-out `eval_nll`, field log loss, field Brier, and forecast metrics.
- Negative `delta_*_mle_minus_current` is better for losses and positive is better for recall or precision.
- On synthetic truth, this measures realism with respect to the simulator, not necessarily real-world vineyard behavior.

## Per-Run Snapshot

|   run_idx |   seed |   truth_events |   current_fixed_train_nll |   mle_fitted_train_nll |   delta_train_nll_mle_minus_current |   current_fixed_eval_nll |   mle_fitted_eval_nll |   delta_eval_nll_mle_minus_current |   current_fixed_field_logloss |   mle_fitted_field_logloss |   delta_field_logloss_mle_minus_current |   current_fixed_forecast_recall_at_k |   mle_fitted_forecast_recall_at_k |   delta_forecast_recall_at_k_mle_minus_current |
|----------:|-------:|---------------:|--------------------------:|-----------------------:|------------------------------------:|-------------------------:|----------------------:|-----------------------------------:|------------------------------:|---------------------------:|----------------------------------------:|-------------------------------------:|----------------------------------:|-----------------------------------------------:|
|         0 |   2026 |            282 |                  101940   |                1345.82 |                           -100594   |              1.16562e+06 |               5313.82 |                       -1.16031e+06 |                       14.654  |                     0.1016 |                                -14.5524 |                               0.0531 |                            0.0117 |                                        -0.0415 |
|         1 |   2027 |            297 |                   96755.8 |                1022.54 |                            -95733.2 |              1.19268e+06 |               5656.3  |                       -1.18702e+06 |                       14.6999 |                     0.1097 |                                -14.5902 |                               0.033  |                            0.0201 |                                        -0.0129 |

## Aggregate Summary

| metric                                          |             mean |          std |         ci95 |   n |
|:------------------------------------------------|-----------------:|-------------:|-------------:|----:|
| delta_train_nll_mle_minus_current               | -98163.9         |  2430.61     |  3368.65     |   2 |
| delta_eval_nll_mle_minus_current                |     -1.17366e+06 | 13354.7      | 18508.7      |   2 |
| delta_field_brier_mle_minus_current             |     -0.835851    |     0.002555 |     0.003541 |   2 |
| delta_field_logloss_mle_minus_current           |    -14.5713      |     0.01888  |     0.026166 |   2 |
| delta_field_rate_l1_mle_minus_current           |     -0.001633    |     3e-06    |     4e-06    |   2 |
| delta_forecast_recall_at_k_mle_minus_current    |     -0.027166    |     0.014288 |     0.019802 |   2 |
| delta_forecast_precision_at_k_mle_minus_current |     -0.102778    |     0.083889 |     0.116264 |   2 |
| delta_forecast_hit_rate_mle_minus_current       |     -0.266667    |     0.266667 |     0.369581 |   2 |
| delta_forecast_lead_time_s_mle_minus_current    |     -2.836       |     8.08653  |    11.2074   |   2 |
| train_nll_improvement_pct                       |     98.8115      |     0.131691 |     0.182515 |   2 |
| eval_nll_improvement_pct                        |     99.5349      |     0.009188 |     0.012734 |   2 |
| field_brier_improvement_pct                     |     98.784       |     0.039356 |     0.054545 |   2 |
| field_logloss_improvement_pct                   |     99.28        |     0.026568 |     0.036821 |   2 |
| field_rate_l1_improvement_pct                   |     99.7897      |     5.6e-05  |     7.8e-05  |   2 |

## Readout

- The MLE-fitted model improved held-out calibration, but hotspot metrics are not uniformly better yet.
- If you want to claim real-world realism, replace the synthetic truth stream with held-out logged field detections and interventions.

