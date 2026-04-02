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
- `T_end`: `600.0`
- `warmup_s`: `300.0`
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
- `runs`: `1`
- `seed_start`: `2026`
- `final_map_recent_truth`: `400`
- `final_map_recent_interventions`: `120`

## Per-run results

|   run_idx |   seed |   truth_events |   prediction_only_field_brier |   proposed_field_brier |   delta_field_brier_proposed_minus_prediction |   prediction_only_field_logloss |   proposed_field_logloss |   delta_field_logloss_proposed_minus_prediction |   prediction_only_nll |   proposed_nll |   delta_nll_proposed_minus_prediction |   brier_improvement_pct |   logloss_improvement_pct |   nll_improvement_pct |
|----------:|-------:|---------------:|------------------------------:|-----------------------:|----------------------------------------------:|--------------------------------:|-------------------------:|------------------------------------------------:|----------------------:|---------------:|--------------------------------------:|------------------------:|--------------------------:|----------------------:|
|         0 |   2026 |            192 |                      0.897988 |               0.834985 |                                     -0.063003 |                         15.5981 |                  14.3125 |                                        -1.28556 |                794994 |         683406 |                               -111588 |                 7.01607 |                   8.24182 |               14.0363 |

## Aggregate deltas

- `delta_field_brier_proposed_minus_prediction`: mean=-0.063003, std=0.000000, n=1
- `delta_field_logloss_proposed_minus_prediction`: mean=-1.285563, std=0.000000, n=1
- `delta_field_rate_l1_proposed_minus_prediction`: mean=-0.000087, std=0.000000, n=1
- `delta_event_cell_probability_mean_proposed_minus_prediction`: mean=-0.040476, std=0.000000, n=1
- `delta_nll_proposed_minus_prediction`: mean=-111588.015735, std=0.000000, n=1
- `brier_improvement_pct`: mean=7.016066, std=0.000000, n=1
- `logloss_improvement_pct`: mean=8.241816, std=0.000000, n=1
- `nll_improvement_pct`: mean=14.036339, std=0.000000, n=1

## Critical interpretation

- Proposed is better on field-level forecast quality in this setup.
- If closed-loop performance is still weak, the next bottleneck is planner/task policy rather than the core predictive field.
- Proposed minus prediction NLL: -111588.015735 (lower is better).
- Proposed minus prediction mean probability on occupied truth cells: -0.040476.
