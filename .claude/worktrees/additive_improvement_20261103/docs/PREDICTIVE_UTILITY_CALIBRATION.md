# Predictive Utility Calibration

## Purpose

This comparison evaluates whether legacy deltaJ-style predictive tasks should be ranked by raw predicted exposure reduction or by a confidence-weighted expected value inside the existing modular task extraction, task selection, dispatch, and assignment pipeline. It predates the habituation-aware STL value mode.

The experiment compares:

- `deltaJ`: deterministic predictive utility, `utility = predicted_deltaJ`
- `bernoulli_expected_deltaJ`: Bernoulli expected-value utility, `utility = confidence * predicted_deltaJ`
- `legacy`: the existing TaskGenerator utility, retained as the unconstrained baseline

The newer STL mode is separate: `predictive_utility_mode="stl_robustness"` replaces deltaJ-style value with counterfactual STL robustness improvement. Use `docs/STL_THEORY_AND_INTEGRATION_AUDIT.md` and `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md` for that path.

## Raw DeltaJ vs Bernoulli Expected DeltaJ

Raw `predicted_deltaJ` treats the forecasted benefit as deterministic. A task with a large predicted reduction ranks highly even when the evidence supporting that prediction is weak.

Bernoulli expected deltaJ treats the prediction as an uncertain optional investment:

```text
utility = C_calibrated * predicted_deltaJ
```

where `C_calibrated` is derived from one of the available confidence sources.

## Expected-Value Interpretation

The expected-value interpretation is heuristic. The implementation computes:

```text
C_raw =
  p_event * selection_weight
  or p_event
  or risk_conf
  or selection_weight

C_calibrated = clip(C_raw, 0, 1) ^ confidence_power
bernoulli_expected_deltaJ = C_calibrated * predicted_deltaJ
```

`confidence_power < 1` makes confidence less punitive, while `confidence_power > 1` makes low confidence more punitive.

## Calibration Methodology

The 24 hour comparison config expands the confidence sweep into explicit testbench systems because the current testbench runner accepts concrete systems rather than a sweep DSL.

The sweep covers:

- `predictive_utility_mode`: `deltaJ`, `bernoulli_expected_deltaJ`

This calibration sweep does not include `stl_robustness`; the STL ladder uses dedicated B0-B4 runners because it needs baseline-specific clause sets and paired habituation-on/off truth controls.
- `confidence_source`: `p_event_times_selection_weight`, `p_event`, `risk_conf`, `selection_weight`
- `confidence_power`: `0.5`, `1.0`, `2.0`

The comparison uses the same proposed thesis workload and frozen SESTPP calibration profile as the current nominal 24 hour thesis comparisons.

## Metrics

The added native metrics include:

- `native_predictive_confidence_mean`
- `native_predictive_confidence_completed_mean`
- `native_predictive_expected_deltaJ_total`
- `native_predictive_raw_deltaJ_total`
- `native_predictive_completion_ratio`
- `native_predictive_success_ratio`
- `native_predictive_false_positive_ratio`
- `native_predictive_success_proxy_evaluated_total`
- `native_predictive_success_proxy_total`
- `native_predictive_false_positive_proxy_total`

The success proxy labels a completed or expired predictive task as successful if a truth event later appears near the predictive task location before the task's predictive deadline. If no explicit deadline is available, the forecast horizon is used.

## Limitations

The confidence value is heuristic. It is not yet a statistically calibrated probability.

The realized success label is approximate. A missing truth event can mean the forecast was a false positive, but it can also mean the preventive action suppressed the event. A truth event near the task indicates the prediction corresponded to later activity, not necessarily that the action improved outcome.

The comparison should not be used to claim proven superiority, theoretical guarantees, or calibrated probabilities unless those claims are demonstrated by the experiment outputs.

## Running

Run the full calibration comparison:

```bash
python run_predictive_utility_calibration_compare.py --config testbench/thesis_compare_predictive_utility_calibration_24h.json --max-workers 1
```

Generate reports from existing testbench outputs without rerunning simulations:

```bash
python run_predictive_utility_calibration_compare.py --config testbench/thesis_compare_predictive_utility_calibration_24h.json --skip-run
```

Run only the testbench:

```bash
python -m testbench.run_testbench --config testbench/thesis_compare_predictive_utility_calibration_24h.json --max-workers 1
```

## Interpreting Results

Prefer conclusions that compare paired seeds and multiple metrics together. A useful Bernoulli configuration should reduce value-weighted exposure or response-time harm without simply starving reactive service or inflating false-positive predictive work.

Treat `native_predictive_success_ratio` and `native_predictive_false_positive_ratio` as proxy diagnostics, not calibrated probability measures.
