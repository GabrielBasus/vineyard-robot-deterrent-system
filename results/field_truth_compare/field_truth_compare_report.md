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

|   run_idx |   seed |   truth_events |   prediction_only_field_brier |   proposed_field_brier |   delta_field_brier_proposed_minus_prediction |   prediction_only_field_logloss |   proposed_field_logloss |   delta_field_logloss_proposed_minus_prediction |   brier_improvement_pct |   logloss_improvement_pct |
|----------:|-------:|---------------:|------------------------------:|-----------------------:|----------------------------------------------:|--------------------------------:|-------------------------:|------------------------------------------------:|------------------------:|--------------------------:|
|         0 |   2026 |           4665 |                      0.975301 |               0.972865 |                                     -0.002436 |                         20.1423 |                  20.0352 |                                       -0.107114 |                0.249734 |                  0.531786 |
|         1 |   2027 |           4915 |                      0.974107 |               0.971358 |                                     -0.002749 |                         20.1266 |                  20.0066 |                                       -0.120044 |                0.282255 |                  0.596443 |
|         2 |   2028 |           4921 |                      0.974093 |               0.972023 |                                     -0.00207  |                         20.1381 |                  20.0396 |                                       -0.098525 |                0.212523 |                  0.489245 |
|         3 |   2029 |           5084 |                      0.973282 |               0.970493 |                                     -0.002789 |                         20.1103 |                  20      |                                       -0.110322 |                0.28656  |                  0.548583 |
|         4 |   2030 |           4838 |                      0.974484 |               0.971664 |                                     -0.00282  |                         20.1403 |                  20.0292 |                                       -0.111171 |                0.289339 |                  0.551983 |
|         5 |   2031 |           4753 |                      0.975032 |               0.971978 |                                     -0.003054 |                         20.1226 |                  19.9796 |                                       -0.143073 |                0.3132   |                  0.711004 |
|         6 |   2032 |           4848 |                      0.974464 |               0.970773 |                                     -0.003691 |                         20.1431 |                  19.9873 |                                       -0.155797 |                0.37879  |                  0.773453 |
|         7 |   2033 |           4928 |                      0.974022 |               0.971352 |                                     -0.002671 |                         20.1371 |                  20.0201 |                                       -0.117016 |                0.274173 |                  0.581097 |

## Aggregate deltas

- `delta_field_brier_proposed_minus_prediction`: mean=-0.002785, std=0.000439, n=8
- `delta_field_logloss_proposed_minus_prediction`: mean=-0.120383, std=0.018098, n=8
- `delta_field_rate_l1_proposed_minus_prediction`: mean=-0.000008, std=0.000001, n=8
- `delta_event_cell_probability_mean_proposed_minus_prediction`: mean=-0.002586, std=0.000861, n=8
- `brier_improvement_pct`: mean=0.285822, std=0.045040, n=8
- `logloss_improvement_pct`: mean=0.597949, std=0.089870, n=8

## Critical interpretation

- Proposed is better on field-level forecast quality in this setup.
- If closed-loop performance is still weak, the next bottleneck is planner/task policy rather than the core predictive field.
- Proposed minus prediction mean probability on occupied truth cells: -0.002586.
