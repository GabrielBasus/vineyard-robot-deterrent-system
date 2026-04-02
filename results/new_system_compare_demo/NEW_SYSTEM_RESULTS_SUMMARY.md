# New System vs Control: Meeting Summary

## Main Results (mean +- CI95)
| system   | baseline        |   Exposure_mean |   Exposure_ci_lo |   Exposure_ci_hi |   Exposure_n |   ResponseTime_s_mean |   ResponseTime_s_ci_lo |   ResponseTime_s_ci_hi |   ResponseTime_s_n |   BoundaryMsgs_mean |   BoundaryMsgs_ci_lo |   BoundaryMsgs_ci_hi |   BoundaryMsgs_n |
|:---------|:----------------|----------------:|-----------------:|-----------------:|-------------:|----------------------:|-----------------------:|-----------------------:|-------------------:|--------------------:|---------------------:|---------------------:|-----------------:|
| control  | reactive        |          108936 |          69789.7 |           148081 |           30 |               353.413 |                276.335 |                430.49  |                 30 |             3065.47 |              1919.25 |              4211.68 |               30 |
| control  | prediction_only |          108550 |          69483.1 |           147617 |           30 |               205.31  |                189.956 |                220.664 |                 30 |             2826.63 |              1704.06 |              3949.21 |               30 |
| control  | proposed        |          108475 |          69537.9 |           147411 |           30 |               217.699 |                200.014 |                235.385 |                 30 |             4892.23 |              2919.02 |              6865.45 |               30 |
| new      | reactive        |          108936 |          69789.7 |           148081 |           30 |               353.413 |                276.335 |                430.49  |                 30 |             3065.47 |              1919.25 |              4211.68 |               30 |
| new      | prediction_only |          108550 |          69483.1 |           147617 |           30 |               205.31  |                189.956 |                220.664 |                 30 |             2826.63 |              1704.06 |              3949.21 |               30 |
| new      | proposed        |          108475 |          69537.9 |           147411 |           30 |               217.699 |                200.014 |                235.385 |                 30 |             4892.23 |              2919.02 |              6865.45 |               30 |

## Proposed vs Prediction-only Deltas
| system   |   ExposureDeltaPct_mean |   ExposureDeltaPct_ci_lo |   ExposureDeltaPct_ci_hi |   ResponseDeltaPct_mean |   ResponseDeltaPct_ci_lo |   ResponseDeltaPct_ci_hi |   CommDeltaPct_mean |   CommDeltaPct_ci_lo |   CommDeltaPct_ci_hi |   n_pairs |
|:---------|------------------------:|-------------------------:|-------------------------:|------------------------:|-------------------------:|-------------------------:|--------------------:|---------------------:|---------------------:|----------:|
| control  |               -0.172749 |                -0.674689 |                 0.329192 |                -5.93047 |                 -8.92356 |                 -2.93738 |             72.3621 |              66.1597 |              78.5646 |        30 |
| new      |               -0.172749 |                -0.674689 |                 0.329192 |                -5.93047 |                 -8.92356 |                 -2.93738 |             72.3621 |              66.1597 |              78.5646 |        30 |

## Plot Paths
- baseline_metrics: `results\new_system_compare_demo\baseline_metrics_compare.png`
- delta_metrics: `results\new_system_compare_demo\proposed_vs_prediction_deltas_compare.png`
- model_deterring_reasons: `results\new_system_compare_demo\model_scored_accept_reject_compare.png`
- yield_metrics: `results\new_system_compare_demo\suppression_yield_compare.png`