# Fixed-unit implementation audit and proposed calibration procedure

**Superseded calibration protocol:** the initial B5-only bounded search finished;
neither finalist passed every guardrail. It is diagnostic, not the shared B1--B5
calibration. The user approved staged upstream tuning with frozen inheritance:
see [HIERARCHICAL_ACC_CALIBRATION.md](HIERARCHICAL_ACC_CALIBRATION.md).
The audit findings below remain applicable; historical execution/status text is retained.

Date: 2026-10-30. Status: **initial bounded calibration approved by the user and started on 2026-10-30**.

Execution: `python -m experiments.run_bounded_calibration --wait-for-recordings --workers 0 --hours 4`.
Live state is `results/bounded_acc_calibration/status.json`. The user additionally authorized
more workers as needed: benchmark memory-capped worker counts up to physical CPU cores,
retaining the 4 GB reserve. No settings are automatically deployed.

Working checkout: `.claude/worktrees/agent-a10afe5b1ab1c62a9`, based on `d7beffe` plus the audit changes.
The workspace-root checkout remains at `6595abd`; it does not contain all of these changes.

## 1. Objective and fixed experiment

Determine which ACC conclusions survive a corrected implementation, and whether a separately
calibrated estimator improves the corrected system. Recovering a favorable B4 result is not
a calibration objective. Keep the following arms distinct:

1. Archived ACC reproduction, with its original random streams and 200-entry truth memory.
2. Old-unit reference in the improvement-plan environment.
3. Corrected units with unchanged ACC numerical constants and decision settings.
4. Corrected units with a shared, independently validated estimator calibration.
5. Optional decision-policy tuning, separately labeled and budgeted for every comparator.

Arms 2-5 use coupled exogenous streams and complete truth intervention memory with the
existing negligible-contribution pruning rule. Unit mode is `mass_per_cell` in arms 3-5.
Retain four UGVs, a 500 x 500 m field, a 60 x 48 grid, 1800 s duration, no warm-up, 1 s
steps, 45 s replanning, the paper cue parameters and depletion/recovery parameters.
Loads remain 2e-5, 1e-4 and 4e-4. Do not reinterpret truth parameters or change the truth
process while calibrating the estimator. Preserve the plan's A-specific forecast-correction
exception; changes B-E remain separate controlled factors.

## 2. Audit findings and corrections

### Verified runtime behavior

- Amount-per-cell trigger and inhibition stamps are divided by node area exactly once.
- Exposure integrals and scalar/vectorized counterfactual consumers use compatible units.
- Excess fields use the time-adjusted background under corrected units.
- Original density mode remains available for reproduction.
- Complete truth memory is independent of the planner's bounded history. A targeted test
  retains 251 relevant applications and removes them only after negligible decay.
- Coupled streams share exogenous draws across policies while allowing detections, accepted
  events and future descendants to differ with interventions.
- Shared forecast propagation, copied-state isolation, chronology, and planner-profile
  overrides are covered by focused tests.
- A is B4. B5 is a separate greedy freshest-cue baseline; D/E use B5 continuations.

### Corrections made during this audit

1. **Replay likelihood timing.** The truth-event log term used the field before a step's
   observations, while its integral used the field after those observations. The integral
   now uses the same left-step field. A deterministic analytic example exposed the error.
   Detected-only diagnostic event scores retain the pre-detection convention.
2. **Replay cache identity.** Reuse now requires the scorer version, observation target,
   recording contents, scoring constants, and relevant replay/model source files to agree.
   Historical caches without this identity are rejected. Corrected scores use separate
   `refit_truth_v2` / `refit_detected_diagnostic_v2` output folders.
3. **Unidentified assignment weight.** A zero assignment-change target no longer selects
   the largest numerically harmless weight. It keeps paper weight 0.2 whenever compatible,
   otherwise chooses the closest zero-change grid value and marks the weight unidentified.
   In the new procedure simply hold it at 0.2; do not fit it.
4. **Recording start.** `record --recording-start paper` now records unchanged ACC numerical
   constants in `recordings_paper/`; the historical equivalent start, whose stamp amplitudes
   are multiplied by node area, stays separate. Replay reconstructs both live fields exactly.
5. **Comparator reproducibility.** `B2_c`, fixed-cue `B3_c`, and auxiliary multi-cue
   `B3_multicue_c` are now supported by the repository parameter builder, rather than existing
   only as temporary registrations inside a local launcher.

These fixes do not change the simulator's physical dynamics. Historical matching run metrics
remain diagnostic data. Historical refit NLL values are superseded; do not combine them with
v2 scores or restart the historical search using its old cache.
The NLL timing correction does not change existing replay intensity fields, occupancy
log-loss/Brier scores, or recorded mission exposure. It does not explain away the earlier
extreme fitted parameters or establish that B4's original advantage will return.

### Limits that remain explicit

- Additive estimator inhibition differs from multiplicative truth suppression. Correct
  implementation does not establish model adequacy.
- Existing occupancy log-loss/Brier use `1-exp(-lambda(t)*area*H)`: a frozen-rate diagnostic,
  not an exact continuation forecast over H. Overlapping windows are not independent samples.
- Historical node-area quadrature is preserved across scoring and planner consumers; it
  is a spatial discretization convention rather than an exact continuous-field integral.
- Replay freezes the collecting policy and relay membership. Closed-loop validation is required.
- One global threshold cannot generally reproduce every old gate rate in every policy/load.
- Separate-margin code exists on branch `phase2-margin-split` but is not integrated here.
  Keep the old pooled matcher for historical interpretation; it is not the new calibration.
- The current historical `refit` command still performs its old expanding search. It is
  **not** an implementation of the bounded procedure below and must not be used as one.

The separate margin feature was checked on its own `phase2-margin-split` checkout:
29 tests passed, including default-behavior reproduction, live profile overrides and the
rollout B5 margin. This is feature-readiness evidence, not an integration test of that
branch with the audited scorer. Merge/integration and B2 routing remain a gate for Stage E.

### Completed validation

154 distinct targeted checks passed in the audited checkout across unit scaling,
counterfactual equivalence, forecast propagation, shared-state isolation, replay timing and
cache safety, paper-start recording/replay, profile routing, comparator definitions, complete
memory, coupled streams, experiment parameters, planner fallback and oracle separation.
The full 1800 s stored ACC reproduction check was explicitly enabled and passed
(`test_legacy_mode_matches_stored_confirmatory_run`, 191.65 s). The 29 separate-branch
margin checks above are additional and are not counted as active-checkout integration tests.
`git diff --check` passed. Five newly added regression checks failed before the corresponding
scorer/cache/assignment fixes and passed afterward.

No broad claim is made that every optional simulator configuration has been tested.
Unsupported combinations and model-form assumptions retain their documented limits.

## 3. Stage A: preflight and fresh baseline recordings

1. Freeze the audited source, environment versions, machine identity and all resolved model,
   policy and cue parameters in a manifest. Hash every input recording.
2. Re-run focused unit/profile/replay checks and short B1-B5 + A-E configuration smokes.
3. Collect B5_c recordings with unchanged numerical ACC constants, corrected units, complete
   memory and coupled streams, for each load and training seed 200-209: 30 recordings.
   The existing area-rescaled recordings are not a substitute.
4. Store all accepted truth events, the observation/relay calls and the owner grids. Truth
   is used offline to score forecasts; never feed it into the deployed planner information set.
5. Benchmark two replays per load before allocating a search budget. Record peak memory and
   time/configuration; benchmark higher replay worker counts as authorized, with a 4 GB free-memory reserve.

Implemented recording entry point, to run only after the protocol is approved:

```powershell
python -m experiments.refit_sim_truth record --recording-start paper --workers 8
```

## 4. Stage B: bounded shared-estimator calibration

Use the same recordings and event targets for every candidate. Candidate forecasts must use
only the logged robot-accessible information. Fit the shared estimator, not B4's mission score.

Primary score: mean predictable-step NLL per accepted truth event, first per recording, then
equally over seeds and loads. Secondary scores: per-load NLL, frozen-rate occupancy log-loss,
Brier score, count bias, and suppression-on/off diagnostics. Bootstrap whole seed groups,
retaining their load blocks; do not bootstrap individual events or overlapping windows.

### Proposed parameter box (engineering bounds, subject to approval)

| Parameter | ACC reference | Proposed initial range |
| --- | ---: | ---: |
| sigma | 10 m | 5-80 m |
| omega | 450 s | 112.5-1800 s |
| alpha_in | 0.15 | 0.0375-0.60 |
| alpha_inhib | 0.90 | 0-3.60; zero is a diagnostic control |
| mu_base | 2.5e-5 | 6.25e-6-1e-4; one value shared across loads |

Initially hold alpha_cross=0, bg_ema=1e-7, omega_inhib=900 s,
feedback_sigma_scale=0.875, and feedback_omega_scale=2.0. This avoids fitting both an
inhibition duration and its multiplier. Profile fixed parameters on the training recordings
before adding any to the search; additions require an explicit scope/budget decision.
These ranges are reference-centered engineering bounds, not biological estimates.

Budget: at most 24 prediction-only candidates, 48 intervention-aware candidates, and a
3 x 3 final comparison (81 candidate pairs maximum). Include the nominal reference and
no-feedback control. Use fixed, logged, space-filling candidate sets plus at most one local
refinement inside that budget; no expanding grid or unlimited convergence cycles.
Proposed wall-time cap: 4 hours after the replay benchmark. If the estimate exceeds this,
reduce the proposed candidate budget before launching, with the reduction recorded.

Inspect one-parameter profiles of the finalists. If several values are indistinguishable,
prefer the nominal value and label the parameter unidentifiable. Do not widen a bound
automatically. A zero-inhibition optimum is evidence to investigate model adequacy, not a
reason to force a positive coefficient or hide the result.

Implementation gate completed: `experiments/run_bounded_calibration.py` enforces candidate
counts, fixed nuisance parameters, approved bounds, disjoint seeds, recording and cache
identity, and a four-hour deadline that is not reset on resume. It benchmarks worker counts
and compares numerical replay results across them. 23 focused bounded-runner tests passed.
The historical expanding-search command is not used.

## 5. Stage C: validation and freeze

Proposed new development-validation seeds: 210-219, kept separate from fitting and final
evaluation. First score the reference and at most two finalists on the SAME fresh B5_c
nominal-reference recordings, 30 recordings covering the three loads. This avoids comparing
forecast errors on different truths created by each candidate policy.

Prefer the nominal model unless a finalist improves the balanced primary validation score.
Report paired uncertainty and each load separately. Proposed review guardrail: no per-load
increase in Brier score above 0.005 absolute; approve this engineering tolerance before use.
Large NLL/count-bias deterioration at any load requires review even if the pooled score improves.
Do not report a better pooled score as universal improvement.

Then run closed-loop cross-checks on B1, B5 and A/B4 with the selected shared estimator,
checking exposure, generated/completed/missed tasks, response times, predicted-versus-realized
effects and cue state. Do not fit coefficients to these mission comparisons.
If replay gains fail to survive or the estimator suppresses real events into an intensity
floor, stop and document a model-form limitation instead of restarting an unbounded search.

Freeze the selected constants, decision settings, model version and all hashes BEFORE any
fixed-unit evaluation on seeds 300-309. Do not revise settings after seeing these outcomes.

## 6. Stage D: fixed-system results first

Run the nominal corrected-unit arm and validated-calibration arm with the same decision
settings; this isolates estimator calibration. Main evaluation uses 10 paired seeds 300-309,
three loads, and habituation on/off. Prioritize the B1-B5 tables before expensive plan runs.

| Paper label | Repository configuration |
| --- | --- |
| B1 | B1_c: greedy, fixed cue |
| B2 | B2_c: reserved, prior deltaJ, fixed cue |
| B3 | B3_c: reserved STL exposure/coverage, fixed cue |
| B4 | A: full STL, multiple cues; reuse the same rows |
| B5 | B5_c: greedy, freshest cue |

Report B3_multicue_c separately for the archived Table VII service comparison. Preserve
A_legacy_units and the A/B/C/C_gate/C_plan/D_plan/E_plan progression. Recompute any Eq. 4
thresholds only if the timed-recovery variant is included; do not reuse old-unit thresholds.

For B4-B5 exposure, provide absolute paired effects and effects normalized by B1's mean,
with explicit denominators. Report generated/completed/missed counts beside service rates.
Keep the paper's completion-based miss statistic separate from the improvement plan's
90 s deadline miss fraction. Response means describe completed tasks only.

Preliminary tables are exploratory. Do not interpret nonsignificance as equivalence.
The existing service noninferiority margin remains +2 percentage points for E_plan versus
B5_c. Formal confirmatory tests retain their declared multiplicity family and require the
planned sample count; do not label the 10-seed preliminary batch a completed 30-seed study.
If the paper's B4 advantage weakens or disappears, state that result.

## 7. Optional Stage E: decision-setting calibration

Do this only after shared-estimator results, as a separate experiment. It must not block
the first fixed-system tables or be tuned to recreate published effect sizes.

- Separate score margins by valuation scale (legacy utility, STL robustness, Eq. 3 exposure).
  Review the existing feature branch and route B2/B3 as well as A-E explicitly before use.
- Retain assignment weight 0.2. Keep physical cue and truth parameters fixed.
- Give every comparator a declared, comparable tuning budget and identical development
  seed/load coverage. Do not optimize B4 while leaving B1/B2/B3/B5 at arbitrary defaults.
- Report an exposure-service Pareto comparison. Selecting one operating point requires a
  service preference chosen before the held-out run; no exposure/service scalar weight is
  inferred from the desired conclusion.
- Proposed budget: at most 12 decision configurations per baseline, with a separately
  reviewed runtime estimate for rollout-based variants. No test-seed tuning.
- Quantile matching may be reported as a diagnostic, with equal policy/load/seed influence,
  but it is not a mandatory infinite-loop prerequisite for these calibration results.

## 8. Decisions required before launching

1. Approve this two-stage separation: shared-estimator calibration first; decision tuning optional.
2. Approve the proposed parameter box, fixed nuisance parameters, candidate counts and 4-hour cap.
3. Approve new validation seeds 210-219 and the per-load Brier review margin, or select alternatives.
4. For any later policy tuning, select a service operating preference and equal tuning budget.

No search, full recording collection, new evaluation batch, merge or deployment was started
as part of the audit. Existing historical results are preserved.
