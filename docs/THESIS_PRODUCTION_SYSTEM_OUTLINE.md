# Final Production System Outline

This outline mirrors the structure of `etc/archive_docs/Thesis_Outline_GBasus.pdf`, but it describes the implemented production system in this repository rather than the original proposal-stage architecture.

## 1.1 Working Title

Intervention-Aware Predictive Multi-Robot Bird Deterrence System for Vineyard Protection

## 1.2 Why This Final System Fits the Existing Framework

The production system now implements the full closed-loop architecture that the original outline proposed:

- health-weighted decentralized zone partitioning with robot-neighbor relationships,
- a per-robot online SESTPP forecast with self-excitation and mode-dependent intervention inhibition,
- direct-detection deterring tasks plus forecast-driven patrol and preventive deterring tasks,
- task extraction, selection, dispatch, and motion execution inside one persistent runtime,
- boundary sharing of both detections and completed intervention events,
- value-weighted exposure, response-time, forecast, suppression, habituation, STL robustness, and communication metrics,
- reproducible calibration, experiment, and testbench workflows around the runtime.

In the current codebase, these pieces are implemented primarily in `DeterrentSystem.py`, `SESTPP.py`, `TaskGenerator.py`, `planner_task_estimation.py`, `planner_dispatch.py`, and `system_structure.py`.

## 1.3 Core System Goal

The production goal is to run a decentralized multi-robot deterrence loop that:

1. responds immediately to observed bird activity,
2. predicts near-future hotspot risk from recent detections,
3. updates that forecast after completed deterrence actions, and
4. reduces value-weighted bird exposure while respecting robot motion, queue capacity, and communication limits.

## 1.4 Final System Objectives

1. Maintain a real-time spatial risk field for each robot zone using local detections and shared boundary events.
2. Represent completed deterrence actions as suppressive interventions with mode-dependent strength, spread, and decay.
3. Generate both reactive and predictive tasks from one shared forecasted field.
4. Score preventive actions by either legacy predicted future exposure reduction or opt-in counterfactual STL robustness improvement.
5. Model cue habituation so repeated use of the same deterrent mode can reduce realized suppression effectiveness.
6. Coordinate multiple robots under assignment, dispatch, and admission constraints that prevent queue collapse.
7. Evaluate the system with metrics that reflect agricultural impact, responsiveness, deterrence effectiveness, habituation, STL robustness, travel cost, and communication overhead.

## 1.5 Problem Setting and Notation

Let:

- `Omega` denote the vineyard workspace,
- `r in R` index robots,
- `Omega_r` denote the zone owned by robot `r`,
- `E_r = {(x_i, t_i)}` denote detections maintained by robot `r`,
- `U_r = {(z_j, tau_j, m_j)}` denote completed deterrence actions with mode `m_j`,
- `w(x)` denote the value weighting over the vineyard,
- `lambda_r(x, t)` denote the robot-local forecast intensity field,
- `eta(z, m, t)` denote the habituation effectiveness of cue mode `m` in cell `z`.

The production system solves a repeated online control problem: given the current robot poses, local forecast fields, active task queue, and recent interventions, decide which robots should execute reactive deterring, preventive deterring, or patrol actions next.

## 1.6 Production Environment and Truth Model

### 1.6.1 Spatial Value Surface

The vineyard is not treated as uniform. The runtime builds a value-weighted map that emphasizes vineyard rows and field edges:

```text
w(x, y) = 1 + row_w(x, y) + edge_w(x, y)
```

This value map is used in both the simulator truth process and the reported exposure metric.

### 1.6.2 Ground-Truth Bird Process

The production simulator uses an event-driven self-exciting truth process with suppression from recent deterrence actions. Background truth events are sampled over the value surface, offspring events create spatial-temporal clustering, and each candidate truth event is filtered by recent deterrence history:

```text
p_keep(x, y, t) = exp(-s(x, y, t))
```

where `s(x, y, t)` is the accumulated suppressive effect of recent interventions. This makes deterrence actions affect both the truth process and the robot forecast loop.


### 1.6.3 Habituating Ground Truth

The production truth model optionally scales each completed deterrence event by a per-cell, per-cue effectiveness value:

```text
s_event(x, y, t) = eta(z, m, tau) * beta_m * K_m(x, y) * exp(-(t - tau) / omega_m)
```

The effectiveness state recovers toward `1.0` over time and decreases when a cue is applied in the same cell. This makes repeated cue use less effective in the simulated world. The non-habituating control sets `enable_habituation=False` or `habituation_kappa=0.0`, which keeps application-time effectiveness at `1.0`.
## 1.7 Production Forecast Model

Each robot carries an `OnlineSESTPP` model over its zone. The implemented production forecast is:

```text
lambda_r(x, t) =
max(0, mu_r(x) * m(t) + trigger_mass_r(x, t) - inhib_mass_r(x, t))
```

where:

- `mu_r(x)` is the local background field,
- `m(t)` is the time-of-day multiplier,
- `trigger_mass` accumulates self- and cross-excitation from detections,
- `inhib_mass` is the sum of persistent intervention inhibition channels.

The current implementation extends the original single inhibition grid into persistent per-mode channels:

- `formation`,
- `laser`,
- `biosonic`,
- plus a default channel for backward compatibility.

Each mode can keep its own `beta`, `sigma`, and `omega` behavior over time. Hotspots are extracted from the excess field `lambda - mu`, not from raw background rate alone.

## 1.8 Planning and Task Selection in Production

### 1.8.1 Task Sources

The production planner draws task candidates from three sources:

1. direct detections for immediate reactive deterring,
2. forecast hotspots for patrolling,
3. forecast hotspots, border hotspots, and clustered detections for model-scored preventive deterring.

### 1.8.2 Patrol Scoring

Patrol candidates are scored from forecast persistence over a finite horizon:

```text
U_patrol(x) = forecast_benefit(x) - c_eta(x)
```

where benefit is the value-weighted excess field integrated over the patrol horizon and `c_eta` captures travel and execution cost.

### 1.8.3 Preventive Deterring Scoring

Preventive deterring candidates use the counterfactual reduction estimator in `planner_task_estimation.py`:

```text
U_det(a) = predicted_deltaJ(a) - c_eta(a)
deltaJ_per_cost(a) = predicted_deltaJ(a) / c_eta(a)
```

The estimator builds a local intervention footprint, integrates available excess risk over a finite horizon, and caps the predicted reduction by what is actually available to suppress.


### 1.8.4 Habituation-Aware STL Predictive Value

The proposal STL path is implemented as an opt-in predictive utility mode:

```text
predictive_utility_mode = "stl_robustness"
```

For a candidate predictive action `a` and robot `r`, the planner computes:

```text
U(a,r) = robustness(Phi_r, trace_with_action) - robustness(Phi_r, trace_without_action)
```

The production mission clauses are exposure, coverage, and optional habituation:

```text
Phi = phi_exp AND phi_cov AND phi_hab
```

B3 uses exposure and coverage only. B4 adds the habituation clause, causing repeated and less-effective cues to be penalized during candidate scoring. The resulting `U(a,r)` is mirrored into the existing task fields used by dispatch, so the dispatch logic remains unchanged.
### 1.8.5 Admission, Assignment, and Dispatch

The production runtime then applies:

- persistence and repeat-block controls,
- ETA and support thresholds,
- direct-conflict protection for reactive work,
- per-robot and per-cycle preventive admission limits,
- patrol and preventive queue caps,
- robot assignment based on capability, ETA, load, zone affinity, health, priority, and task value.

Direct-detection deterring retains absolute priority. Remaining patrol and model-scored preventive tasks share one lexicographic dispatch order based on:

1. utility / score,
2. `predicted_deltaJ`,
3. `deltaJ_per_cost`,
4. lower ETA.

In the current thesis-facing production path, preventive admission still follows the restored heuristic gate, while newer selective-admission controls remain available in the codebase for controlled experiments and tuning.

## 1.9 Decentralized Communication and Closed-Loop Feedback

The production system uses local event-triggered communication instead of full global synchronization.

- Detection events near zone borders are shared to neighboring robots as cross-boundary excitation.
- Completed deterrence actions near zone borders are shared as intervention messages that preserve mode, weight, spread, and decay.
- Message cost is tracked explicitly through boundary-message counts and byte estimates.
- Intervention sharing is filtered by debounce interval, spatial quantization, and minimum message weight.

This yields a decentralized but feedback-aware architecture: actions taken by one robot can change the predicted field of its neighbors when those actions occur near shared boundaries.

## 1.10 Implementation in the Current Codebase

### 1.10.1 Runtime Orchestration

`DeterrentSystem.py` runs the persistent loop and produces structured stage outputs for:

- truth generation,
- forecast update,
- task generation,
- dispatch,
- motion execution with row-constrained travel and headland lane switching,
- communication / feedback,
- metrics,
- telemetry and tracking export.

### 1.10.2 Forecast and Robot Interfaces

`SESTPP.py` implements the online field model. `Robot.py` provides the robot-local wrapper for:

- ingesting detections,
- ingesting intervention events,
- exporting boundary detections,
- exporting boundary intervention events.

### 1.10.3 Planning Stack

The production planning stack is split across:

- `planner_task_extraction.py` for candidate extraction,
- `TaskGenerator.py` for patrol and preventive candidate scoring,
- `planner_task_estimation.py` for legacy counterfactual exposure reduction and STL counterfactual robustness estimation,
- `planner_task_selection.py` for optional preassignment filtering,
- `planner_dispatch.py` for dispatch-time gating and assignment selection.

### 1.10.4 Configuration, Calibration, and Observability

The production system is documented and instrumented through:

- `system_structure.py` for structured runtime snapshots and STL/habituation config exports,
- `planner_profiles.py` for named planner presets,
- `docs/SYSTEM_VARIABLES.md` for configuration surface documentation,
- `experiments/` for calibration and thesis-facing validation,
- `testbench/` for shared benchmark comparisons,
- `tracking_export.py` and `demos/streamlit_app.py` for observability.

## 1.11 Experimental Validation and Baselines

The production system is evaluated against the same main baselines used throughout the thesis work:

1. `reactive`: direct-response deterring only,
2. `prediction_only`: patrol forecasting without intervention feedback,
3. `proposed`: intervention-aware forecasting and preventive deterring.
4. `B3_res_stl_nohab` / `B4_res_stl_full`: STL predictive-value baselines for the habituation study.

The current staged validation flow is:

1. SESTPP calibration,
2. field-divergence verification,
3. field-divergence confirmation,
4. planner / assignment tuning,
5. optional assignment-method comparison,
6. robot-scaling and long-horizon confirmation.

Primary reported metrics include:

- value-weighted exposure,
- mean response time,
- birds deterred percentage,
- habituation effectiveness and cue-variety metrics,
- STL robustness clause metrics,
- truth suppression rate,
- forecast recall / precision at `k`,
- completed tasks and task efficiency,
- travel / energy proxies,
- boundary message count and communication bytes.

## 1.12 Final System Contributions

The implemented production system contributes:

- an online intervention-aware SESTPP forecast model with persistent per-mode inhibition channels,
- a closed-loop simulator where completed deterrence actions alter both future truth events and future forecasts,
- a shared planning pipeline spanning reactive deterring, patrol, and model-scored preventive deterring,
- decentralized boundary communication for both detections and interventions,
- a reproducible experiment and benchmark framework around the runtime,
- a production habituation-aware STL predictive value path with paired-seed validation evidence.

## 1.13 Implemented Deliverables and Current Scope

Implemented deliverables now present in the repository include:

- intervention-aware online forecasting,
- mode-dependent deterrence actions,
- legacy counterfactual preventive scoring and opt-in STL robustness preventive scoring,
- queue- and dispatch-aware multi-robot execution,
- structured telemetry and runtime snapshots,
- thesis-facing calibration and comparison workflows.

The production system should therefore be described as an implemented end-to-end architecture, not as a proposed extension. The remaining thesis work is primarily about analysis, validation, comparison, and framing rather than missing core system mechanisms.

## 1.14 Final Thesis Chapter Outline

1. Introduction and vineyard bird-deterrence motivation
2. Related work in multi-robot coordination, persistent monitoring, hotspot prediction, and intervention-aware event modeling
3. Production system overview and closed-loop runtime architecture
4. Intervention-aware SESTPP forecast model and mode-dependent suppression design
5. Task extraction, scoring, dispatch, and motion execution in the production planner
6. Calibration workflow, baselines, and experimental methodology
7. Results, ablations, habituation-aware STL evidence, operational tradeoffs, and discussion
8. Conclusions, limitations, and future extensions
