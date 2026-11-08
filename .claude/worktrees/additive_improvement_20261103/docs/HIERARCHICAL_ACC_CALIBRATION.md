# Fair ACC calibration with frozen inheritance

Approved protocol, 2026-10-30. Implemented by
`experiments/run_hierarchical_calibration.py` in the audited worktree.
Calibration is local to the experiment; global runtime defaults are not deployed.

## Ownership and controlled settings

The shared estimator is fitted on **new B1 recordings**. B1 then owns shared
task-generation thresholds/costs, budget, ETA limits and forecast horizon, and
the legacy admission margin. B2 inherits B1 and owns reservation fraction/window,
override slack, and its ΔJ admission margin. B3 inherits B2 and owns the STL
admission margin. B4 inherits B3; B5 inherits B1. B4/B5 enable their paper-defined
cue/habituation additions without invented tuning parameters.

Every child rejects numerical overrides outside its ownership registry. Each frozen
configuration records its parent hash, configuration hash, actual additions, scores,
and source identity. All shared fitted estimator values remain identical across B1–B5.
Public margin arguments are `model_deterring_score_margin_legacy`, `_deltaJ`, `_stl`,
and `_eq3`; unset arguments retain the resolved single-margin behavior. The production
profile overlay has precedence, and B5 continuation rollouts consume the legacy margin.
The calibration materializes profiles and disables subsequent profile/manifest loading.
Live generator state is checked against the intended configuration before output is accepted.

All arms use corrected `mass_per_cell` units, complete intervention memory, coupled
exogenous streams, 1800 seconds, no warmup, the paper geometry/fleet and physical cue
and habituation dynamics. B1–B3 retain the fixed laser cue. B3 is the paper's fixed-cue
definition; auxiliary multi-cue B3 is not silently substituted.

STL requirements retain `E_star=5`, `T_cov=1200 s`, `W=600 s`, `eta_min=0.4` and paper
theta. No quantile matching or numerical rescaling of these requirements is performed:
the stamp correction changes the field model rather than the exposure metric's units.
The approved forecast horizon search is a shared B1 decision parameter, inherited by
STL descendants. Preserve the improvement plan's A/B4 forecast-correction exception
and same-state diagnostic shadows; other arms retain their declared correction settings.
Consequently the B3/B4 contrast includes these declared architectural differences.

## Finite selection and data roles

- Training seeds 200–209; development seeds 210–219. Both groups have been used before.
- One configuration per system across spare/heavy/overload loads, weighted equally.
- Fit the bounded five-parameter estimator with the existing 24/48/9 candidate stages
  (81 maximum), unchanged nuisance values and existing NLL/Brier guardrails. The original
  four-hour search deadline remains a hard limit; no candidate-budget shrinking or automatic
  expansion is used. An interrupted/incomplete search does not silently select a finalist.
- If no estimator finalist passes, explicitly retain the numerical ACC reference and label
  the estimator calibration unsuccessful. Continue the policy stages with that common model.
- Policy stages have at most 48 candidates. Include the paper-reference addition. B1 uses
  budgets {3,4,6}, ETA {90,120} s, horizons {240,300,420} s. Positive thresholds/costs use
  multipliers {.001,.01,.1,1,10} of their numerical paper references. These are hotspot and
  risk floors, preventive/patrol costs, and the busy-fallback ΔJ/cost threshold.
- B2 uses reservation fractions {.10,.25,.40}, windows {300,600} s, override slack
  {60,90,120} s. B3 searches only its STL margin.
- New margins use training-only score-gap quantiles {0,.10,.25,.50,.75,.90,1} plus the
  numerical paper reference. Empty diagnostic samples leave only the reference margin;
  this is recorded rather than fabricating a distribution. Freeze the grid before selection.
- Sample oversized products without replacement with NumPy RNG seed 0. Rank candidates by
  mean exposure normalized by the numerical-ACC B1 mean at each load. Evaluate the training
  top three on development seeds and freeze the development winner. Exact ties prefer the
  smallest squared reference-relative parameter displacement, then candidate index.
- Service metrics never influence selection. Boundary winners are recorded without expansion.

Fresh seeds 220–229 validate the frozen estimator in closed-loop recordings under all five
policies; failures are reported without downstream retuning. Evaluation seeds 300–309 run
both calibrated and unchanged-constant fixed-unit B1–B5 with habituation on and off.
Reports include paired seed bootstrap intervals, exposure, completion-based miss rate,
deadline misses, response times, coverage robustness and habituation. Raw finite metrics
remain available even when no cross-system contrast is defined.

## Running and resuming

Use the existing Python **3.10** scientific environment, not the shell's default Python 3.8.
From this worktree:

```powershell
& C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -u -m experiments.run_hierarchical_calibration --phase all
```

`--dry-run` prints the configuration/seed roles without simulations or experiment output.
`--phase estimator` stops after estimator selection; `--phase policy` stops after freezing
the hierarchy and exporting the A–E inputs. `--phase all` also runs fresh validation and
B1–B5 evaluation. The **separate A–E evaluation** is available once configurations are frozen:

```powershell
& C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -u -m experiments.run_hierarchical_calibration --phase improvement
```

A reuses B4's identical evaluation runs. B/C inherit B4's calibration; D/E inherit B5's.
Each retains the improvement plan's explicit algorithmic changes, without retuning. Nested
rollout planners run one outer job at a time. These are preliminary ten-seed results; the
existing 30-seed confirmatory protocol remains separate.

Default output: `results/hierarchical_acc_calibration/`. `status.json` and `run.log` show
progress; `estimator/status.json` and `estimator.log` describe estimator replay. The source
manifest includes untracked runtime modules as well as tracked code. Existing checkpoints
must match source, machine, configuration, seed, load and habituation condition. Recordings
are atomically published; stale identities fail instead of being reused. Do not edit runtime
source during a run. A live `RUNNING.lock` prevents concurrent orchestrators; inspect its PID
before removing a lock left by a terminated process.

Worker counts are benchmarked before collection, capped by physical cores and available
memory with a 4 GB reserve. Stopping for memory or another failure preserves completed
checkpoints. Repeat the same command to resume compatible output; expired estimator search
deadlines require explicit review rather than silently granting a new budget.
