# Fixes

This file records issues that were diagnosed well enough to justify a concrete fix or a canonical debugging baseline.

## 2026-04-02 - Heuristic Risk Gate Blocked The Preventive Branch

Status:
- Fixed in the simplification ladder as `s1_risk_open_core`
- Not yet adopted as the default behavior in `s5_current_thesis_profile`

Problem:
- The preventive branch was producing many candidates but zero generated, accepted, or completed model-scored tasks.
- This made the proposed planner behave much closer to prediction-only plus reactive response than to a true intervention-aware preventive planner.

Evidence Before The Fix:
- `s1_main_core`: `3494.2` preventive candidates, `0.0` generated, `0.0` accepted, `0.0` completed
- `s5_current_thesis_profile`: `3151.4` preventive candidates, `0.0` generated, `0.0` accepted, `0.0` completed

Root Cause:
- The heuristic preventive risk gate in `TaskGenerator.py` was rejecting nearly every candidate that passed the field check.
- Active defaults during failure:
  - `model_deterring_risk_threshold = 0.35`
  - `model_deterring_risk_scale = 1e-4`
- In practice this made the preventive branch effectively dead.

Fix Implemented:
- Added a canonical simplification stage `s1_risk_open_core` in `simplification/stages.py`
- Kept the stripped-down main runtime from `s1_main_core`
- Forced the heuristic preventive risk gate open with:
  - `model_deterring_risk_threshold = 0.0`
  - `model_deterring_risk_scale = 1e-4`
- Updated `simplification/compare_stages.py` and `simplification/README.md` so the new stage is part of the standard stage ladder and reporting flow

Result After The Fix:
- `s1_risk_open_core` with `5` runs and `7200s` horizon:
  - `2.860%` exposure improvement vs `prediction_only`
  - `1.890%` exposure improvement vs `reactive`
  - `408.0` generated model-scored tasks
  - `24.0` accepted
  - `18.6` completed

What This Fix Changed:
- The preventive branch is now active in the simplification ladder.
- Downstream planner behavior can now be debugged directly instead of being masked by the risk gate.

Next Fix:
- Dispatch and queue saturation after the branch opens.
- Evidence from `s1_risk_open_core`:
  - `64401.0` task-cap rejections
  - `1166.8` model-deterring cap rejections
  - `65567.8` total planner rejections
- Next target files:
  - `planner_dispatch.py`
  - `DeterrentSystem.py`

Reproduction:

```powershell
python -m simplification.run_stage --stage s1_risk_open_core --num-runs 5 --t-end 7200 --time-metrics-period-s 300 --quiet
python -m simplification.compare_stages --main-stage s5_current_thesis_profile
```

## 2026-04-02 - Added Capacity-Aware Preassignment Selection

Status:
- Implemented in the selection-stage split
- Added to the simplification ladder as `s1_capacity_aware_selection_core`
- Smoke-tested only; not yet validated with the 4h/6h comparison stack

Problem:
- After the preventive branch was reopened, the next dominant failure was queue and task-cap saturation.
- The runtime had SESTPP-driven task extraction and assignment/dispatch, but no explicit pre-assignment admission controller.
- That meant overload was being handled late by dispatch rejection instead of earlier by a controlled selection stage.

Fix Implemented:
- Added a concrete pre-assignment policy `capacity_aware_greedy` in `planner_task_selection.py`
- Kept direct-detection tasks reserved first
- Added a greedy admission rule for the remaining extracted tasks:
  - maximize marginal gain per expected service cost
  - obey per-owner total/patrol/model-det capacity estimates from the current active load
  - penalize spatially redundant nearby tasks before assignment
- Added stable rejection reasons for this stage such as:
  - `capacity_exhausted`
  - `patrol_capacity_exhausted`
  - `model_det_capacity_exhausted`
  - `redundant_overlap`
  - `utility_below_threshold`
- Added a simplification stage `s1_capacity_aware_selection_core` in `simplification/stages.py`

What This Fix Changed:
- The system now has an explicit block between:
  - task extraction from SESTPP
  - robot-task assignment / dispatch
- This makes admission control a separate, testable subsystem instead of burying all overload handling inside dispatch.

Why This Is The Right Structural Addition:
- It matches the diagnosed bottleneck after the risk-gate fix: too many extracted tasks reaching a very small active-task cap.
- It preserves the thesis-friendly separation:
  - extraction
  - selection
  - assignment
- It creates a place to test stronger research-backed admission rules later without rewriting dispatch.

Next Step:
- Benchmark `s1_capacity_aware_selection_core` against `s1_risk_open_core`
- Recommended horizons:
  - `4h` for faster iteration
  - `6h` for confirmation
- Primary metrics:
  - exposure
  - birds_deterred_pct
  - model-scored completions
  - planner_rejected_task_cap
  - communication

Reproduction:

```powershell
python -m simplification.run_stage --stage s1_capacity_aware_selection_core --num-runs 1 --t-end 3600 --time-metrics-period-s 300
```

## 2026-04-03 - Testbench Component Shortlist For Thesis Summary

Status:
- Documented from the shared testbench runs
- No default runtime change made yet

Problem:
- The repo now has several working branches and experimental planner variants.
- We needed a clear answer to which components can still be emphasized in the thesis outline and thesis summary without changing the thesis story.

Evidence Used:
- `results/testbench/core_comparison_long/summary_by_metric.csv`
- `results/testbench/core_comparison/summary_by_metric.csv`
- `results/testbench/core_comparison_long/report.md`
- `results/testbench/core_comparison/report.md`

Conclusion:
- Keep `s1_risk_open_core` as the canonical thesis-consistent core:
  - best deterrence-oriented performance among the thesis-consistent stages
  - best last-hour bird-deterrence rate
  - best completed deterring work
- Keep `s0_simple_tasks_core` as the simple execution ablation:
  - best throughput among the simplification cores
  - useful as the minimal robust execution reference
- Keep `s1_capacity_aware_selection_core` only as a secondary load-control experiment:
  - good for exposure / response tradeoff
  - weaker than `s1_risk_open_core` on deterrence yield
- Do not emphasize these in the thesis summary yet:
  - `s2_direct_conflict`
  - `s3_persistence`
  - `s4_capacity_budget`
  - current `s5_current_thesis_profile`
  because they are currently inert or underperforming on the key deterrence metrics
- Keep these outside the thesis summary for now:
  - `row_local_priority_queue`
  - `row_local_priority_queue_frequent_repartition`
  - `main_native`
  because they are either exploratory architectural changes or not yet directly comparable on the native deterrence metrics

What This Changes:
- The thesis-facing roadmap is now narrower and clearer.
- The current best thesis-consistent story is:
  - risk-open preventive activation
  - simple execution baseline
  - optional secondary admission-control experiment
- This prevents the thesis summary from drifting toward components that are either exploratory or not yet justified by the shared benchmark.

Recommended Next Step:
- Keep using `s1_risk_open_core` as the main thesis debugging baseline.
- Only promote another component into the thesis summary after it beats that baseline on deterrence-oriented metrics in the shared testbench.

Reproduction:

```powershell
python -m testbench.run_testbench --config testbench\core_comparison_config.json --outdir results\testbench\core_comparison_long --max-workers 4
```
