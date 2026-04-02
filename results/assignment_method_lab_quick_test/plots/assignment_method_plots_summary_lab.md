# Assignment Method Comparison Lab - Plot Summary

- Selected winner (from manifest rule): `frozen_greedy`
- Baselines: reactive, prediction_only, proposed
- Methods: frozen_greedy, hungarian, auction, cbba

## Proposed minus Prediction-only (mean %) by method

| method | exposure improve % | response improve % | comm increase % |
|---|---:|---:|---:|
| frozen_greedy | 4.689 | 0.880 | 54.545 |
| hungarian | 0.000 | 5.524 | 62.500 |
| auction | 0.000 | 6.625 | 57.143 |
| cbba | 0.000 | -0.610 | 36.364 |

## Generated Plots

- `exposure_by_method.png`
- `response_by_method.png`
- `comm_by_method.png`
- `proposed_minus_prediction_by_method.png`
- `tradeoff_scatter_exposure_comm.png`
- `rank_heatmap_reactive.png`
- `rank_heatmap_prediction_only.png`
- `rank_heatmap_proposed.png`
