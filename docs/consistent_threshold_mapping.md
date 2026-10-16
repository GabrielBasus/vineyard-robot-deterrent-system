# Consistent-estimator threshold mapping

`estimator_mode="consistent"` (SESTPP.ConsistentOnlineSESTPP) makes each robot's
`lam_hat` a true event density per m^2 per s. The candidate-generation and scoring
thresholds of the paper profile `thesis_calibrated_selective_proposed` were tuned on the
legacy estimator, whose field magnitudes are several orders of magnitude different
(legacy hotspot excess about 1e-2, consistent about 1e-7; legacy preventive
`predicted_deltaJ` about 1e4, consistent about 1e-1). In consistent mode the unmapped
profile therefore generated no model-scored deterrence at all (risk gate rejected every
candidate) and no hotspot patrol (every hotspot below `min_hotspot_score`).

Rule (fixed by the user, no tuning): for every threshold T on a model-unit quantity X,

    q        = F_legacy(T)            (share of comparisons on the rejecting side)
    T_mapped = F_consistent^{-1}(q)

measured at the point where X is compared with T, pooled over B1, B5 and B4 (variant A)
and over mu = 2e-5, 1e-4, 4e-4 (one profile serves all loads), or over the systems that
use T. Development seeds 200-209 only; evaluation seeds 300-329 were never run (the
script refuses seeds >= 300). Paper configuration
`run_plan_completion._ladder_params(system, hab_on=True, mu)` (60x48 grid, 4 robots,
1800 s, warmup 0, deterrence scales 4/4/3, kappa 0.5, rho 0.25) with
`random_stream_mode="coupled"` and `truth_deterrence_memory="complete"`.

Mapped values live in `planner_profiles.CONSISTENT_THRESHOLD_MAPPING` and make up the
profile `thesis_calibrated_selective_proposed_consistent`. Under `estimator_mode="consistent"`
the simulator swaps the paper profile for it automatically
(`planner_profiles.resolve_planner_profile_for_estimator`). To keep the legacy numbers in
consistent mode, pass `planner_profile="thesis_calibrated_selective_proposed_unmapped"`
(identical values to the paper profile, never remapped). The legacy estimator is unaffected.

Full provenance (q per system, sample sizes, quantiles of both distributions, the value
of every iteration): `docs/consistent_threshold_mapping.json`. Tool:
`experiments/consistent_threshold_mapping.py` (`collect`, `map`, `finalize`, `validate`).

## Instrumentation

Read-only, entirely in the experiment script (no logging code in the simulator):

* a line tracer active only inside `TaskGenerator.periodic_patrolling` and its
  `_collect_border_hotspots` closure reads the frame locals on each comparison line
  (lines located by source text);
* `planner_task_estimation.counterfactual_value` is wrapped to read the nominal STL
  exposure signals e_z(t) (compared with `stl_E_star`) and the ratio
  e_target(t) / (q_hat beta exp(-(t - lead)/omega_u)) (compared with `kernel_self` in
  `min(e_nom, kernel_self * supp)`); the same-state shadow valuation of A is not recorded;
* `DeterrentSystem.passes_busy_fallback_quality` is wrapped to read `p_event` and
  `deltaJ_per_cost`.

## 1. Inventory

Line numbers refer to this branch.

### Active in the paper configuration and in model units (mapped)

| threshold | legacy | where compared | quantity |
|---|---|---|---|
| `min_hotspot_score` | 1e-4 | TaskGenerator.py:1697 (patrol candidates), :1198 (border hotspot seeds); default TaskGenerator.py:530 | `lam - mu` at the hotspot |
| `model_deterring_risk_scale` (with unit-free `risk_threshold` 0.35) | 1e-4 | TaskGenerator.py:1624 via `_risk_confidence` :808-813; defaults DeterrentSystem.py:2183-2184 | effective cut on `lam - mu`: fs < -scale ln(1 - 0.35) = 4.31e-5 |
| `model_deterring_score_margin` | 0.10 | TaskGenerator.py:1731 (heuristic branch); profile planner_profiles.py:203 | best preventive score minus best patrol score (legacy utility = predicted_deltaJ - cost_eta; A: STL U minus patrol utility) |
| `model_deterring_busy_fallback_p_event_min` | 0.95 | planner_dispatch.py:72-86, called from DeterrentSystem.py busy-primary gate; profile planner_profiles.py:222 | `p_event = 1 - exp(-patch expected count)` (TaskGenerator.py:988-992) |
| `model_deterring_busy_fallback_deltaJ_per_cost_min` | 1e6 | planner_dispatch.py:72-86; profile planner_profiles.py:223 | `predicted_deltaJ / cost_eta` |
| `stl_E_star` | 5.0 | habituation_stl/mission_spec.py:75 (phi_exp predicate and its scale); DeterrentSystem.py:2331 | cell exposure e_z = sum w lam dA (planner_task_estimation.py:256) |
| `kernel_self` (Dynamics) | 1.0 | habituation_stl/task_value.py:46, :215 (`min(e_nom, supp)` in `_build_wa_signals`) | exposure rate versus suppression amplitude q_hat beta kernel_self |
| utility break-even, preventive | cost weight 1 | TaskGenerator.py:1117 (utility = predicted_deltaJ - cost_eta), compared with reactive score 0 in `_mixed_greedy_sort_key` DeterrentSystem.py:703 (dispatch "unc", B1 and B5) | `predicted_deltaJ / raw cost`; mapped value applied as a multiplier on the cue `w_eta` / `fixed_cost` |
| utility break-even, patrol | `cost_w_eta` 1 | TaskGenerator.py:966, same comparison | patrol `predicted_deltaJ / raw cost`; mapped value applied as patrol `cost_w_eta` |

The last two have no explicit threshold in the code: a reactive task scores 0, so under
"unc" a predictive task outranks it iff utility > 0, i.e. iff benefit / cost > 1. The
same exchange rate between model units and seconds sets mode choice and the
preventive-versus-patrol arbitration, so leaving it unmapped would invert B1/B5 dispatch
(legacy: 98% of generated preventive tasks have utility > 0; consistent unmapped: almost
none). Four simulator parameters were added for values that had no parameter:
`stl_kernel_self`, `min_hotspot_score`, `patrol_cost_weight`, `deterring_cost_multiplier`
(DeterrentSystem.py:2366-2369, passed through planner_task_extraction.run_task_location_estimation).
Defaults reproduce the historical behaviour bit for bit.

### Derived, not a free parameter

| item | where | note |
|---|---|---|
| `model_deterring_busy_risk_override` 0.20 | TaskGenerator.py:1601 | unit free; acts on the same `risk_conf`, so it follows the mapped `risk_scale`. Legacy q 0.296, consistent rate reported in the JSON. |

### Model units but inactive in the paper configuration (not mapped)

| threshold | where | why inactive |
|---|---|---|
| `model_deterring_chance_threshold` 0.35, `model_deterring_min_deltaJ_per_cost` 1e5, SPRT alpha/beta/margin, `model_deterring_min_selection_weight` | TaskGenerator.py:1539-1590, :1667-1673 | `gate_policy` is forced to "heuristic" (TaskGenerator.py:611) |
| `min_predicted_deltaJ_for_model_deterring` 0.0 | TaskGenerator.py:1593 | `enable_predicted_deltaJ_gate` forced False (TaskGenerator.py:612) |
| `model_deterring_field_threshold` None | TaskGenerator.py:1617 | None |
| `predictive_utility_min` 0, `predictive_cost_ratio_min` 1, `predictive_confidence_min` 0.25 | DeterrentSystem.py:1113-1160 | only `dispatch_policy="res-risk-adjusted"` |
| `model_deterring_budget_utility_per_robot_per_hr` 5 | planner_dispatch.py:196 | budget mode is `count_per_hour` |
| `stl_benefit_gate` 0 | habituation_stl/task_value.py:223, :248 | A uses `stl_robustness` valuation without strict admission |
| `E_high`, `E_low` | habituation_stl/mission_spec.py:52-53 | timed-recovery clause not active |
| `assigner_w_task_value` 0.20 | TaskGenerator.py:2062 | adds the same task utility to every robot's score for one task, so it never changes the argmax |

### Unit free (no mapping)

Sign tests (`hs <= 0` TaskGenerator.py:1244, `pred_dj <= 0` :1535), the 97th-percentile
patrol hotspot filter (:745, relative), `risk_threshold` 0.35, `busy_risk_override` 0.20,
persistence counts, `model_deterring_max_eta_s`, `busy_fallback_eta_s_max` 1.25 s,
lead-time and reservation parameters (s, fractions), `stl_T_cov_s`, `stl_W_s`,
`stl_eta_min`, `stl_theta` (temperature on normalized robustness), hab clause, budgets
(counts per hour).

## 2. Quantiles and mapped values

Final iteration (it5, computed on the consistent runs that used the it4 thresholds).

| threshold | legacy | q | mapped (consistent) | achieved consistent rate | note |
|---|---|---|---|---|---|
| `min_hotspot_score` | 1e-4 | 0.3145 | 0.0 | 0.014 | 63% of consistent hotspot scores are exactly 0 (no excitation, no suppression); attainable rates jump from 0.014 to 0.63, the nearer one is taken |
| `model_deterring_risk_scale` | 1e-4 (cut 4.31e-5) | 0.3257 | 1e-12 (cut 4.3e-13) | 0.855 | the q-quantile cut is negative (-4.9e-4); `risk_conf` clips fs at 0 and the scale must be positive, so the nearest feasible value is the limit 0+ (rejects exactly fs <= 0, as the legacy gate always did) |
| `model_deterring_score_margin` | 0.10 | 0.3562 | -0.00590 | 0.356 | pooled; per system legacy q = 0.011 (B1), 0.011 (B5), 1.0 (A), consistent 0.0, 0.0, 0.61 |
| `busy_fallback_p_event_min` | 0.95 | 0.0 | 0.95 (unchanged) | 0.0 | legacy value already at q = 0 |
| `busy_fallback_deltaJ_per_cost_min` | 1e6 | 1.0 | 4.005e6 | 1.0 | q = 1 (never passes in legacy): consistent maximum |
| `stl_E_star` | 5.0 | 0.6600 | 69.90 | 0.660 | A only |
| `stl_kernel_self` | 1.0 | 0.0144 | 2.363 | 0.0144 | A only |
| `deterring_cost_multiplier` | 1.0 | 0.0172 | 4.862e-8 | 0.0171 | B1, B5 |
| `patrol_cost_weight` | 1.0 | 0.0719 | 1e-300 | 0.271 | B1, B5; 20-27% of consistent patrol tasks have predicted_deltaJ = 0, so the q-quantile is 0 and the positive cost weight takes its limit 0+ |

Tie and boundary rules (the only places the quantile rule is not single valued):
(i) if q is 0 or 1 and the legacy value already sits at the same q in the consistent
distribution, keep it; (ii) with ties at the quantile, take the boundary whose rejection
rate is nearer q; (iii) a parameter that must be positive (risk_scale, cost weights) and
whose mapped value is <= 0 takes the limit 0+; unit-free companions (`risk_threshold`,
`busy_risk_override`) are never changed.

## 3. Convergence

| threshold | it1 | it2 | it3 | it4 | it5 (final) | last change |
|---|---|---|---|---|---|---|
| `min_hotspot_score` | 0 | 0 | 0 | 0 | 0 | 0.00% |
| `model_deterring_risk_scale` | (gate off) | 1e-12 | 1e-12 | 1e-12 | 1e-12 | 0.00% |
| `model_deterring_score_margin` | n/a | 6.898 | -0.006917 | -0.006375 | -0.005899 | 7.47% |
| `busy_fallback_p_event_min` | n/a | 0.8843 | 0.95 | 0.95 | 0.95 | 0.00% |
| `busy_fallback_deltaJ_per_cost_min` | n/a | 1e+06 | 4.005e+06 | 4.005e+06 | 4.005e+06 | 0.00% |
| `stl_E_star` | 74.96 | 69.85 | 69.47 | 69.88 | 69.90 | 0.03% |
| `stl_kernel_self` | 2.900 | 2.244 | 2.608 | 2.363 | 2.363 | 0.00% |
| `deterring_cost_multiplier` | n/a | 1e-300 | 4.758e-08 | 4.862e-08 | 4.862e-08 | 0.00% |
| `patrol_cost_weight` | n/a | 1e-300 | 1e-300 | 1e-300 | 1e-300 | 0.00% |

Iteration k maps the legacy distribution onto the consistent distribution collected with
the thresholds of iteration k-1 (it1 uses the unmapped profile). n/a: the stage was
starved in the previous round (no samples), so the legacy value was kept for that round.
it1 used an earlier, discarded representation of a negative risk cut (gate off through
`risk_threshold = 0`); it was replaced from it2 on because it changed a unit-free
parameter, and with the gate off 93% of generated preventive tasks had zero predicted
benefit. Everything is below 1%
except `model_deterring_score_margin` (7.5%), which drifts slowly (-0.0069, -0.0064,
-0.0059) because its pooled quantile is set by about 180 A comparisons whose
distribution moves with E_star and kernel_self; the 5-iteration limit was reached.

## 4. Validation (dev seeds 200-209, hab on, means over 10 seeds)

`legacy` = paper profile, legacy estimator. `consistent_unmapped` = consistent estimator
with the legacy thresholds. `consistent_mapped` = consistent estimator, profile selected
automatically (end to end through the simulator, no experiment overrides).
pred_* are the simulator's predictive-stream counters (patrol and preventive);
model_det_generated counts model-scored deterrence tasks; hotspot_patrol_generated
counts hotspot patrol tasks (fallback patrols excluded); det_vs_patrol_margin_checks
counts robot-replans where both a preventive and a patrol candidate competed.

| system | mu | run | pred_generated | pred_admitted | pred_completed | model_det_generated | hotspot_patrol_generated | det_vs_patrol_checks | reactive_completed | reactive_generated | VWE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 | 2e-05 | legacy | 825.5 | 122.0 | 27.0 | 57.0 | 31.7 | 11.0 | 24.4 | 31.3 | 42175 |
| B1 | 2e-05 | consistent_unmapped | 180.7 | 162.7 | 13.0 | 0.0 | 0.0 | 0.0 | 31.9 | 43.0 | 41589 |
| B1 | 2e-05 | consistent_mapped | 259.7 | 160.7 | 12.9 | 9.2 | 10.1 | 1.4 | 26.9 | 36.1 | 41460 |
| B1 | 1e-04 | legacy | 1982.7 | 63.8 | 12.4 | 114.8 | 30.3 | 38.7 | 77.2 | 108.0 | 199349 |
| B1 | 1e-04 | consistent_unmapped | 294.9 | 156.5 | 5.9 | 0.0 | 0.0 | 0.0 | 81.2 | 130.0 | 195995 |
| B1 | 1e-04 | consistent_mapped | 365.3 | 155.8 | 5.5 | 6.4 | 6.6 | 2.2 | 79.5 | 125.5 | 197649 |
| B1 | 4e-04 | legacy | 1954.5 | 22.3 | 2.0 | 144.6 | 16.1 | 60.2 | 109.0 | 227.7 | 805147 |
| B1 | 4e-04 | consistent_unmapped | 1057.1 | 104.1 | 1.6 | 0.0 | 0.0 | 0.0 | 109.8 | 248.5 | 793937 |
| B1 | 4e-04 | consistent_mapped | 1172.5 | 103.7 | 1.7 | 6.8 | 5.9 | 2.7 | 108.9 | 245.2 | 800619 |
| B5 | 2e-05 | legacy | 841.0 | 120.1 | 28.1 | 59.7 | 29.2 | 11.0 | 22.5 | 29.8 | 39657 |
| B5 | 2e-05 | consistent_unmapped | 180.7 | 162.7 | 13.0 | 0.0 | 0.0 | 0.0 | 31.9 | 43.0 | 41589 |
| B5 | 2e-05 | consistent_mapped | 235.0 | 163.2 | 14.1 | 5.9 | 8.8 | 1.1 | 23.5 | 32.5 | 39467 |
| B5 | 1e-04 | legacy | 2042.3 | 60.5 | 12.6 | 118.2 | 29.9 | 40.3 | 74.2 | 105.7 | 196615 |
| B5 | 1e-04 | consistent_unmapped | 294.9 | 156.5 | 5.9 | 0.0 | 0.0 | 0.0 | 81.2 | 130.0 | 195995 |
| B5 | 1e-04 | consistent_mapped | 361.5 | 156.4 | 6.1 | 6.6 | 6.3 | 2.3 | 77.9 | 121.0 | 196185 |
| B5 | 4e-04 | legacy | 1927.1 | 23.9 | 2.9 | 143.5 | 17.2 | 62.1 | 109.8 | 228.1 | 805620 |
| B5 | 4e-04 | consistent_unmapped | 1057.1 | 104.1 | 1.6 | 0.0 | 0.0 | 0.0 | 109.8 | 248.5 | 793937 |
| B5 | 4e-04 | consistent_mapped | 1177.8 | 103.4 | 1.1 | 6.1 | 5.1 | 2.8 | 113.8 | 248.2 | 790613 |
| A | 2e-05 | legacy | 771.1 | 131.7 | 30.6 | 43.9 | 43.4 | 13.3 | 17.2 | 28.8 | 38154 |
| A | 2e-05 | consistent_unmapped | 182.2 | 162.4 | 11.5 | 0.0 | 0.0 | 0.0 | 26.2 | 48.6 | 42478 |
| A | 2e-05 | consistent_mapped | 389.9 | 156.0 | 13.3 | 18.4 | 15.2 | 2.3 | 19.4 | 31.4 | 42142 |
| A | 1e-04 | legacy | 1438.8 | 95.0 | 29.8 | 76.5 | 66.5 | 39.3 | 46.8 | 99.7 | 193843 |
| A | 1e-04 | consistent_unmapped | 340.7 | 153.2 | 6.4 | 0.0 | 0.0 | 0.0 | 53.0 | 134.4 | 208646 |
| A | 1e-04 | consistent_mapped | 654.2 | 145.4 | 4.6 | 18.7 | 10.7 | 6.4 | 54.1 | 128.6 | 206378 |
| A | 4e-04 | legacy | 1452.5 | 69.1 | 14.6 | 76.6 | 84.1 | 67.2 | 68.5 | 214.4 | 841540 |
| A | 4e-04 | consistent_unmapped | 1126.2 | 104.2 | 1.1 | 0.0 | 0.0 | 0.0 | 64.7 | 220.4 | 853470 |
| A | 4e-04 | consistent_mapped | 1198.7 | 97.0 | 2.5 | 18.3 | 16.6 | 9.4 | 65.9 | 216.9 | 854087 |

Machine-readable: `results/consistent_threshold_mapping/validation.json` (not tracked).

### Reading

* The mapping restores the two pipelines the unmapped profile shut off completely
  (model-scored deterrence and hotspot patrol go from 0 to 6-19 and 5-17 per run), and
  reactive generation moves back toward legacy (A, mu 2e-5: 48.6 -> 31.4, legacy 28.8).
* Behaviour rates are **not** matched. Model-scored deterrence is 5-20x below legacy for
  B1/B5 and 2.4-4x below for A; hotspot patrol 2-5x below. Two thresholds cannot reach
  their legacy quantile, and both act early in the funnel:
  * risk gate: legacy rejects 33% of preventive candidates, but 86-91% of consistent
    candidates (B1/B5; 74% for A) have non-positive excess intensity `lam - mu`, because
    the consistent estimator's multiplicative suppression exp(-S) drives the field below
    background wherever a cue was applied, while the legacy additive field is clipped at 0.
    No positive `risk_scale` can pass a candidate with fs <= 0.
  * `min_hotspot_score`: 63% of consistent hotspot scores are exactly 0, so the attainable
    rejection rates are 1.4% or 63% against a target of 31%.
  Matching these rates would need a change to the gate itself (for example letting the risk
  confidence see negative excess), which is outside the quantile rule.
* `model_deterring_score_margin` is pooled over systems whose scores have different
  meaning (legacy utility for B1/B5, STL U for A). The pooled quantile is matched (0.356)
  but per system it is not (legacy: B1 0.011, B5 0.011, A 1.0; consistent: 0.0, 0.0, 0.61).
* pred_generated and pred_admitted are dominated by fallback patrols, which no threshold
  touches; they track the starvation of the other two sources.
