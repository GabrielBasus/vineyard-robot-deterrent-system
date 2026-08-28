# Vineyard Robot Deterrent System

This repository contains a simulation framework for multi-robot bird deterrence in vineyard-like environments.  
It implements an intervention-aware spatiotemporal intensity model, decentralized zone coordination, task generation/scoring, and experiment runners for thesis evaluation.

## What This Repo Includes

- **Online intensity model (`SESTPP.py`)**
  - Self-exciting trigger mass + inhibitory intervention mass
  - Separate temporal decays and spatial stamping
- **Robot + zone coordination (`Robot.py`, `ZonePartitioner.py`)**
  - Health-weighted zone partitioning and neighbor sharing
  - Boundary event exchange (detections + interventions)
- **Task generation and scoring (`TaskGenerator.py`)**
  - Candidate generation from hotspots
  - Benefit-vs-cost action scoring for patrol and deterrence
  - Optional habituation-aware STL robustness scoring for predictive deterring
- **System simulation (`DeterrentSystem.py`)**
  - Ground-truth event process
  - Closed-loop intervention feedback
  - Optional per-cell/per-cue habituation in the truth process
  - Metrics collection and baseline comparisons
- **Habituation-aware STL package (`habituation_stl/`)**
  - Signal Temporal Logic robustness operators
  - Per-cell/per-mode cue habituation state
  - Counterfactual predictive task value `U(a,r)`
  - Reference tests and production integration helpers
- **Monitoring and telemetry (`telemetry_sim.py`, `demos/streamlit_app.py`)**
  - Live telemetry CSV output
  - Streamlit dashboard with map/tasks/robot diagnostics
- **Experiment scripts**
  - `experiments/run_24h_experiment.py` (sequential 24h sweep, headless, thesis summary outputs)
  - `experiments/run_24h_experiment_parallel.py` (multiprocessing 24h sweep, headless, faster)
  - `demos/demo_optimal_proposed.py` (single-file visual demo using best proposed config)

## Workspace Layout

The repository is organized by role so the root stays reserved for core runtime modules. Supporting scripts now live in:

- `demos/`
- `diagnostics/`
- `docs/`
- `experiments/`
- `labs/`
- `plots/`

The directory map and run conventions are documented in `docs/WORKSPACE_LAYOUT.md`.

## Mathematical Implementation

This section describes the implemented math from environment input to reported output. The main runtime lives in `DeterrentSystem.py`, the online field model lives in `SESTPP.py`, task scoring lives in `TaskGenerator.py`, and the counterfactual deterrence estimator lives in `planner_task_estimation.py`.

### 1. Spatial Value Surface

The simulator starts from a geometric map of vineyard rows and field edges. Every world point `(x, y)` is given a value weight:

```text
d_row(x, y) = distance to the nearest vineyard-row centerline
row_w(x, y) = row_gain                    if d_row(x, y) <= row_width_m / 2
              0                           otherwise

d_edge(x, y) = distance to the outer field boundary
edge_w(x, y) = edge_gain * exp(-d_edge(x, y) / edge_scale_m)

w(x, y) = 1 + row_w(x, y) + edge_w(x, y)
```

In the main runtime this is implemented by `value_weight(...)` in `DeterrentSystem.py`. The same value surface is reused in scoring and in the final exposure metric.

### 2. Ground-Truth Bird Process

The truth process is a discrete-time self-exciting spatial point process with suppression from recent deterrence events.

First, a base spatial sampling grid is built from the positive value weights:

```text
W_grid(i, j) = max(w(x_i, y_j), 0)
P_base(i, j) = W_grid(i, j) / sum(W_grid)
```

At each step of duration `dt`, the number of base events is:

```text
lambda_base = mu_true * mean(W_grid) * area
N_base ~ Poisson(lambda_base * dt)
```

Each base event location is sampled from `P_base`.

Every accepted truth event also produces offspring:

```text
N_off ~ Poisson(alpha_true)
Delta t ~ Exponential(mean = omega_true)
Delta x, Delta y ~ Normal(0, sigma_true)
```

This gives a truth process with both background events and clustered after-events.

### 3. Suppression From Robot Deterrence

Truth events are not accepted automatically. Each candidate truth event is filtered by recent deterrence actions. For a candidate event at `(x, y, t)`, every recent deterrence event `z` contributes:

```text
c_z(x, y, t) =
    beta_z
    * exp(-||[x, y] - [x_z, y_z]||^2 / (2 * sigma_z^2))
    * exp(-(t - t_z) / omega_z)
```

The total suppression mass is:

```text
s(x, y, t) = sum_z c_z(x, y, t)
```

The candidate truth event survives with probability:

```text
p_keep = exp(-s)
p_suppress = 1 - p_keep
```

The simulator samples a Bernoulli draw with `p_keep`. If the event is suppressed, it contributes to:

```text
truth_suppressed_events
birds_deterred_pct = 100 * truth_suppressed_events / truth_candidate_events
truth_suppression_rate = truth_suppressed_events / truth_candidate_events
```

This is implemented in `_suppression_eval(...)` and the truth-update loop in `DeterrentSystem.py`.

### 4. Online SESTPP Forecast Model

Each robot carries an online SESTPP model over its grid. The state is:

- `mu`: background rate grid
- `trigger_mass`: self- and cross-excitation grid
- `inhib_channels[m]`: one inhibition grid per intervention mode

The time-of-day modulation is:

```text
phi(t) = 2 * pi * (t mod 24h) / 24h
m(t) = max(0.2, 1 + 0.4 * sin(phi) + 0.15 * sin(2 * phi))
```

State decay over one step is:

```text
trigger_mass <- trigger_mass * exp(-dt / omega)
inhib_channel_m <- inhib_channel_m * exp(-dt / omega_inhib,m)
```

Event stamps are added by Gaussian kernels:

```text
local detection stamp amplitude       = alpha_in
cross-boundary stamp amplitude        = alpha_cross * weight
intervention stamp amplitude          = alpha_inhib * beta_u
```

The forecast intensity is then:

```text
lambda(x, y, t) = max(0, mu(x, y) * m(t) + trigger_mass(x, y) - inhib_mass(x, y))
inhib_mass = sum_m inhib_channel_m
```

This is implemented in `OnlineSESTPP` in `SESTPP.py`.

### 5. Hotspot Extraction

Hotspots are selected from the largest cells of either `lambda` or `lambda - mu`. In the main runtime the excess field is used:

```text
hotspot_score(x, y) = lambda(x, y) - mu(x, y)
```

The highest-scoring cells are greedily kept while enforcing a merge radius so nearby cells collapse into one hotspot.

### 6. Patrol Task Scoring

For a patrol candidate at `(x, y)`, the expected field benefit is integrated over a finite horizon:

```text
time_factor = omega * (1 - exp(-horizon_s / omega))
benefit = max(0, patrol_field_score(x, y)) * w(x, y) * time_factor * DeltaA
```

The travel-and-service cost is:

```text
cost_eta = w_eta * (distance / speed + spinup) + fixed_cost
```

The patrol task utility is:

```text
utility_patrol = benefit - cost_eta
score_patrol = utility_patrol
```

This is implemented inside `TaskGenerator.periodic_patrolling(...)`.

### 7. Model-Scored Preventive Deterrence

Preventive deterring tasks support two predictive value modes.

The legacy mode uses a counterfactual exposure-reduction estimate. For a candidate action at `(x, y)`:

```text
available_integral(x, y) =
    max(lambda - baseline_grid, 0) * omega * (1 - exp(-horizon_s / omega))
```

The intervention footprint uses a normalized Gaussian kernel and an intervention decay integral:

```text
suppression_amp = alpha_inhib * beta_u
suppression_here =
    suppression_amp
    * kernel_here
    * omega_u * (1 - exp(-horizon_s / omega_u))
```

The reduction at each grid cell is capped by what is available to suppress:

```text
reduction_here = min(available_here, suppression_here)
```

The predicted weighted reduction is:

```text
predicted_deltaJ =
    sum_cells w(cell) * reduction_here * DeltaA
```

The preventive action utility and normalized score are:

```text
utility_deterring = predicted_deltaJ - cost_eta
deltaJ_per_cost = predicted_deltaJ / max(cost_eta, 1e-6)
```

This is implemented in `estimate_counterfactual_reduction(...)` in `planner_task_estimation.py` and consumed by `TaskGenerator.py`.
The habituation-aware STL mode is selected with:

```text
predictive_utility_mode = "stl_robustness"
```

In this mode, the candidate value is the counterfactual robustness improvement:

```text
U(a, r) = rho(Phi_r, xi_with_action) - rho(Phi_r, xi_without_action)
```

where `Phi_r` is the robot-local STL mission specification and `xi` is the predicted local signal trace. The active production clauses are:

- `exp`: keep value-weighted exposure below `stl_E_star`
- `cov`: keep coverage age below `stl_T_cov_s`
- `hab`: prefer cues whose effectiveness is above `stl_eta_min`

`TaskGenerator.py` stores the resulting value in `predictive_stl_U` and mirrors it into `utility`, `score`, `predicted_deltaJ`, and `deltaJ_per_cost` so existing dispatch policies continue to work without command or dispatcher changes.

### 7.1 Habituation in Ground Truth

When `enable_habituation=True`, each completed deterring action updates a per-cell, per-cue `HabituationField`. Truth suppression is scaled by the effectiveness sampled at the action completion time:

```text
suppression_event = eta(cell, mode) * beta_mode * spatial_kernel * temporal_decay
```

Repeated use of the same cue in the same cell lowers `eta`; recovery moves it back toward `1.0`. Setting `enable_habituation=False` or `habituation_kappa=0.0` keeps `eta_at_apply = 1.0` and provides the non-habituating control.

### 8. Heuristic Preventive Gates

The legacy heuristic risk gate maps the excess field to a pseudo-confidence:

```text
risk_conf = 1 - exp(-max(lambda - mu, 0) / deterring_risk_scale)
```

If enabled, a candidate must satisfy:

```text
risk_conf >= model_deterring_risk_threshold
```

The simplified `s1_risk_open_core` stage sets the threshold to `0.0`, which effectively disables this extra cutoff while keeping the rest of the preventive pipeline intact.

Additional optional gates in the main codebase use:

- persistence / repeat blocking
- ETA caps
- direct-detection conflict checks
- `predicted_deltaJ` minimums
- `deltaJ_per_cost` minimums

### 9. Assignment And Dispatch

After extraction and optional pre-assignment selection, the runtime assigns tasks to robots. The main assignment score combines capability, travel time, load, zone affinity, health, priority, and task value:

```text
assignment_score =
    w_cap   * capability
  - w_eta   * eta
  + w_stay  * endurance
  + w_zone  * zone_bonus
  + w_health * health
  + w_prio  * task_priority
  + w_task_value * task_value
  - w_load  * active_load
```

Dispatch then enforces queue caps and per-type limits such as:

- `max_active_tasks_per_robot`
- `max_active_patrolling_per_robot`
- `max_active_model_deterring_per_robot`

These dispatch constraints are what drive the planner rejection counters in the experiment outputs.

### 10. Output Metrics

The core reported metrics are direct functions of the event/task history:

```text
value_weighted_exposure =
    sum_{accepted truth events e} w(x_e, y_e)

mean_response_time_s =
    mean over matched detections of (task_completion_time - event_time)

tasks_per_unit_distance =
    completed_tasks_total / total_robot_distance

exposure_per_completed_task =
    value_weighted_exposure / completed_tasks_total

fleet_task_engagement_fraction_so_far =
    fleet_task_engagement_time / elapsed_sim_time
```

The baseline experiment runners aggregate these per-run metrics into:

- mean / variance tables in `comparison.csv`
- time-bucket summaries in `comparison_over_time.csv`
- derived improvements such as proposed-vs-reactive exposure improvement

### 11. Exploratory Row-Queue Variant

The isolated exploration line in `exploration/` changes two pieces of math.

Whole-row ownership replaces polygonal power cells. Each row center `y_k` is assigned to robot `r` by minimizing:

```text
score_row(k, r) =
    (y_k - anchor_y_r)^2
    - (row_health_gain_m * normalized_weight_r)^2
```

where `normalized_weight_r` is the health-derived zone weight for robot `r`.

The local priority queue then replaces global assignment for strictly local task choice:

```text
priority(task, robot) =
    task_value
  + type_bonus
  + zone_bonus
  + 0.25 * support
  + 0.50 * selection_weight
  - distance_weight * distance(robot, task)
  - age_weight * task_age
```

The frequent-repartition exploration variant keeps the same formulas but recomputes row ownership more often and increases the distance penalty so nearby tasks are favored more strongly.

## Quick Start

From repo root:

```powershell
python -m py_compile DeterrentSystem.py TaskGenerator.py SESTPP.py
```

Run the base 24h sweep (sequential):

```powershell
python -m experiments.run_24h_experiment
```

Run faster parallel sweep:

```powershell
python -m experiments.run_24h_experiment_parallel --profile fast --max-workers 12
```

Run a visual demo of the best proposed configuration (from summary CSV):

```powershell
python -m demos.demo_optimal_proposed
```

Save demo as video:

```powershell
python -m demos.demo_optimal_proposed --duration-s 1800 --fps 10 --save-path demo.mp4
```

Launch live dashboard (if telemetry is being flushed by a running sim):

```powershell
streamlit run demos/streamlit_app.py
```


## Habituation-Aware STL Workflow

Run the package-level STL and habituation tests:

```powershell
$env:PYTHONPATH=(Resolve-Path .\habituation_stl).Path
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe habituation_stl\tests\test_spec_value.py
```

Run the production B0-B4 revised ladder:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_revised_b0_b4_900s_10seed --duration-s 900 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --systems B0_reactive B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue --max-workers 2
```

Run the revised confirmatory B1/B2/B3/B4 batch:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --reservation-fraction 0.25 --mu-true 2e-05 --deterrence-beta-scale 4.0 --deterrence-sigma-scale 4.0 --deterrence-omega-scale 3.0 --habituation-kappa 0.5 --systems B1_greedy_fixedcue B2_res_deltaJ_fixedcue B3_res_stl_nohab_fixedcue B4_res_stl_full_multicue --max-workers 4
```

Summarize ladder outputs:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\summarize_habituation_stl_ladder.py --outdir results\testbench\habituation_stl_revised_confirm_with_b2_1800s_10seed
```

Current thesis-facing STL documentation:

- `docs/STL_THEORY_AND_INTEGRATION_AUDIT.md`
- `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`
- `docs/habituation_stl_completion_plan.md`
- `habituation_stl/README_INTEGRATION.md`

## Pluggable Testbench

Use the config-driven testbench when you want one shared scenario and one shared metric contract, but different systems plugged into the same benchmark.

The harness supports:

- simplification stages
- exploration variants
- direct current-workspace modes
- arbitrary repo/module targets, including the sibling `main` worktree

Bundled example:

```powershell
python -m testbench.run_testbench --config testbench/example_config.json --max-workers 4
```

The testbench writes:

- `per_run_metrics.csv`
- `per_run_timeseries.csv`
- `summary_by_metric.csv`
- `advantage_vs_reference.csv`
- `system_scoreboard.csv`
- `testbench_manifest.json`
- `report.md`

Configuration details are in [`testbench/README.md`](testbench/README.md).

## Thesis Evaluation Order

Use the staged thesis workflow in [`docs/EXPERIMENT_EXECUTION_ORDER.md`](docs/EXPERIMENT_EXECUTION_ORDER.md). Each stage runner now writes a README into its output directory describing:

- the question that stage answers,
- the metrics that matter,
- what counts as failure before you proceed to the next stage.

## Outputs

Typical experiment outputs include:

- baseline comparison CSVs (mean/variance metrics)
- per-run metrics CSVs
- experiment manifest CSVs (parameter traceability)
- thesis summary CSV/Markdown (sequential script)
- profile-specific parallel outputs (`*_parallel_fast.csv`, `*_parallel_final.csv`)

## Results Snapshot

After running experiments and plotting (`python -m plots.plot_experiment_results`), key figures are saved in `results/`.

Most important plots to review:

- `results/boxplot_exposure.png` (primary outcome: value-weighted exposure)
- `results/boxplot_response_time.png` (responsiveness)
- `results/boxplot_task_efficiency.png` (task efficiency)
- `results/tradeoff_exposure_vs_response_S2_nominal.png` (core tradeoff view)
- `results/winner_count_by_baseline.png` (who wins across settings)
- `results/mean_rank_heatmap.png` (ranking stability by scenario)

### Habituation-Aware STL Testing

The current STL proposal result uses the revised fixed-cue versus multi-cue production ladder. The current confirmatory run is:

`results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed`

Run shape:

- duration: 1800 seconds
- seeds: 125-134
- systems: `B1_greedy_fixedcue`, `B2_res_deltaJ_fixedcue`, `B3_res_stl_nohab_fixedcue`, `B4_res_stl_full_multicue`
- controls: habituation on and habituation off
- status: confirmatory

Primary paired exposure results:

| Comparison | Truth control | Mean paired delta in Jexp | 95% CI | Seeds improved |
| --- | --- | ---: | ---: | ---: |
| B4 - B1 | habituation on | -3696.74 | [-5226.86, -2166.61] | 9/10 |
| B4 - B3 | habituation on | -4277.35 | [-5791.31, -2763.40] | 10/10 |
| B3 - B2 | habituation on | -689.90 | [-1537.63, +157.84] | 7/10 |
| B4 - B3 | habituation off | 0.00 | [0.00, 0.00] | 0/10 |

Mechanism check under habituating truth:

| Metric | Mean paired delta B4 - B3 | 95% CI |
| --- | ---: | ---: |
| Truth suppression rate | +0.0867 | [+0.0596, +0.1139] |
| Truth suppression effect sum | +1901.7389 | [+1346.1216, +2457.3562] |
| Eta at apply | +0.1559 | [+0.1012, +0.2106] |
| Variety index | +0.3634 | [+0.2498, +0.4770] |

Interpretation: B4 reduced value-weighted exposure relative to both the greedy fixed-cue baseline and the STL-without-habituation fixed-cue baseline when truth habituated. When habituation was disabled, B4 collapsed exactly to B3, which isolates the advantage to the habituation-aware STL cue-variety clause. B3 also improved over B2 on mean exposure, but that comparison is directional because the confidence interval crosses zero.

STL result artifacts:

- `results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed/THESIS_RESULTS_SUMMARY.md`
- `results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed/CLAIMS_SUMMARY.md`
- `results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed/summary_by_system.csv`
- `results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed/advantage_vs_reference.csv`

### Key Plots

Value-weighted exposure (primary metric):

![Value-weighted exposure boxplot](results/boxplot_exposure.png)

Response time distribution:

![Response time boxplot](results/boxplot_response_time.png)

Task efficiency distribution:

![Task efficiency boxplot](results/boxplot_task_efficiency.png)

Exposure vs response tradeoff (nominal scenario):

![Exposure-response tradeoff](results/tradeoff_exposure_vs_response_S2_nominal.png)

Win count and ranking stability:

![Winner count by baseline](results/winner_count_by_baseline.png)
![Mean rank heatmap](results/mean_rank_heatmap.png)

You can also open the generated summary tables:

- `thesis_summary_24h_sweep.csv` / `thesis_summary_24h_sweep.md` (sequential)
- `thesis_summary_24h_sweep_parallel.csv` / `thesis_summary_24h_sweep_parallel.md` (parallel)

## Experiments Documentation

Detailed instructions for experiment workflows and CLI options are in:

- `docs/EXPERIMENTS.md`
- `docs/EXPERIMENT_EXECUTION_ORDER.md`

## Notes on Visualization vs Batch Runs

- `experiments/run_24h_experiment.py` and `experiments/run_24h_experiment_parallel.py` are configured for **headless batch data collection** (no visualization).
- `demos/demo_optimal_proposed.py` is intended for **visual presentation/demo** of a selected best proposed configuration.
