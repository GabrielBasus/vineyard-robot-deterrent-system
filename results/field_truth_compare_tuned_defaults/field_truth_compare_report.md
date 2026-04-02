# Field-Level Truth-vs-Model Forecast Report

This diagnostic compares forecast probability fields against realized future truth occupancy fields.
Model lambda is converted to a per-cell horizon event probability with a Poisson approximation.
Truth is represented as realized occupied cells in the future horizon, not the latent closed-form Hawkes probability field.

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
- `model_omega_inhib`: `900.0`
- `model_alpha_in`: `0.25`
- `model_alpha_cross`: `0.0`
- `model_alpha_inhib`: `0.45`
- `model_mu_base`: `5e-05`
- `model_bg_ema`: `1e-06`
- `runs`: `8`
- `seed_start`: `2026`
- `final_map_recent_truth`: `400`
- `final_map_recent_interventions`: `120`

## Per-run results

|   run_idx |   seed |   truth_events |   prediction_only_field_brier |   proposed_field_brier |   delta_field_brier_proposed_minus_prediction |   prediction_only_field_logloss |   proposed_field_logloss |   delta_field_logloss_proposed_minus_prediction |   prediction_only_nll |   proposed_nll |   delta_nll_proposed_minus_prediction |   brier_improvement_pct |   logloss_improvement_pct |   nll_improvement_pct |
|----------:|-------:|---------------:|------------------------------:|-----------------------:|----------------------------------------------:|--------------------------------:|-------------------------:|------------------------------------------------:|----------------------:|---------------:|--------------------------------------:|------------------------:|--------------------------:|----------------------:|
|         0 |   2026 |           4665 |                      0.975202 |               0.948827 |                                     -0.026375 |                         20.132  |                  19.3913 |                                       -0.740671 |           3.31116e+07 |    2.84859e+07 |                          -4.62572e+06 |                 2.70462 |                   3.67907 |               13.9701 |
|         1 |   2027 |           4915 |                      0.974079 |               0.947841 |                                     -0.026237 |                         20.1172 |                  19.4032 |                                       -0.714005 |           3.46715e+07 |    3.00708e+07 |                          -4.60072e+06 |                 2.69355 |                   3.54922 |               13.2695 |
|         2 |   2028 |           4921 |                      0.974072 |               0.951946 |                                     -0.022126 |                         20.1304 |                  19.5132 |                                       -0.61717  |           3.47503e+07 |    3.0203e+07  |                          -4.54727e+06 |                 2.27152 |                   3.06586 |               13.0856 |
|         3 |   2029 |           5084 |                      0.97326  |               0.94932  |                                     -0.02394  |                         20.1011 |                  19.454  |                                       -0.647088 |           3.58042e+07 |    3.11697e+07 |                          -4.63458e+06 |                 2.45974 |                   3.21916 |               12.9442 |
|         4 |   2030 |           4838 |                      0.97447  |               0.950423 |                                     -0.024047 |                         20.1316 |                  19.465  |                                       -0.666654 |           3.41946e+07 |    2.96686e+07 |                          -4.52602e+06 |                 2.4677  |                   3.31148 |               13.2361 |
|         5 |   2031 |           4753 |                      0.974994 |               0.947094 |                                     -0.027901 |                         20.1099 |                  19.3247 |                                       -0.785245 |           3.35406e+07 |    2.89733e+07 |                          -4.56727e+06 |                 2.86164 |                   3.90476 |               13.6172 |
|         6 |   2032 |           4848 |                      0.974415 |               0.945552 |                                     -0.028863 |                         20.1346 |                  19.3632 |                                       -0.771385 |           3.39029e+07 |    2.93659e+07 |                          -4.53698e+06 |                 2.96205 |                   3.83114 |               13.3823 |
|         7 |   2033 |           4928 |                      0.973966 |               0.949004 |                                     -0.024961 |                         20.1297 |                  19.4366 |                                       -0.693087 |           3.48635e+07 |    3.02473e+07 |                          -4.61617e+06 |                 2.56285 |                   3.4431  |               13.2407 |

## Aggregate deltas

- `delta_field_brier_proposed_minus_prediction`: mean=-0.025556, std=0.002079, n=8
- `delta_field_logloss_proposed_minus_prediction`: mean=-0.704413, std=0.055764, n=8
- `delta_field_rate_l1_proposed_minus_prediction`: mean=-0.000048, std=0.000004, n=8
- `delta_event_cell_probability_mean_proposed_minus_prediction`: mean=-0.022723, std=0.002297, n=8
- `delta_nll_proposed_minus_prediction`: mean=-4581843.118683, std=39967.243811, n=8
- `brier_improvement_pct`: mean=2.622958, std=0.212566, n=8
- `logloss_improvement_pct`: mean=3.500474, std=0.277059, n=8
- `nll_improvement_pct`: mean=13.343201, std=0.300532, n=8

## Critical interpretation

- Proposed is better on field-level forecast quality in this setup.
- If closed-loop performance is still weak, the next bottleneck is planner/task policy rather than the core predictive field.
- Proposed minus prediction NLL: -4581843.118683 (lower is better).
- Proposed minus prediction mean probability on occupied truth cells: -0.022723.
