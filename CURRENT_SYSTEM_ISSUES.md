# Current System Issues

Purpose: short, easy-to-read summary of the biggest problems in the current intervention-aware deterrence system.

## Bottom Line

The main problem is not that the system lacks an intervention-aware predictive field. The main problem is that the system is not turning that field into robust end-to-end improvement.

The biggest issues right now are:

1. Preventive deterring generates many candidates but very few completed actions.
2. Patrol and preventive tasks are scored with different objectives.
3. Dispatch and queue limits likely crowd out preventive work before execution.
4. Communication overhead is high relative to the observed gain.

The model/truth mismatch is still a risk, but it does not currently look like the first bottleneck to fix.

## Highest-Priority Issues

### 1. Preventive Deterring Is Too Low-Yield

**What is currently implemented**

- Preventive candidates are generated from forecast hotspots and clustered detections.
- Each candidate is scored with a counterfactual future-reduction estimate (`predicted_deltaJ`) and an ETA-based cost.
- Candidates are then filtered by risk, persistence, support, ETA, repeat blocking, utility-per-cost, and capacity/budget limits.

In compact form, the preventive branch is trying to maximize:

```latex
\[
U_{\text{det}}(a) = \Delta J(a) - c_\eta(a)
\]
```

**What is failing**

- The system is not short on preventive candidates.
- It is short on preventive candidates that survive the gate and become completed actions.

**Why this is the top issue**

- This is the core proposed capability of the current system.
- If the preventive branch rarely completes work, the system behaves much closer to prediction-only plus reactive response than to a genuinely intervention-aware planner.

**Key evidence**

- `thesis_summary_24h_sweep_parallel_fast_diagnostic_like.md`
  - S2: about `8262.8` preventive candidates, `8.6` accepted, `1.0` completed model-scored action.
  - S3: about `19066.4` preventive candidates, `31.4` accepted, `0.6` completed model-scored action.
- `results/planner_tune_analysis.md`

**Main references**

- `TaskGenerator.py`
- `DeterrentSystem.py`
- `SYSTEM_VARIABLES.md`

### 2. Patrol And Preventive Work Use Different Objectives

**What is currently implemented**

- Preventive deterring uses explicit counterfactual reduction scoring.
- Patrol uses forecast-hotspot persistence and value weighting.
- In the current patrol path:
  - `predicted_deltaJ = 0`
  - `deltaJ_per_cost = 0`

The patrol branch is currently closer to:

```latex
\[
U_{\text{patrol}}(x)
=
\max(\lambda(x)-\mu(x),0)\,w(x)\,\Omega(\omega,H)\,\Delta A - c_\eta(x)
\]
```

while the preventive branch is using:

```latex
\[
U_{\text{det}}(a) = \Delta J(a) - c_\eta(a)
\]
```

**What is failing**

- Patrol and preventive tasks are not directly comparable under one shared objective.
- That means the planner is not solving one coherent problem of "which action best reduces future exposure."

**Why this matters**

- Even if the field model improves, the planner can still make weak choices because different task types are scored in fundamentally different ways.

**Key evidence**

- `TaskGenerator.py`
- `README.md`

**Main references**

- `TaskGenerator.py`
- `README.md`
- `SESTPP_INTERVENTION_REFACTOR_SUMMARY.md`

### 3. Dispatch And Queueing Likely Crowd Out Preventive Work

**What is currently implemented**

- Direct-detection tasks have absolute priority.
- Remaining tasks are ranked by:
  - utility,
  - `predicted_deltaJ`,
  - `deltaJ_per_cost`,
  - ETA,
  - other tie-breakers.
- Queue admission is limited by per-robot task caps, patrol caps, preventive caps, and preemption/protection rules.

**What is failing**

- The system appears to spend a lot of time in a saturated queue regime.
- Preventive work is likely being filtered twice:
  - first by the preventive admission gate,
  - then again by downstream dispatch and queue pressure.

**Why this matters**

- Upstream field differences only matter if the selected actions actually survive to execution.
- If the queue collapses behavior back to reactive and patrol work, field improvements do not become system improvements.

**Key evidence**

- `results/planner_tune_analysis.md`
- `thesis_summary_24h_sweep_parallel_fast_diagnostic_like.md`
  - large task-cap and patrol-cap rejection counts

**Main references**

- `DeterrentSystem.py`
- `SYSTEM_VARIABLES.md`

### 4. Communication Overhead Is Too High For The Current Gain

**What is currently implemented**

- Detection events are shared near zone boundaries.
- Intervention events are also shared near zone boundaries.
- Intervention messages are filtered by debounce interval, spatial quantization, and minimum weight.

**What is failing**

- The proposed system pays a large communication cost without a robust exposure win.
- Communication grows substantially even when exposure improvement is weak, near zero, or statistically inconclusive.

**Why this matters**

- This weakens the practical value proposition of the intervention-feedback architecture.
- It also suggests the current feedback mechanism is not efficient enough relative to what it adds.

**Key evidence**

- `results/phase23_finalist_confirm/publication_plots/ADVISOR_SLIDE_SUMMARY.md`
  - zero robust exposure winners
  - top config has weak exposure gain with about `69%` more communication
- `thesis_summary_24h_sweep_parallel_fast_diagnostic_like.md`
  - about `84%` communication increase in S2
  - about `72%` communication increase in S3

**Main references**

- `Robot.py`
- `DeterrentSystem.py`
- `README.md`

## Secondary Issue

### Model / Truth Mismatch Is Still Present

**What is currently implemented**

- The predictive field uses self-excitation, cross-boundary excitation, and per-mode inhibitory intervention channels.
- The truth simulator applies recent interventions as decaying spatial-temporal suppression on future truth events.

**What is failing**

- The field-level diagnostics suggest the proposed field is directionally better than prediction-only.
- But subsystem-isolation tests still say the proposed SESTPP is not consistently better in isolation.

**Why this is secondary for now**

- This still matters technically.
- But the current evidence suggests that planner/control integration is the more immediate bottleneck.

**Key evidence**

- `results/field_truth_compare/field_truth_compare_report.md`
  - proposed field is better on forecast quality in that diagnostic
- `results/sestpp_subsystem_ablations/spacetime_w300/sestpp_subsystem_report.md`
  - proposed SESTPP is not consistently better in subsystem isolation yet

**Main references**

- `SESTPP.py`
- `DeterrentSystem.py`
- `SESTPP_INTERVENTION_REFACTOR_SUMMARY.md`

## What Should Be Fixed First

1. Simplify the preventive admission pipeline so more strong preventive candidates survive.
2. Put patrol and preventive tasks under one objective.
3. Rework dispatch and queue policy so preventive tasks are not systematically crowded out.
4. Reduce communication overhead or explicitly account for it in task admission.
5. Return to SESTPP calibration and truth-side realism after the control-layer bottlenecks are reduced.

## Best Documents To Read

If someone needs to understand the current implemented algorithms quickly, these are the best places to start.

- `README.md`
  - high-level system overview
- `SYSTEM_VARIABLES.md`
  - best single reference for active controls and algorithm knobs
- `SESTPP_INTERVENTION_REFACTOR_SUMMARY.md`
  - best explanation of the current intervention-aware SESTPP design
- `EXPERIMENT_EXECUTION_ORDER.md`
  - staged thesis workflow and what each stage is meant to prove
- `results/field_truth_compare/field_truth_compare_report.md`
  - best summary of current field-model quality
- `results/planner_tune_analysis.md`
  - best summary of planner, preventive-yield, and queue-pressure issues
- `results/phase23_finalist_confirm/publication_plots/ADVISOR_SLIDE_SUMMARY.md`
  - best compact summary of the current end-to-end weakness
