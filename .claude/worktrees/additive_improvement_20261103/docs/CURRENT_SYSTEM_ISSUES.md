# Current System Issues

The main problem is that the system is not turning the predictive field into robust end-to-end improvement.

The biggest issues right now are:

1. Preventive deterring generates many candidates but very few completed actions.
2. Patrol and preventive tasks are scored with different objectives.
3. Dispatch and queue limits likely crowd out preventive work before execution.

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
- `docs/SYSTEM_VARIABLES.md`

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
- `docs/SESTPP_INTERVENTION_REFACTOR_SUMMARY.md`

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
- `docs/SYSTEM_VARIABLES.md`

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
- `docs/SESTPP_INTERVENTION_REFACTOR_SUMMARY.md`

## What Should Be Fixed First

1. Simplify the preventive admission pipeline so more strong preventive candidates survive.
2. Put patrol and preventive tasks under one objective.
3. Rework dispatch and queue policy so preventive tasks are not systematically crowded out.
4. Reduce communication overhead or explicitly account for it in task admission.
5. Return to SESTPP calibration and truth-side realism after the control-layer bottlenecks are reduced.

## Thesis-Consistent Component Shortlist

The recent testbench runs are useful for deciding which implemented components are actually helping. The important distinction is:

- what should stay inside the thesis-facing mainline,
- what is worth keeping only as an ablation or supporting control layer,
- and what should remain exploratory or outside the thesis summary for now.

### Components That Still Fit The Thesis Outline

These stay within the thesis outline because they preserve the core architecture:

- decentralized zone coordination,
- intervention-aware SESTPP,
- task generation from the predictive field,
- dispatch / assignment,
- and a preventive deterring branch.

#### 1. Risk-Open Preventive Activation

This is the strongest thesis-consistent component right now.

- Canonical stage: `s1_risk_open_core`
- Why it stays in-scope:
  - It does not remove any thesis-defining mechanism.
  - It removes a legacy heuristic choke point that was not thesis-defining.
- Why it matters:
  - Best exposure among the thesis-consistent deterrence-first stages.
  - Best last-hour bird-deterrence rate.
  - Best completed preventive / deterring work.

This should be treated as the current best thesis-core debugging baseline.

#### 2. Simple Task Management As The Execution Baseline

This is still thesis-consistent as a simplification or ablation baseline, not necessarily as the final thesis planner.

- Canonical stage: `s0_simple_tasks_core`
- Why it stays in-scope:
  - It still uses zone partitioning, SESTPP feedback, task generation, and execution.
  - It simplifies queueing rather than changing the basic thesis architecture.
- Why it matters:
  - Best throughput among the simplification cores.
  - Best task efficiency per travel distance among the simplification cores.

This is useful as the “simple but robust execution” reference line.

#### 3. Capacity-Aware Selection As A Secondary Control Layer

This is still acceptable inside the thesis outline because it lives in planner tuning / admission control, not in a new system architecture.

- Canonical stage: `s1_capacity_aware_selection_core`
- Why it stays in-scope:
  - It preserves extraction -> selection -> assignment.
  - It is a planner-control refinement, not a change to the thesis story.
- Why it matters:
  - Best exposure in the current short core-comparison run.
  - Better response than `s1_risk_open_core`.
- Why it should stay secondary:
  - It weakens deterrence yield relative to `s1_risk_open_core`.
  - It currently looks more like an overload-control component than the main thesis contribution.

This should be treated as an optional load-control layer, not the main thesis claim.

### Components That Are Not Earning Their Complexity

These remain inside the codebase, but current evidence does not justify emphasizing them in the thesis summary.

#### 4. Direct-Conflict Guard, Persistence Locks, And Capacity Budget Layer

Stages:

- `s2_direct_conflict`
- `s3_persistence`
- `s4_capacity_budget`

Current evidence:

- In the long testbench core comparison, these stages are effectively identical to `s1_main_core` on the key deterrence metrics.
- That means these added control layers are currently inert or too weak to justify thesis emphasis.

These should remain secondary implementation controls until a benchmark shows a clear gain.

#### 5. Current Thesis Profile As Implemented

Stage:

- `s5_current_thesis_profile`

Current evidence:

- Its main apparent advantage is reduced communication overhead.
- It is weaker than `s1_risk_open_core` on deterrence-oriented metrics.

So the current thesis profile should not be treated as the strongest end-to-end expression of the thesis method until it is reworked or revalidated.

### Components That Should Stay Outside The Thesis Summary For Now

These are useful experimentally, but they do not cleanly belong in the thesis-facing mainline without reframing the thesis argument.

#### 6. Local Priority Queue Exploration

Variants:

- `row_local_priority_queue`
- `row_local_priority_queue_frequent_repartition`

Why they should stay exploratory:

- They change the coordination / assignment structure materially.
- The more aggressive frequent-repartition version is very good on response time.
- But these variants are not yet the clean thesis story, and they are weaker on deterrence quality than `s1_risk_open_core`.

These are useful experimental lines, not current thesis-summary candidates.

#### 7. Main Native Throughput Machinery

Target:

- `main_native`

Why it should stay outside the thesis summary for now:

- It clearly has stronger execution / throughput machinery.
- But it does not emit the same native deterrence metrics in the current harness.
- So it is not yet a fair thesis-summary comparison on exposure and bird-deterrence quality.

It is a useful engineering reference, not yet a thesis-summary baseline.

### Recommended Thesis-Facing Position

If the thesis outline and thesis summary are to stay stable, the current position should be:

1. Keep `s1_risk_open_core` as the best thesis-consistent core.
2. Use `s0_simple_tasks_core` as the simple execution ablation.
3. Use `s1_capacity_aware_selection_core` as a secondary admission-control experiment.
4. Do not promote the local-priority exploration line or the `main_native` scheduler into the thesis summary unless the thesis framing is explicitly updated.

## Best Documents To Read

If someone needs to understand the current implemented algorithms quickly, these are the best places to start.

- `README.md`
  - high-level system overview
- `docs/SYSTEM_VARIABLES.md`
  - best single reference for active controls and algorithm knobs
- `docs/SESTPP_INTERVENTION_REFACTOR_SUMMARY.md`
  - best explanation of the current intervention-aware SESTPP design
- `docs/EXPERIMENT_EXECUTION_ORDER.md`
  - staged thesis workflow and what each stage is meant to prove
- `results/field_truth_compare/field_truth_compare_report.md`
  - best summary of current field-model quality
- `results/planner_tune_analysis.md`
  - best summary of planner, preventive-yield, and queue-pressure issues
- `results/phase23_finalist_confirm/publication_plots/ADVISOR_SLIDE_SUMMARY.md`
  - best compact summary of the current end-to-end weakness
