# SESTPP Isolation Sandbox

This folder is a safe place to change the SESTPP model without touching the production system.

## What To Edit

- Edit `sestpp_isolation/model.py` for structural model changes.
- Keep the main system on `SESTPP.py` unchanged until the isolated evidence is good enough.

## What The Benchmark Does

- `python -m sestpp_isolation.paired_benchmark` compares:
  - `mainline`: the current repo model from `SESTPP.py`
  - `sandbox`: the local copy from `sestpp_isolation/model.py`
- Both models see the same truth stream, detections, and intervention replay on matched seeds.
- The benchmark writes paired metrics so you can tell whether a sandbox change actually helped.

## Recommended First Run

```powershell
python -m sestpp_isolation.paired_benchmark --runs 4 --T-end 3600 --outdir results/sestpp_isolation_smoke
```

If `sestpp_isolation/model.py` is still identical to `SESTPP.py`, the paired deltas should stay near zero.

## MLE Comparison

To compare the current fixed SESTPP parameters against an offline MLE-style refit on the warmup segment:

```powershell
python -m sestpp_isolation.mle_vs_current --runs 4 --T-end 3600 --warmup-s 900 --outdir results/sestpp_mle_vs_current
```

This benchmark:

- fits the current `SESTPP.py` model parameters by approximate maximum likelihood on the warmup window,
- evaluates both `current_fixed` and `mle_fitted` on the held-out horizon after warmup,
- reports whether the MLE fit improves held-out calibration or just overfits the training likelihood.

Treat held-out `eval_nll`, `field_logloss`, and `field_brier` as the main realism metrics.
If MLE improves losses but hurts `forecast_recall_at_k` or `forecast_precision_at_k`, it may be better calibrated but less useful for hotspot ranking.

## Outputs

- `paired_per_run.csv`: one row per seed with side-by-side model metrics
- `paired_per_eval.csv`: time-slice metrics for both models
- `paired_summary.csv`: aggregate delta means, std, and CI95
- `paired_report.md`: compact written interpretation
- `paired_timeseries.png`: quick visual comparison over time

## Metrics Worth Trusting First

- `field_brier`
- `field_logloss`
- `nll`
- `forecast_recall_at_k`
- `forecast_precision_at_k`

Use the loss metrics first for calibration questions and the recall/precision metrics second for hotspot usefulness.
