# Habituation-Aware STL Results

This document records the current thesis-facing status of the habituation-aware STL production ladder.

## Current Source of Truth

The current ladder definition is the revised fixed-cue versus multi-cue design in `experiments/run_habituation_stl_production_ladder.py`.

| System | Meaning |
| --- | --- |
| `B0_reactive` | Reactive-only reference. |
| `B1_greedy_fixedcue` | Legacy predictive value with unconstrained/greedy dispatch and one fixed cue mode. |
| `B2_res_deltaJ_fixedcue` | Reserved-capacity dispatch with prior `deltaJ` value and one fixed cue mode. |
| `B3_res_stl_nohab_fixedcue` | Reserved-capacity STL value with exposure and coverage clauses only, one fixed cue mode. |
| `B4_res_stl_full_multicue` | Full proposal: reserved-capacity STL value with exposure, coverage, and habituation clauses plus multi-cue action variants. |
| `B5_greedy_habcue` | B1-style unconstrained exposure-greedy dispatch, but with non-STL habituation-aware cue selection. |

This revision matches the STL package demo mechanism: the no-habituation baselines repeatedly use a fixed cue, while the full method can spend STL utility on cue variety.
B5 is the added reader-check baseline: it tests whether simple cue rotation gets most of the benefit without STL.

## Baseline Provenance and Tuning Fairness

B2 is the real prior production predictive-value path from the immediate pre-STL code, not a new STL-shaped reimplementation. In the ladder, `B2_res_deltaJ_fixedcue` sets `predictive_utility_mode="deltaJ"`. That mode calls `TaskGenerator._deterrence_candidate_metrics(...)`, which in turn calls `planner_task_estimation.estimate_counterfactual_reduction(...)` and writes the result into the existing `predicted_deltaJ`, `utility`, and `score` fields. The same `estimate_counterfactual_reduction(...)` function existed before the STL integration in commit `635bab7` (`Update snapshot workspace`).

Important provenance caveat: this means B2 represents the immediate pre-STL production counterfactual-value method. It is not the earliest `main`-branch task generator, because `main` predates the later predictive counterfactual module entirely.

The dispatcher settings are controlled as follows:

| System | Dispatcher | Reservation fraction rho | Predictive value |
| --- | --- | ---: | --- |
| B1 | `unc` | none | legacy greedy fixed cue |
| B2 | `res` | 0.25 in the reported runs | prior `estimate_counterfactual_reduction` deltaJ, fixed cue |
| B3 | `res` | 0.25 in the reported runs | STL exposure+coverage, fixed cue |
| B4 | `res` | 0.25 in the reported runs | STL exposure+coverage+habituation, multi-cue |
| B5 | `unc` | none | legacy greedy with non-STL habituation-aware cue choice |

B2, B3, and B4 therefore share the same reserved-capacity dispatcher class and the same `rho` in the reported B1-B5 ladders. B1 and B5 intentionally use the unconstrained greedy dispatcher, so there is no reservation fraction to tune for those baselines.

The current experiments should be described as fixed-settings ablations, not as a fully tuned best-response comparison across every policy. The STL/habituation settings and stress scenario were iterated during this revision, while B2 did not receive an independent sweep over `rho`, horizon, budget, and admission thresholds. This does not invalidate B4-vs-B1, B4-vs-B3, B4-vs-B5, or the mismatch robustness checks, but it does limit H3. The correct H3 wording is: under the shared reserved-capacity settings used here, STL exposure+coverage without the habituation clause is approximately neutral relative to the prior deltaJ method. Do not claim that a globally optimized STL-nohab policy beats a globally optimized legacy deltaJ policy.

The fair-comparison protocol is now implemented in `experiments/run_habituation_stl_fair_tuning.py`. Once that runner has completed, prefer its held-out confirmation tables for any thesis claim about tuned B4 versus tuned baselines.

## Revised-Ladder Confirmatory Run

Primary summarized run:

```text
results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed
```

Run shape:

- duration: 1800 seconds
- seeds: 125-134
- systems: `B1_greedy_fixedcue`, `B2_res_deltaJ_fixedcue`, `B3_res_stl_nohab_fixedcue`, `B4_res_stl_full_multicue`, `B5_greedy_habcue`
- controls: habituation on and habituation off
- truth rate: `mu_true=2e-05`
- status: confirmatory

Primary paired exposure results:

| Comparison | Truth control | Mean delta in Jexp | 95% CI | Seeds improved |
| --- | --- | ---: | ---: | ---: |
| B4 - B1 | habituation on | -3696.74 | [-5462.62, -1930.85] | 9/10 |
| B4 - B3 | habituation on | -4277.35 | [-6024.58, -2530.12] | 10/10 |
| B3 - B2 | habituation on | -689.90 | [-1668.25, +288.46] | 7/10 |
| B5 - B1 | habituation on | -2220.87 | [-3093.89, -1347.84] | 10/10 |
| B4 - B5 | habituation on | -1475.87 | [-3639.64, +687.90] | 7/10 |
| B4 - B3 | habituation off | 0.00 | [0.00, 0.00] | 0/10 |

Negative deltas are better because lower value-weighted exposure is the desired outcome. Confidence intervals are paired two-sided 95% Student-t intervals over matched seeds.

Mechanism evidence for B4 - B3 under habituating truth:

| Metric | Mean delta | 95% CI |
| --- | ---: | ---: |
| Truth suppression rate | +0.0867 | [+0.0554, +0.1181] |
| Truth suppression effect sum | +1901.7389 | [+1260.5112, +2542.9666] |
| Eta at apply | +0.1559 | [+0.0927, +0.2190] |
| Variety index | +0.3634 | [+0.2323, +0.4946] |

Interpretation: the revised ladder supports the central habituation mechanism, but the B5 ablation narrows the STL claim. A simple non-STL cue-rotation heuristic already recovers a substantial share of the gain over B1. B4 still has lower mean exposure than B5, but the B4-B5 confidence interval crosses zero in this 10-seed run, so the extra STL layer should be framed as directionally beneficial rather than conclusively better than cue rotation alone. The strongest confirmed result is that habituation-aware cue variety matters; the incremental value of STL beyond cue rotation needs either a larger run or a more targeted condition.

Note on STL robustness: B4 uses a stricter formula than B3 because it includes the additional habituation clause. Do not use global robustness alone as the primary B4/B3 comparison; use exposure and the mechanism metrics above.

Guardrail and mechanism metrics under matched-model habituating truth:

| System | Response s | Predictive completion ratio | Coverage robustness | Eta-bar at apply | Variety index | Suppression effect sum | Habituation-attributable exposure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 95.41 | 0.256 | 0.1555 | 0.3615 | 0.0000 | 3281.97 | +4723.11 |
| B3 | 149.26 | 0.265 | -0.0266 | 0.3548 | 0.0000 | 3006.04 | +3881.80 |
| B4 | 176.43 | 0.273 | 0.0838 | 0.5107 | 0.3634 | 4907.78 | -395.56 |
| B5 | 102.62 | 0.245 | 0.0727 | 0.4485 | 0.1403 | 4294.19 | +2554.33 |

Matched-model guardrail interpretation: B4 does not buy exposure improvement by degrading the available completion or coverage guardrails. It has the highest predictive completion ratio in this table and coverage robustness is positive. However, B4 does increase mean response time relative to B1 and B5, so response latency must be reported as a tradeoff. The strongest mechanism evidence is that B4 raises eta-bar at apply, increases variety, raises realized suppression effect, and nearly eliminates the habituation-attributable exposure penalty observed in B1, B3, and B5.

## Model-Mismatch Robustness Run

Robustness summarized run:

```text
results/testbench/habituation_stl_model_mismatch_b1_b5_1800s_10seed
```

This run deliberately breaks the self-fulfilling matched-model assumption. The realized truth process uses faster habituation recovery, cross-mode generalization, and an additive post-cue drop, while the planner still assumes the proposal multiplicative update with no cross-mode generalization.

Run shape:

- duration: 1800 seconds
- seeds: 125-134
- systems: `B1_greedy_fixedcue`, `B2_res_deltaJ_fixedcue`, `B3_res_stl_nohab_fixedcue`, `B4_res_stl_full_multicue`, `B5_greedy_habcue`
- controls: habituation on and habituation off
- truth mismatch: `truth_habituation_T_rec_s=900`, `truth_habituation_gamma=0.35`, `truth_habituation_update_model=additive_drop`
- planner assumption: `planner_habituation_T_rec_s=1800`, `planner_habituation_gamma=0.0`, `planner_habituation_update_model=multiplicative`
- status: robustness check

Primary paired exposure results under habituating truth:

| Comparison | Mean delta in Jexp | 95% CI | Seeds improved |
| --- | ---: | ---: | ---: |
| B4 - B1 | -2461.34 | [-3467.22, -1455.46] | 10/10 |
| B4 - B3 | -2846.91 | [-3920.37, -1773.45] | 10/10 |
| B3 - B2 | -111.31 | [-1090.87, +868.26] | 6/10 |
| B5 - B1 | -1024.21 | [-1824.23, -224.20] | 8/10 |
| B4 - B5 | -1437.13 | [-2669.03, -205.23] | 8/10 |

Confidence intervals are paired two-sided 95% Student-t intervals over matched seeds.

Mismatch diagnostics under habituating truth:

| System | Truth eta mean | Planner eta mean | Eta at apply | Variety index |
| --- | ---: | ---: | ---: | ---: |
| B1 | 0.4748 | 0.8368 | 0.3163 | 0.0000 |
| B3 | 0.5042 | 0.8383 | 0.3159 | 0.0000 |
| B4 | 0.5085 | 0.7671 | 0.4035 | 0.3295 |
| B5 | 0.4900 | 0.8092 | 0.3568 | 0.1145 |

Interpretation: the mismatch result is stronger than the matched-model B5 ablation. B4 still beats B1 and B3 in every seed, and now also beats the non-STL B5 cue-rotation baseline with a negative 95% confidence interval. This supports the claim that the STL layer is not merely exploiting perfect knowledge of the ground-truth habituation model. The weaker result remains B3 versus B2, where STL without the habituation clause is approximately neutral.

Guardrail and mechanism metrics under mismatched habituating truth:

| System | Response s | Predictive completion ratio | Coverage robustness | Eta-bar at apply | Variety index | Suppression effect sum | Habituation-attributable exposure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 | 82.55 | 0.228 | -0.0269 | 0.3163 | 0.0000 | 3040.12 | +5317.43 |
| B3 | 160.27 | 0.301 | 0.0651 | 0.3159 | 0.0000 | 2902.66 | +4281.07 |
| B4 | 142.05 | 0.276 | 0.1766 | 0.4035 | 0.3295 | 4051.32 | +1434.16 |
| B5 | 91.62 | 0.226 | 0.0834 | 0.3568 | 0.1145 | 3469.10 | +4345.31 |

Mismatch guardrail interpretation: B4's exposure gain is not accompanied by a coverage robustness collapse; it has the best mean coverage robustness in the table. It also improves predictive completion ratio over B1 and B5, though B3 has the highest completion ratio. Response time is again slower than the unconstrained greedy systems, but faster than B3. Mechanistically, B4 has higher eta-bar at apply, much higher cue variety, higher suppression effect, and a much smaller habituation-attributable exposure penalty than B1, B3, or B5.

Travel and explicit deadline-miss caveat: the completed B1-B5 ladder rows did not export `travel_distance_total`, `predictive_expired_fraction`, or `predictive_deadline_feasible_fraction`, so those guardrails cannot be reconstructed from the existing raw JSON. The ladder exporter now includes those fields for future reruns. Until that rerun is available, do not claim that B4 has no travel or deadline-miss cost; claim only what the current rows directly support.

## Fair Equal-Budget Tuning Status

The fair tuning run in:

```text
results/testbench/habituation_stl_fair_tuning
```

completed the tuning phase only. It produced 648 per-run rows, matching six systems, 36 trials per system, three tuning seeds, and habituation-on selection. The audit found:

- every system received 36 trials;
- every trial has exactly three tuning seeds;
- the shared tuning grid is identical across systems;
- `rho` is tuned only for reserved-dispatch systems and is balanced at 12 trials each for `0.10`, `0.25`, and `0.40`;
- fixed cue is tuned only for B1/B2/B3 and is balanced at 12 trials each for `formation`, `laser`, and `biosonic`;
- the selected configs are the actual best rows under tuning-set `value_weighted_exposure`;
- primary exposure and guardrail/mechanism metrics are finite in all 648 tuning rows.

Selected tuning scores under habituating truth:

| Rank | Baseline | Selected trial | Tuning exposure |
| ---: | --- | --- | ---: |
| 1 | B1_greedy_fixedcue | B1_greedy_fixedcue_trial_027 | 19625.047 |
| 2 | B5_greedy_habcue | B5_greedy_habcue_trial_025 | 19776.460 |
| 3 | B4_res_stl_full_multicue | B4_res_stl_full_multicue_trial_003 | 19965.626 |
| 4 | B3_res_stl_nohab_fixedcue | B3_res_stl_nohab_fixedcue_trial_013 | 20028.964 |
| 5 | B2_res_deltaJ_fixedcue | B2_res_deltaJ_fixedcue_trial_010 | 20643.600 |
| 6 | B5_res_habcue_multicue | B5_res_habcue_multicue_trial_014 | 20749.965 |

Interpretation: the fair tuning protocol appears structurally unbiased, but the tuning-set result does not show B4 dominating all baselines. B1 and B5-greedy tune to lower exposure on the three tuning seeds. The held-out confirmation phase is therefore required before any final thesis claim about fair best-response performance. Because this tuning run used no explicit guardrail constraints during selection, the thesis can call it an exposure-primary fair tuning protocol; claims about deadline, coverage, or travel tradeoffs must come from the held-out confirmation metrics.

## Calibration Pilot

The preceding revised-ladder calibration run remains useful for debugging:

```text
results/testbench/habituation_stl_revised_calibration_1800s_3seed
```

That pilot was mechanism-positive but underpowered. It should not be cited as the final result now that the 10-seed revised confirmatory batch is available.

## Historical Calibration Result

The earlier 10-seed run remains useful as a historical stress-case calibration:

```text
results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5
```

That run showed a strong B4 exposure win, but it used the earlier baseline labels and pre-revision ladder framing. Do not cite it as the final revised-ladder result without explaining that it predates the fixed-cue versus multi-cue cleanup.

## Reproduction Command

Run the revised confirmatory batch:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --reservation-fraction 0.25 --mu-true 2e-05 --deterrence-beta-scale 4.0 --deterrence-sigma-scale 4.0 --deterrence-omega-scale 3.0 --habituation-kappa 0.5 --systems B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue --max-workers 4
```

Then summarize:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\summarize_habituation_stl_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed
```

Run the B5 supplemental 10-seed batch without rerunning B1-B4:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --reservation-fraction 0.25 --mu-true 2e-05 --deterrence-beta-scale 4.0 --deterrence-sigma-scale 4.0 --deterrence-omega-scale 3.0 --habituation-kappa 0.5 --systems B5_greedy_habcue --merge-existing-raw --max-workers 4
```

After B5 completes, the same output directory will contain raw rows for B1-B5 and regenerated combined CSV/Markdown summaries.

Run the model-mismatch robustness check:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_model_mismatch_b1_b5_1800s_10seed --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --reservation-fraction 0.25 --mu-true 2e-05 --deterrence-beta-scale 4.0 --deterrence-sigma-scale 4.0 --deterrence-omega-scale 3.0 --habituation-kappa 0.5 --truth-habituation-t-rec-s 900 --truth-habituation-gamma 0.35 --truth-habituation-update-model additive_drop --planner-habituation-t-rec-s 1800 --planner-habituation-gamma 0.0 --planner-habituation-update-model multiplicative --systems B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue B5_greedy_habcue --max-workers 4
```

This isolates model misspecification: the realized truth field recovers with `T_rec=900`, applies cross-mode generalization with `gamma=0.35`, and uses an additive post-cue drop. The planner still assumes `T_rec=1800`, no cross-mode generalization, and the proposal multiplicative update.

Final thesis acceptance criteria:

- B4 beats B3 under habituating truth on paired value-weighted exposure: satisfied, 10/10 seeds.
- B4 beats B5 under matched-model habituating truth: directionally satisfied, 7/10 seeds, but not significant at 95% confidence.
- B4 beats B5 under mismatched habituating truth: satisfied, 8/10 seeds, 95% confidence interval below zero.
- B5 beats B1 under habituating truth on paired value-weighted exposure: satisfied, 10/10 seeds.
- B3 beats B2 under habituating truth on paired value-weighted exposure: directionally satisfied, 7/10 seeds, but not significant at 95% confidence.
- B4/B3 is near-zero under non-habituating truth: satisfied, exactly zero.
- B4 increases `habituation_variety_index` and `habituation_eta_at_apply_mean`: satisfied.
- B4 increases realized truth suppression or suppression-effect sum: satisfied.

## Risks, Mitigations, and Threats to Validity

Risk mitigations accounted for in the integration and experiment design:

- Flat task values, the failure mode that motivated the STL revision, are mitigated by smooth STL robustness, AGM-style smooth aggregation, and per-clause normalization in the STL value path.
- Habituation being too weak to affect the primary metric is mitigated by the concentrated high-value stress scenario, the `habituation_kappa` control, and the habituation-off paired control that bounds the effect size.
- Decentralized monitoring gaps at zone boundaries are mitigated by the existing `EventBus` boundary-event sharing path and by evaluating each robot's STL monitor over its local cells and boundary-adjacent cells.
- Horizon and monitor-period sensitivity are treated as secondary parameters. The headline experiments fix them at principled defaults rather than sweeping them.

Threats to validity:

- The study is simulation-only and has no physical-robot validation.
- The simulator has access to the ground-truth process used to generate events.
- Detection noise is not the primary modeled uncertainty in the headline STL ladder.
- The predictive workload generator is in-house.
- The habituation model is a stylized abstraction and is not fitted to ecological field data.

These limitations should be stated in the thesis. They do not invalidate the central simulation claim tested here: holding the simulator, SESTPP model, dispatch logic, and workload setting fixed, adding habituation-aware cue selection improves outcomes under habituating truth. The stronger claim that STL robustness adds benefit beyond a non-STL cue-rotation heuristic is directional in the matched-model batch and statistically supported in the model-mismatch robustness batch.

## Current Claim

The production integration is complete, and the fixed-setting revised ladder validates the habituation-aware cue-variety mechanism. The newer fair equal-budget tuning run is the stricter thesis protocol, but only its tuning phase has completed. Under fair tuning seeds, B4 is competitive but not the best exposure policy; B1 and B5-greedy are lower on the tuning set. Do not present the fair-tuned thesis result as complete until the held-out confirmation phase is run and the guardrail/mechanism metrics are summarized.
