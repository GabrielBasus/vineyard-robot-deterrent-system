# habituation_stl — integration guide

Reusable, tested Python implementing the **new thesis direction**: predictive task
value as the *counterfactual robustness margin* of a *habituation-aware STL mission
specification*. Everything here is `numpy`-only and side-effect free, so it drops into
the existing decentralized vineyard testbed without new dependencies.

The existing SESTPP model, zone partitioner, fleet model, and reserved-capacity
dispatcher are **kept**. This package replaces exactly one thing — the predictive value
function — and adds the habituation state the objective needs.

---

## 1. What each module is, and which equation it implements

| Module | Implements | Proposal ref |
|---|---|---|
| `stl.py` | STL robustness monitor; classical `min/max` and smooth `softmin/softmax`; future (`Eventually`,`Always`,`Until`) and past-time (`Once`,`Historically`,`Since`) operators | Eqs. 12–20 |
| `habituation.py` | `HabituationField`: per-(cell,mode) effectiveness with exponential recovery + multiplicative habituation jump + optional cross-mode coupling | Eqs. 6–7 |
| `mission_spec.py` | The four clauses `phi_exp, phi_react, phi_cov, phi_hab` and `Phi = ^ clauses`, normalized predicates, `SpecParams` | Eqs. 21–26 |
| `task_value.py` | `counterfactual_value(...)` = `U(a,r)` and the analytic forward predictor | Eqs. 25–26, Alg. 2 |
| `signals.py` | `RobotMonitor`: decentralized online robustness over a trailing buffer | Alg. 1 |
| `dispatch.py` | `reserved_capacity_dispatch(...)` with `U` as predictive utility | Alg. 3 |
| `metrics.py` | `J_exp`, deadline-miss rate, coverage violation, `eta_bar`, variety index, habituation-attributable exposure | Sec. 8.4 |
| `reference_sim.py`, `experiment.py` | self-contained smoke-test sim + B0–B4 ladder with habituation on/off control | Sec. 8 |

Run `python run_all_tests.py` (15 tests) and `python run_demo.py` first to see it work.

---

## 2. The five edits to the existing codebase

Cells in this package are integer ids. Map them to your planner grid cells or to zone
ids — whatever granularity you already monitor. Below, `Z` is that id.

### Edit A — ground truth gets habituation (`DeterrentSystem.py`, `DeterrentSystem_simple_tasks.py`)

This is the change that makes habituation *real in the world* (Eq. 8). You already have a
mode-dependent suppression path (`use_mode_dependent_truth_suppression`, `beta_true`).
Scale that suppression by current effectiveness, and update the field.

```python
from habituation_stl.habituation import HabituationField

# once, at construction:
self.hab = HabituationField(n_cells=self.n_cells, n_modes=self.n_modes,
                            T_rec=cfg.T_rec, kappa=cfg.kappa, gamma=cfg.gamma)

# every truth step, before computing intensity:
self.hab.recover(dt)                                   # Eq. 6

# in the suppression term of lambda_true, multiply beta_true by effectiveness:
eta = self.hab.effectiveness(cell_of(z_j), mode_of(intervention_j))   # Eq. 8
suppression += eta * beta_true[mode] * K_u(x - z_j) * exp(-(t - tau_j)/omega_u)

# when an intervention COMPLETES (the same place you currently log it):
self.hab.apply(cell_of(z_j), mode_of(intervention_j))  # Eq. 7
```

Control for H4: pass `kappa=0.0` to disable habituation; the world stops habituating and
B4 should collapse to B1 (this is the falsifiable check in `experiment.py`).

### Edit B — predictive value becomes counterfactual robustness (`planner_task_estimation.py`)

Replace the body of `estimate_counterfactual_reduction(...)` (the hand-tuned ΔJ score)
with a call to `counterfactual_value`. `U` is larger when the action reduces exposure,
restores coverage, **and** uses an un-habituated cue.

```python
from habituation_stl.task_value import counterfactual_value, CellState, Dynamics
from habituation_stl.mission_spec import SpecParams

def estimate_predictive_value(candidate, robot, field, hab, cfg):
    cells = robot.local_cells                      # Z_r u boundary (Sec. 6.1)
    states = {c: CellState(e0=exposure_rate(field, c),   # e_z = ∫_Z w*lambda_hat
                           g0=coverage_age(c))     # g_z = t - last_service[c]
              for c in cells}
    params = cfg.spec_params                        # a SpecParams (Edit D)
    dyn = Dynamics(omega_e=cfg.omega_e, omega_u=cfg.omega_u, beta=cfg.beta_modes)
    return counterfactual_value(
        (candidate.cell, candidate.mode, candidate.completion_lead),
        cells, states, hab, params, dyn)
```

`exposure_rate(field, c)` is `e_z` from Eq. (sig-e): integrate `w(x) * lambda_hat(x,t)`
over cell `c` using your SESTPP field — i.e. your `hat_lambda` weighted by the value
surface, summed over the cell. To also choose the cue mode, use
`best_action_for_cell(c, cells, states, hab, params, dyn)` → `(mode, U)`; the habituation
clause makes it pick the freshest cue.

### Edit C — selection / dispatch use U (`planner_task_selection.py`, `planner_dispatch.py`)

Your reserved-capacity dispatcher already has the right shape (hard-latency override +
reservation `rho`). Only the predictive utility changes: rank predictive candidates by
`U` instead of ΔJ. If you prefer, call `reserved_capacity_dispatch(...)` from
`dispatch.py` directly — it mirrors Algorithm 1 of the April reframe with `value_fn=U`.

### Edit D — config gets the new parameters (`calibration_config.py`)

```python
from habituation_stl.mission_spec import SpecParams
spec_params = SpecParams(
    E_star=...,        # exposure budget per cell (value-weighted rate)
    T_cov=...,         # coverage recency bound (s)
    T_react=...,       # reactive deadline (s) — reuse your existing value
    W=...,             # anti-habituation refractory window (s)
    eta_min=0.4,       # effectiveness floor
    horizon=300.0,     # robustness horizon H
    monitor_dt=30.0,   # monitor period Delta_m
    theta=12.0,        # smooth-robustness temperature
    smooth=True)
# habituation truth params: T_rec, kappa (scalar or per-mode), gamma
# forward-predictor params: omega_e, omega_u, beta_modes (per-mode suppression)
```

### Edit E — telemetry logs robustness + habituation metrics (`Robot.py`, `telemetry_sim.py`)

Give each robot a monitor and log it; accumulate the new metrics.

```python
from habituation_stl.signals import RobotMonitor
from habituation_stl.metrics import RunMetrics

# Robot.__init__:
self.monitor = RobotMonitor(self.local_cells, cfg.spec_params)

# each monitor tick (Alg. 1):
self.monitor.record(t, exposures, coverage_ages, active_modes, hab)
rob = self.monitor.robustness()          # {'exp','cov','hab','global'}
telemetry.log(robot=self.id, **rob)

# RunMetrics accumulates J_exp, deadline misses, eta_bar, variety_index, etc.
```

---

## 3. Quantity ↔ existing-code crosswalk

| Spec quantity | Source in existing code |
|---|---|
| `e_z` value-weighted exposure (Eq. sig-e) | `sum_{x in cell} w(x) * hat_lambda(x,t)` from your SESTPP field × value surface `w` |
| `g_z` coverage age (Eq. sig-g) | `t - last_service_time[cell]` (you already track service events) |
| `eta_z` effectiveness (Eqs. 6–7) | `HabituationField.effectiveness(cell, active_mode)` |
| reactive arrival / deadline | your existing reactive task `arrival` / `t_exp` |
| cue modes `M` | your deterrent action types (`DeterrentSystem` / `planner_profiles`) |
| forward decay (Eq. 25) | mirror your SESTPP passive-decay constants in `Dynamics(omega_e, omega_u)` |

---

## 4. Honest seams (need your exact signatures)

These are deliberately left as thin adapters because they depend on names only in the
full codebase:

1. **`cell_of(x)` / `mode_of(intervention)`** — map a continuous location to a cell id
   and read the action's cue mode. One-liners against your grid/zone + action structs.
2. **`exposure_rate(field, cell)`** — the integral of `w * hat_lambda` over a cell using
   *your* SESTPP accessor. The package assumes you can produce this scalar per cell.
3. **Local cell set `robot.local_cells`** — `Z_r ∪ ∂Z_r` from your `ZonePartitioner`
   (owned cells plus boundary band already exchanged over the EventBus).
4. **`completion_lead`** — your `tau_service(a,r)` estimate (Eq. 2); already computed by
   the dispatcher for ETA.

Everything upstream of these adapters is implemented and tested here.

---

## 5. Suggested order of work

1. Drop in `habituation.py`, wire **Edit A**, run with `kappa=0` first (no behavior
   change), then `kappa>0` and confirm exposure rises under the *current* greedy policy
   — this proves habituation is live in the truth process.
2. Wire **Edit D** (config) and **Edit B** (value function); rank predictive tasks by `U`.
3. Add **Edit E** telemetry; reproduce the B0–B4 ladder on the real sim.
4. Run the H1–H4 checks; `experiment.py` shows the expected pattern on the reference
   harness (B4 ≪ B1 with habituation on; B4 ≈ B1 with habituation off).

The reference harness is a smoke test — its absolute numbers are illustrative. The point
it demonstrates is mechanical and carries over: when the cue rotates, effectiveness stays
high, so the same number of actions suppresses more, and predictive variety finally pays.
