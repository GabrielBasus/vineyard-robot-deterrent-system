"""
reference_sim.py -- compact, self-contained testbed exercising the full stack.

This is a SMOKE-TEST harness, not the production simulator. It is intentionally
small (zones on a line, scalar per-zone intensity) so the whole pipeline --
habituation field, STL monitor, counterfactual robustness value, reserved-
capacity dispatch, metrics -- runs end-to-end in seconds and the qualitative
habituation effect is visible. The thesis experiments run the real vineyard
simulator; see README_INTEGRATION.md for how the same components plug in there.

Truth process per zone z (effectiveness-scaled suppression, cf. Eq. 8):
  raw_lam_z   += grow * (pressure_z - raw_lam_z) * dt        (regeneration)
  supp_z      *= exp(-dt / omega_u)                          (suppression decay)
  lam_z        = max(0, raw_lam_z - supp_z)                  (effective intensity)
  on a completed mode-m deterrence in z:
      supp_z  += eta_applied * beta[m]                       (eta from HabituationField)
      hab.apply(z, m)                                        (habituation jump)

Policies:
  B1  greedy unconstrained, habituation-blind (always cue mode 0)
  B3  STL-robustness value, spec WITHOUT phi_hab (mode 0)  -> isolates Idea 1
  B4  STL-robustness value, full spec, picks the freshest cue per action -> Idea 1+2
"""
from __future__ import annotations

import numpy as np

from habituation import HabituationField
from mission_spec import SpecParams
from task_value import Dynamics, CellState, counterfactual_value, best_action_for_cell
from dispatch import reserved_capacity_dispatch
from metrics import RunMetrics


class Robot:
    def __init__(self, rid, x):
        self.id = rid
        self.x = float(x)          # 1D position (zone-index units)
        self.busy_until = 0.0
        self.target = None         # (cell, mode, kind, task)
        self.pred_time = 0.0       # accumulated predictive service time (for phi)
        self.total_time = 1e-9


class ReferenceSim:
    def __init__(self, policy="B4", n_zones=8, n_robots=4, seed=123,
                 horizon_s=3600.0, dt=10.0, n_modes=3,
                 kappa=0.5, T_rec=1500.0, beta=2.5, hot_zones=(2, 5),
                 pressure_hot=1.2, pressure_cold=0.15, rho=0.25,
                 T_react=120.0, T_cov=900.0, E_star=4.0, eta_min=0.4,
                 habituation=True):
        self.policy = policy
        self.n_zones = n_zones
        self.n_modes = n_modes
        self.dt = dt
        self.horizon_s = horizon_s
        self.rng = np.random.default_rng(seed)
        self.rho = rho
        self.habituation_on = bool(habituation)
        if not self.habituation_on:
            kappa = 0.0   # H4 control: ground truth does not habituate

        # zone pressures and value weights
        self.pressure = np.full(n_zones, pressure_cold)
        for z in hot_zones:
            if z < n_zones:
                self.pressure[z] = pressure_hot
        self.w = 1.0 + 0.5 * (self.pressure / pressure_hot)   # value weight per zone

        # truth state
        self.raw_lam = self.pressure.copy()
        self.supp = np.zeros(n_zones)
        self.omega_u = 900.0
        self.beta = tuple([beta] * n_modes)
        self.grow = 0.002

        # habituation field
        self.hab = HabituationField(n_zones, n_modes, T_rec=T_rec, kappa=kappa)

        # robots
        self.robots = [Robot(f"r{i}", x=self.rng.uniform(0, n_zones - 1))
                       for i in range(n_robots)]

        # coverage bookkeeping
        self.last_service = np.zeros(n_zones)

        # reactive queue
        self.reactive = []   # list of dicts
        self._next_aid = 0

        # spec params
        active = ("exp", "cov") if policy == "B3" else ("exp", "cov", "hab")
        self.params = SpecParams(E_star=E_star, T_cov=T_cov, T_react=T_react,
                                 eta_min=eta_min, horizon=300.0, monitor_dt=30.0,
                                 smooth=True, theta=12.0, active_clauses=active)
        self.dyn = Dynamics(omega_e=600.0, omega_u=self.omega_u, beta=self.beta)
        self.metrics = RunMetrics(n_zones, eta_min=eta_min)
        self.speed = 0.5     # zones per second of travel-equivalent
        self.service_s = 40.0
        self.detect_gain = 0.15

    # -- helpers -----------------------------------------------------------
    def eff_lam(self):
        return np.maximum(0.0, self.raw_lam - self.supp)

    def _cell_states(self):
        lam = self.eff_lam()
        states = {}
        for z in range(self.n_zones):
            e = self.w[z] * lam[z]
            g = self.t - self.last_service[z]
            states[z] = CellState(e0=e, g0=g)
        return states

    def _phi(self):
        # global predictive time fraction (proxy for the per-robot window phi)
        tp = sum(r.pred_time for r in self.robots)
        tt = sum(r.total_time for r in self.robots)
        return tp / tt if tt > 0 else 0.0

    # -- core step ---------------------------------------------------------
    def step(self):
        t = self.t
        dt = self.dt

        # 1) truth regeneration + suppression decay
        self.raw_lam += self.grow * (self.pressure - self.raw_lam) * dt
        self.supp *= np.exp(-dt / self.omega_u)
        lam = self.eff_lam()

        # 2) exposure accumulation (value-weighted)
        self.metrics.add_exposure(dt * float(np.sum(self.w * lam)))

        # 3) coverage violation accounting
        ages = t - self.last_service
        over = np.maximum(0.0, ages - self.params.T_cov)
        self.metrics.add_coverage_violation(dt * float(np.sum(over > 0)))

        # 4) reactive detections
        for z in range(self.n_zones):
            if self.rng.uniform() < self.detect_gain * lam[z] * dt:
                self.reactive.append({
                    "id": self._next_aid, "value": float(self.w[z] * lam[z]),
                    "t_exp": t + self.params.T_react, "target_cell": z})
                self._next_aid += 1
                self.metrics.reactive_arrival()

        # 5) expire overdue reactive tasks (deadline miss)
        still = []
        for a in self.reactive:
            if a["t_exp"] < t:
                self.metrics.reactive_miss()
            else:
                still.append(a)
        self.reactive = still

        # 6) free robots that finished service
        for r in self.robots:
            if r.target is not None and t >= r.busy_until:
                self._complete(r)

        # 7) assign idle robots
        cells = list(range(self.n_zones))
        states = self._cell_states()
        phi = self._phi()
        for r in self.robots:
            if r.target is not None:
                continue
            sel = self._select(r, states, cells, phi, t)
            if sel is not None:
                self._begin(r, sel, t)

        for r in self.robots:
            r.total_time += dt

        self.t += dt

    def _select(self, r, states, cells, phi, t):
        if self.policy == "B0":
            if self.reactive:
                a = max(self.reactive, key=lambda a: a["value"])
                return {"cell": a["target_cell"], "mode": 0, "kind": "reactive", "task": a}
            return None
        if self.policy == "B1":
            return self._select_greedy(r, t)
        return self._select_robustness(r, states, cells, phi, t)

    def _select_greedy(self, r, t):
        # reactive first (highest value), else highest-exposure zone; cue mode 0.
        if self.reactive:
            a = max(self.reactive, key=lambda a: a["value"])
            return {"cell": a["target_cell"], "mode": 0, "kind": "reactive", "task": a}
        lam = self.eff_lam()
        z = int(np.argmax(self.w * lam))
        return {"cell": z, "mode": 0, "kind": "predictive", "task": None}

    def _select_robustness(self, r, states, cells, phi, t):
        # Build predictive candidates (top exposure zones) scored by U.
        lam = self.eff_lam()
        order = np.argsort(-(self.w * lam))[:max(3, self.n_zones // 2)]
        pred_tasks = []
        for z in order:
            z = int(z)
            if self.policy == "B4":
                mode, U = best_action_for_cell(z, cells, states, self.hab,
                                               self.params, self.dyn,
                                               completion_lead=self.service_s)
            else:  # B3: habituation-blind cue (mode 0), spec excludes phi_hab
                U = counterfactual_value((z, 0, self.service_s), cells, states,
                                         self.hab, self.params, self.dyn)
                mode = 0
            pred_tasks.append({"id": f"p{z}", "cell": z, "mode": mode, "U": U})

        react_tasks = [{"id": a["id"], "value": a["value"], "t_exp": a["t_exp"],
                        "target_cell": a["target_cell"], "_ref": a}
                       for a in self.reactive]

        sel = reserved_capacity_dispatch(
            t, react_tasks, pred_tasks, phi_pred_frac=phi, rho=self.rho,
            tau_exp=self.params.T_react * 0.5)
        if sel is None:
            return None
        if sel["decision"] in ("reactive_override", "reactive_service"):
            return {"cell": sel["target_cell"], "mode": (0 if self.policy != "B4"
                    else self.hab.best_mode(sel["target_cell"])),
                    "kind": "reactive", "task": sel["_ref"]}
        return {"cell": sel["cell"], "mode": sel["mode"], "kind": "predictive", "task": None}

    def _begin(self, r, sel, t):
        z = sel["cell"]
        travel = abs(r.x - z)
        service = self.service_s + travel / self.speed
        r.target = (z, sel["mode"], sel["kind"], sel["task"])
        r.busy_until = t + service
        self.metrics.add_travel(travel)
        if sel["kind"] == "predictive":
            r.pred_time += service

    def _complete(self, r):
        z, mode, kind, task = r.target
        r.x = float(z)
        # apply effectiveness-scaled suppression + habituation jump
        eta_applied = self.hab.effectiveness(z, mode)
        self.supp[z] += eta_applied * self.beta[mode]
        self.hab.apply(z, mode)
        self.last_service[z] = self.t
        self.metrics.record_action(z, mode, eta_applied)
        if eta_applied < self.params.eta_min:
            # suppression lost to habituation, attributed as hab-driven exposure
            self.metrics.add_habituation_attributable_exposure(
                self.beta[mode] * (1.0 - eta_applied) * self.w[z])
        if kind == "reactive" and task is not None and task in self.reactive:
            self.reactive.remove(task)
        r.target = None

    def run(self):
        self.t = 0.0
        n_steps = int(self.horizon_s / self.dt)
        for _ in range(n_steps):
            self.step()
        out = self.metrics.as_dict()
        out["policy"] = self.policy
        return out
