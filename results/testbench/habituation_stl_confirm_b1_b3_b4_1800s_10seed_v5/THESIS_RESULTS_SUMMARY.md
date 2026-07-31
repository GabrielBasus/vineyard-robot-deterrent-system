# Habituation STL Confirmatory Results

Source run: `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5`.

## Run Configuration

- Duration: `1800.0` seconds
- Seeds: `125` through `134`
- Systems: `B1_unc_legacy, B3_res_stl_nohab, B4_res_stl_full`
- Jobs completed: `60`
- Grid/fleet: `nx=60`, `ny=48`, `nrobots=4`
- Truth rate: `mu_true=2e-05`

## Primary Paired Results

| Comparison | Mean delta Jexp | 95% CI | Seeds improved | Interpretation |
|---|---:|---:|---:|---|
| B4 - B1, hab_on | -2298.517 | [-4184.215, -412.820] | 8/10 | B4 beats legacy unconstrained in this confirmatory batch. |
| B4 - B3, hab_on | -3288.099 | [-4112.467, -2463.732] | 10/10 | Full habituation-aware STL beats STL without habituation. |
| B4 - B3, hab_off | 0.000 | [0.000, 0.000] | 0/10 | No-habituation control collapses as expected. |

Negative exposure deltas are better because they mean the system reduced value-weighted exposure relative to the reference.

## Mechanism Evidence: B4 - B3 Under Habituation On

| Metric | Mean delta | 95% CI | Direction |
|---|---:|---:|---|
| Suppression rate | 0.0630 | [0.0467, 0.0793] | Higher is better |
| Eta at apply | 0.1454 | [0.0843, 0.2064] | Higher is better |
| Variety index | 0.3072 | [0.2390, 0.3755] | Higher is better |

B4 increases cue variety and application-time effectiveness, which increases realized truth suppression and reduces exposure.

## Figure Files

- `advisor_figures/exposure_mean_ci_by_system.png`
- `advisor_figures/hab_on_exposure_per_seed.png`
- `advisor_figures/hab_on_b4_paired_exposure_deltas.png`
- `advisor_figures/hab_on_b4_b3_mechanism_deltas.png`

## Thesis-Ready Claim

In a 10-seed, 1800-second confirmatory batch with habituating ground truth, the full habituation-aware STL predictive value function reduces value-weighted exposure relative to both legacy unconstrained dispatch and STL robustness without habituation. The B4/B3 no-habituation control is exactly matched on exposure and task metrics, supporting the claim that the observed advantage is caused by the habituation-aware clause rather than unrelated dispatcher changes.
