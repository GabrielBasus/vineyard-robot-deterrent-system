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

This revision matches the STL package demo mechanism: the no-habituation baselines repeatedly use a fixed cue, while the full method can spend STL utility on cue variety.

## Revised-Ladder Confirmatory Run

Primary summarized run:

```text
results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed
```

Run shape:

- duration: 1800 seconds
- seeds: 125-134
- systems: `B1_greedy_fixedcue`, `B2_res_deltaJ_fixedcue`, `B3_res_stl_nohab_fixedcue`, `B4_res_stl_full_multicue`
- controls: habituation on and habituation off
- truth rate: `mu_true=2e-05`
- status: confirmatory

Primary paired exposure results:

| Comparison | Truth control | Mean delta in Jexp | 95% CI | Seeds improved |
| --- | --- | ---: | ---: | ---: |
| B4 - B1 | habituation on | -3696.74 | [-5226.86, -2166.61] | 9/10 |
| B4 - B3 | habituation on | -4277.35 | [-5791.31, -2763.40] | 10/10 |
| B3 - B2 | habituation on | -689.90 | [-1537.63, +157.84] | 7/10 |
| B4 - B3 | habituation off | 0.00 | [0.00, 0.00] | 0/10 |

Negative deltas are better because lower value-weighted exposure is the desired outcome.

Mechanism evidence for B4 - B3 under habituating truth:

| Metric | Mean delta | 95% CI |
| --- | ---: | ---: |
| Truth suppression rate | +0.0867 | [+0.0596, +0.1139] |
| Truth suppression effect sum | +1901.7389 | [+1346.1216, +2457.3562] |
| Eta at apply | +0.1559 | [+0.1012, +0.2106] |
| Variety index | +0.3634 | [+0.2498, +0.4770] |

Interpretation: the revised ladder supports the central thesis claim. B4 chooses fresher cues, applies deterrence at higher effectiveness, increases realized suppression, and reduces value-weighted exposure relative to both the greedy fixed-cue baseline and the STL-without-habituation fixed-cue baseline. The exact B4/B3 no-habituation control isolates the result to the habituation-aware cue-variety mechanism. H3 is directionally consistent with the claim that smooth STL robustness improves over hand-tuned `deltaJ`, but its 95% CI crosses zero, so it should be framed as directional rather than fully confirmed.

Note on STL robustness: B4 uses a stricter formula than B3 because it includes the additional habituation clause. Do not use global robustness alone as the primary B4/B3 comparison; use exposure and the mechanism metrics above.

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

Final thesis acceptance criteria:

- B4 beats B3 under habituating truth on paired value-weighted exposure: satisfied, 10/10 seeds.
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

These limitations should be stated in the thesis. They do not invalidate the central simulation claim tested here: holding the simulator, SESTPP model, dispatch logic, and workload setting fixed, replacing the predictive value function with habituation-aware STL robustness improves outcomes under habituating truth. Broader claims across alternative workload generators or ecological parameterizations should be treated as future validation unless additional sweeps are run.

## Current Claim

The production integration is complete, the revised ladder validates the mechanism, and the 10-seed B2-inclusive confirmatory batch supports the central simulation claim. H3 should be reported as a weaker directional result unless additional sensitivity runs make it statistically decisive.
