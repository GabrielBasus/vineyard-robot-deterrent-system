# Assignment Method Comparison Lab - Plot Summary

- Selected winner (from manifest rule): `frozen_greedy`
- Baselines: reactive, prediction_only, proposed
- Methods: frozen_greedy, hungarian, auction, cbba

## Proposed minus Prediction-only (mean %) by method

| method | exposure improve % | response improve % | comm increase % |
|---|---:|---:|---:|
| frozen_greedy | 0.559 | 5.141 | 86.213 |
| hungarian | -1.321 | 0.141 | 94.667 |
| auction | -1.144 | -0.864 | 91.176 |
| cbba | 0.028 | -5.222 | 86.311 |

## Generated Plots

- `exposure_by_method.png`
- `response_by_method.png`
- `comm_by_method.png`
- `proposed_minus_prediction_by_method.png`
- `tradeoff_scatter_exposure_comm.png`
- `rank_heatmap_reactive.png`
- `rank_heatmap_prediction_only.png`
- `rank_heatmap_proposed.png`
