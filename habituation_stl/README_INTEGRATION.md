# habituation\_stl — integration guide

Reusable, tested Python implementing the **new thesis direction**: predictive task
value as the *counterfactual robustness margin* of a *habituation-aware STL mission
specification*. Everything here is `numpy`-only and side-effect free, so it drops into
the existing decentralized vineyard testbed without new dependencies.

The existing SESTPP model, zone partitioner, fleet model, and reserved-capacity
dispatcher are **kept**. This package replaces exactly one thing — the predictive value
function — and adds the habituation state the objective needs.

\---

## 1\. What each module is, and which equation it implements

|Module|Implements|Proposal ref|
|-|-|-|
|`stl.py`|STL robustness monitor; classical `min/max` and smooth `softmin/softmax`; future (`Eventually`,`Always`,`Until`) and past-time (`Once`,`Historically`,`Since`) operators|Eqs. 12–20|
|`habituation.py`|`HabituationField`: per-(cell,mode) effectiveness with exponential recovery + multiplicative habituation jump + optional cross-mode coupling|Eqs. 6–7|
|`mission\\\_spec.py`|The four clauses `phi\\\_exp, phi\\\_react, phi\\\_cov, phi\\\_hab` and `Phi = ^ clauses`, normalized predicates, `SpecParams`|Eqs. 21–26|
|`task\\\_value.py`|`counterfactual\\\_value(...)` = `U(a,r)` and the analytic forward predictor|Eqs. 25–26, Alg. 2|
|`signals.py`|`RobotMonitor`: decentralized online robustness over a trailing buffer|Alg. 1|
|`dispatch.py`|`reserved\\\_capacity\\\_dispatch(...)` with `U` as predictive utility|Alg. 3|
|`metrics.py`|`J\\\_exp`, deadline-miss rate, coverage violation, `eta\\\_bar`, variety index, habituation-attributable exposure|Sec. 8.4|
|`reference\\\_sim.py`, `experiment.py`|self-contained smoke-test sim + B0–B4 ladder with habituation on/off control|Sec. 8|

Run `python run\\\_all\\\_tests.py` (15 tests) and `python run\\\_demo.py` first to see it work.

\---

## 2\. The five edits to the existing codebase

Cells in this package are integer ids. Map them to your planner grid cells or to zone
ids — whatever granularity you already monitor. Below, `Z` is that id.

### Edit A — ground truth gets habituation (`DeterrentSystem.py`, `DeterrentSystem\\\_simple\\\_tasks.py`)

This is the change that makes habituation *real in the world* (Eq. 8). You already have a
mode-dependent suppression path (`use\\\_mode\\\_dependent\\\_truth\\\_suppression`, `beta\\\_true`).
Scale that suppression by current effectiveness, and update the field.

```python
from habituation\\\_stl.habituation import HabituationField

# once, at construction:
self.hab = HabituationField(n\\\_cells=self.n\\\_cells, n\\\_modes=self.n\\\_modes,
                            T\\\_rec=cfg.T\\\_rec, kappa=cfg.kappa, gamma=cfg.gamma)

# every truth step, before computing intensity:
self.hab.recover(dt)                                   # Eq. 6

# in the suppression term of lambda\\\_true, multiply beta\\\_true by effectiveness:
eta = self.hab.effectiveness(cell\\\_of(z\\\_j), mode\\\_of(intervention\\\_j))   # Eq. 8
suppression += eta \\\* beta\\\_true\\\[mode] \\\* K\\\_u(x - z\\\_j) \\\* exp(-(t - tau\\\_j)/omega\\\_u)

# when an intervention COMPLETES (the same place you currently log it):
self.hab.apply(cell\\\_of(z\\\_j), mode\\\_of(intervention\\\_j))  # Eq. 7
```

Control for H4: pass `kappa=0.0` to disable habituation; the world stops habituating and
B4 should collapse to B1 (this is the falsifiable check in `experiment.py`).

### Edit B — predictive value becomes counterfactual robustness (`planner\\\_task\\\_estimation.py`)

Replace the body of `estimate\\\_counterfactual\\\_reduction(...)` (the hand-tuned ΔJ score)
with a call to `counterfactual\\\_value`. `U` is larger when the action reduces exposure,
restores coverage, **and** uses an un-habituated cue.

```python
from habituation\\\_stl.task\\\_value import counterfactual\\\_value, CellState, Dynamics
from habituation\\\_stl.mission\\\_spec import SpecParams

def estimate\\\_predictive\\\_value(candidate, robot, field, hab, cfg):
    cells = robot.local\\\_cells                      # Z\\\_r u boundary (Sec. 6.1)
    states = {c: CellState(e0=exposure\\\_rate(field, c),   # e\\\_z = ∫\\\_Z w\\\*lambda\\\_hat
                           g0=coverage\\\_age(c))     # g\\\_z = t - last\\\_service\\\[c]
              for c in cells}
    params = cfg.spec\\\_params                        # a SpecParams (Edit D)
    dyn = Dynamics(omega\\\_e=cfg.omega\\\_e, omega\\\_u=cfg.omega\\\_u, beta=cfg.beta\\\_modes)
    return counterfactual\\\_value(
        (candidate.cell, candidate.mode, candidate.completion\\\_lead),
        cells, states, hab, params, dyn)
```

`exposure\\\_rate(field, c)` is `e\\\_z` from Eq. (sig-e): integrate `w(x) \\\* lambda\\\_hat(x,t)`
over cell `c` using your SESTPP field — i.e. your `hat\\\_lambda` weighted by the value
surface, summed over the cell. To also choose the cue mode, use
`best\\\_action\\\_for\\\_cell(c, cells, states, hab, params, dyn)` → `(mode, U)`; the habituation
clause makes it pick the freshest cue.

### Edit C — selection / dispatch use U (`planner\\\_task\\\_selection.py`, `planner\\\_dispatch.py`)

Your reserved-capacity dispatcher already has the right shape (hard-latency override +
reservation `rho`). Only the predictive utility changes: rank predictive candidates by
`U` instead of ΔJ. If you prefer, call `reserved\\\_capacity\\\_dispatch(...)` from
`dispatch.py` directly — it mirrors Algorithm 1 of the April reframe with `value\\\_fn=U`.

### Edit D — config gets the new parameters (`calibration\\\_config.py`)

```python
from habituation\\\_stl.mission\\\_spec import SpecParams
spec\\\_params = SpecParams(
    E\\\_star=...,        # exposure budget per cell (value-weighted rate)
    T\\\_cov=...,         # coverage recency bound (s)
    T\\\_react=...,       # reactive deadline (s) — reuse your existing value
    W=...,             # anti-habituation refractory window (s)
    eta\\\_min=0.4,       # effectiveness floor
    horizon=300.0,     # robustness horizon H
    monitor\\\_dt=30.0,   # monitor period Delta\\\_m
    theta=12.0,        # smooth-robustness temperature
    smooth=True)
# habituation truth params: T\\\_rec, kappa (scalar or per-mode), gamma
# forward-predictor params: omega\\\_e, omega\\\_u, beta\\\_modes (per-mode suppression)
```

### Edit E — telemetry logs robustness + habituation metrics (`Robot.py`, `telemetry\\\_sim.py`)

Give each robot a monitor and log it; accumulate the new metrics.

```python
from habituation\\\_stl.signals import RobotMonitor
from habituation\\\_stl.metrics import RunMetrics

# Robot.\\\_\\\_init\\\_\\\_:
self.monitor = RobotMonitor(self.local\\\_cells, cfg.spec\\\_params)

# each monitor tick (Alg. 1):
self.monitor.record(t, exposures, coverage\\\_ages, active\\\_modes, hab)
rob = self.monitor.robustness()          # {'exp','cov','hab','global'}
telemetry.log(robot=self.id, \\\*\\\*rob)

# RunMetrics accumulates J\\\_exp, deadline misses, eta\\\_bar, variety\\\_index, etc.
```

\---

## 3\. Quantity ↔ existing-code crosswalk

|Spec quantity|Source in existing code|
|-|-|
|`e\\\_z` value-weighted exposure (Eq. sig-e)|`sum\\\_{x in cell} w(x) \\\* hat\\\_lambda(x,t)` from your SESTPP field × value surface `w`|
|`g\\\_z` coverage age (Eq. sig-g)|`t - last\\\_service\\\_time\\\[cell]` (you already track service events)|
|`eta\\\_z` effectiveness (Eqs. 6–7)|`HabituationField.effectiveness(cell, active\\\_mode)`|
|reactive arrival / deadline|your existing reactive task `arrival` / `t\\\_exp`|
|cue modes `M`|your deterrent action types (`DeterrentSystem` / `planner\\\_profiles`)|
|forward decay (Eq. 25)|mirror your SESTPP passive-decay constants in `Dynamics(omega\\\_e, omega\\\_u)`|

\---

## 4\. Honest seams (need your exact signatures)

These are deliberately left as thin adapters because they depend on names only in the
full codebase:

1. **`cell\\\_of(x)` / `mode\\\_of(intervention)`** — map a continuous location to a cell id
and read the action's cue mode. One-liners against your grid/zone + action structs.
2. **`exposure\\\_rate(field, cell)`** — the integral of `w \\\* hat\\\_lambda` over a cell using
*your* SESTPP accessor. The package assumes you can produce this scalar per cell.
3. **Local cell set `robot.local\\\_cells`** — `Z\\\_r ∪ ∂Z\\\_r` from your `ZonePartitioner`
(owned cells plus boundary band already exchanged over the EventBus).
4. **`completion\\\_lead`** — your `tau\\\_service(a,r)` estimate (Eq. 2); already computed by
the dispatcher for ETA.

Everything upstream of these adapters is implemented and tested here.

\---

## 5\. Suggested order of work

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
