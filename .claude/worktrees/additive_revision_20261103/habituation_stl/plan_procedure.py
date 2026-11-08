"""
plan_procedure.py -- the improvement plan's decision procedure (Plan Sections 4 and 5).

Simulator mode ``planner_procedure="plan"``.  The executed system is B5 plus
admitted predictive deviations: at every replan the simulator runs its normal
B5 pipeline (generation, ``unc`` dispatch, freshest-cue rule); before it does,
this module may commit predictive deviations, each a forced-first deterrence
task (robot, x, y, cue) that its robot executes first and then rejoins B5.
A robot without a deviation therefore does exactly what B5 does, so the
executed fallback is pi_0's first action and Plan Proposition 1 holds for the
executed system.

Decision procedure at a replan time t (Plan Sec. 5, steps 1 to 6):

1. Freeze one planner-only snapshot (``decision_snapshot_from_sim_locals``,
   start_stage="replan": exactly the state the B5 dispatcher sees).
2./3. Candidates: every (robot, preventive seed, cue) pair B5's generation
   scores at t (``generation_details``), for robots that are free (no deviation
   still executing).  There is NO reservation ceiling on admission (user decision
   2026-10-22, AUDIT round: "no ceiling anywhere"); the robots' predictive-time
   shares are logged only.  pi_0 and all
   candidates are evaluated by Monte Carlo continuation rollouts with common
   random numbers (``scenario_rollout.evaluate``), one region (the whole
   field) for every robot so U is comparable across robots.
4. Feasibility: service protection of pending reactive tasks (Plan Sec. 4),
   optional baseline-late condition, optional timed-recovery obligations
   (Plan Eq. 4), optional effectiveness floor.
5. Admission U(a) > eps_gate; fleet-level argmax; execute its first action
   (commit the deviation), add the commitment to the snapshot and repeat with
   the remaining robots' candidates (sequential commitment, multiagent
   rollout) until none is admissible or the computation budget is exhausted.
6. Log predicted benefit, active constraints, runtime, timeouts, and the
   realized exposure; on a sampled fraction of decisions, evaluate pi_0 and
   the top candidate on a full-observability (truth) snapshot to measure the
   estimation error of Plan Proposition 2.

Section 6 additions (user decisions 2026-10-21):

* valuation="one_intervention" (decision 8, variant C_plan): same candidates,
  gate, fleet argmax and sequential commitment as D_plan, but U(a) is the
  one-intervention Eq. 3 counterfactual (scenario_rollout.one_intervention_J): in
  both arms the world evolves from the snapshot (every past suppression term kept)
  with NO future intervention of any robot, except that in arm a the candidate's
  own suppression is applied at its application time.  Follow-up 2026-10-22: C_plan
  has NO service protection (as D_plan) and runs NO continuation rollout; the
  candidate's application time comes from scenario_rollout.candidate_application_schedule
  (its own robot's travel and hold under the engine's motion model from the
  snapshot, a hold in progress finishing first), identical in every scenario.
  Service protection, timed recovery and the floor need continuations and are
  rejected with this valuation.
* eta_floor (decision 26): reject a candidate whose planner effectiveness q_hat at
  its application time is below the floor (reason "floor").
* obligation_relaxation (decision 28): "bounded_violation" keeps an obligation that
  neither pi_0 nor any feasible candidate satisfies in every scenario, and prefers,
  among the otherwise admissible policies and pi_0, the one with the smallest
  exceedance of E_low at the deadline, recording the violation size; "drop" is
  the earlier relaxation (kept for reproduction).
* terminal summary (decision 30): per decision, round and policy, per scenario,
  the unfinished tasks by stream, the residual exposure rate at t + H and the
  busy robots at t + H.  There is NO terminal cost: J_H stops at t + H, and a
  pending task not completed by t + H has completion time +inf in every
  comparison.
* oracle (decision 31): oracle_scenarios (64) scenarios drawn from a seed stream
  independent of the planner's, with its own Monte Carlo standard errors.
* ranking (decision 12), deviation travel (decision 13), F0-protected outcomes
  (decision 29) and the timeout rate (decision 16) are logged and summarised.
* information sets (decision 17, follow-up 2026-10-22 "info set = the candidate's
  robot"): with an ``info_provider`` (the simulator installs
  scenario_rollout.robot_information_snapshot when planner_hab_mode="per_robot")
  every robot r's candidates are generated and evaluated on r's own snapshot
  (r's estimator world, r's effectiveness record), pi_0 is evaluated per robot on
  that snapshot, each candidate's feasibility and gate use its own robot's pi_0,
  the fleet takes the best admissible U across robots, and the committed deviation
  is added to every robot's snapshot (task state is centralized) before the next
  round.  None = one shared snapshot (instant full sharing), unchanged.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from habituation_stl import scenario_rollout as sr

REJECTION_REASONS = (
    "robot_committed",      # robot already executes a deviation (earlier decision or earlier round)
    "infeasible_service",   # some scenario: a task in F0^s finishes after its deadline
    "infeasible_late",      # some scenario: a baseline-late task finishes later than under pi_0
    "infeasible_obligation",  # some scenario: an obligation pi_0 satisfies is not satisfied
    "floor",                # planner q_hat at the candidate's application < eta_floor (decision 26)
    "gate",                 # feasible but U(a) <= eps_gate
    "obligation_exceedance",  # admissible, but a policy with smaller bounded-violation exceedance was preferred
    "not_selected",         # admissible but another robot's candidate had larger U in its round
    "timeout",              # never evaluated, or its round did not finish within the budget
)

TERMINAL_FIELDS = ("unfinished_reactive", "unfinished_predictive", "unfinished_deviation",
                   "reactive_uncompleted", "residual_exposure_rate", "robots_busy")


@dataclass
class PlanConfig:
    n_scenarios: int = 16
    horizon_s: float = 300.0
    reactive_deadline_s: float = 90.0        # d_j = creation + reactive_override_slack_s
    service_protection: bool = True          # plan variant E (False: variant D)
    protect_late_tasks: bool = True          # C_j(pi_a) <= C_j(pi_0) for baseline-late finite tasks
    eps_gate: float = 0.0
    # Monte Carlo significance (user decision 2026-10-18): admit only if the mean paired
    # benefit exceeds eps_gate + gate_se_multiplier * its standard error over scenarios.
    gate_se_multiplier: float = 0.0
    # rho of the reservation (logged with every decision next to the robots' predictive-time
    # shares).  NOT an admission rule: the ceiling was removed (user decision 2026-10-22).
    reservation_fraction: float = 0.0
    E_high: Optional[float] = None           # timed recovery (Plan Eq. 4); all three or none
    E_low: Optional[float] = None
    T_response_s: Optional[float] = None
    compute_budget_s: float = 45.0           # wall-clock budget per replan decision
    pool_workers: Optional[int] = None
    oracle_fraction: float = 0.25
    log_path: Optional[str] = None
    seed: int = 0
    scenario_chunk: int = 0                  # 0 = adaptive (snapshot sent by file, about 4 tasks per worker)
    # Calibration aids (dev seeds only): observe_only never deviates, so the executed
    # system is exactly B5; exposure_log_path records every cell's forecast e_z per step.
    observe_only: bool = False
    # Diagnostics for the scenario-count test (2026-10-19): per-scenario U and service
    # violations for every candidate, and oracle evaluation of all round-0 candidates
    # (also the source of the decision-12 Kendall tau on oracle-sampled decisions).
    log_per_scenario: bool = False
    oracle_all_candidates: bool = False
    exposure_log_path: Optional[str] = None
    # Section 6 decisions (2026-10-21)
    valuation: str = "continuation"           # "continuation" (D/E) | "one_intervention" (C_plan, decision 8)
    eta_floor: Optional[float] = None         # decision 26: reject if q_hat at application < floor
    obligation_relaxation: str = "bounded_violation"   # decision 28; "drop" reproduces the earlier rule
    oracle_scenarios: int = 64                # decision 31: independent oracle scenarios

    @property
    def timed_recovery(self) -> bool:
        return self.E_high is not None and self.E_low is not None and self.T_response_s is not None

    def validate(self):
        if int(self.n_scenarios) < 2:
            raise ValueError("plan_n_scenarios must be >= 2 (standard errors need two scenarios)")
        if not (float(self.horizon_s) >= float(self.reactive_deadline_s)):
            raise ValueError("plan horizon must cover every reactive deadline (H >= reactive_override_slack_s)")
        given = [v is not None for v in (self.E_high, self.E_low, self.T_response_s)]
        if any(given) and not all(given):
            raise ValueError("timed recovery needs plan_E_high, plan_E_low and plan_T_response_s together")
        if self.timed_recovery and not (float(self.E_low) < float(self.E_high)):
            raise ValueError("timed recovery requires E_low < E_high")
        if not (0.0 <= float(self.oracle_fraction) <= 1.0):
            raise ValueError("plan_oracle_fraction must lie in [0, 1]")
        if float(self.compute_budget_s) <= 0.0:
            raise ValueError("plan_compute_budget_s must be > 0")
        if self.valuation not in ("continuation", "one_intervention"):
            raise ValueError("plan_valuation must be 'continuation' or 'one_intervention'")
        if self.obligation_relaxation not in ("bounded_violation", "drop"):
            raise ValueError("plan_obligation_relaxation must be 'bounded_violation' or 'drop'")
        if int(self.oracle_scenarios) < 2:
            raise ValueError("plan_oracle_scenarios must be >= 2")
        if self.eta_floor is not None and not (0.0 <= float(self.eta_floor) <= 1.0):
            raise ValueError("plan_eta_floor must lie in [0, 1]")
        if self.valuation == "one_intervention":
            # Follow-up 2026-10-22: C_plan has NO service protection and NO continuation; the
            # constraints below would need continuation rollouts (C_j(pi), obligation
            # tracking, q_hat after continuation depletions), which C_plan does not run.
            bad = [name for name, on in (("plan_service_protection", bool(self.service_protection)),
                                         ("timed recovery", self.timed_recovery),
                                         ("plan_eta_floor", self.eta_floor is not None)) if on]
            if bad:
                raise ValueError("plan_valuation='one_intervention' (C_plan) runs no continuation and "
                                 "cannot be combined with " + ", ".join(bad))


class RolloutEngine:
    """Default evaluator: scenario_rollout.evaluate on one lazily created RolloutPool."""

    def __init__(self, n_workers: Optional[int] = None, scenario_chunk: int = 0):
        self.n_workers = n_workers
        self.scenario_chunk = int(scenario_chunk)
        self.pool = None
        self.restarts = 0

    def evaluate(self, snapshot, candidates, *, n_scenarios, seed, reactive_deadline_s, deadline=None,
                 one_intervention=False, continuation=True):
        if self.pool is None:
            self.pool = sr.RolloutPool(self.n_workers)
        try:
            return sr.evaluate(snapshot, candidates, n_scenarios=n_scenarios, seed=seed, pool=self.pool,
                               reactive_deadline_s=reactive_deadline_s, deadline=deadline,
                               scenario_chunk=self.scenario_chunk, slim=True, one_intervention=one_intervention,
                               continuation=continuation)
        except sr.EvaluationTimeout:
            # Cancelled futures do not stop rollouts already running in the workers; restart
            # the pool so the next decision gets its whole budget (decision 16).
            self.pool.kill()
            self.pool = None
            self.restarts += 1
            raise

    def close(self):
        if self.pool is not None:
            self.pool.close()
            self.pool = None


def _finite(v) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _q(a, p):
    a = np.asarray(a, float)
    return float(np.percentile(a, p)) if a.size else float("nan")


def _m(a):
    a = np.asarray(a, float)
    return float(np.mean(a)) if a.size else float("nan")


def kendall_tau_b(a, b) -> float:
    """Kendall tau-b between two equal-length sequences (nan if undefined)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    n = a.size
    if n < 2:
        return float("nan")
    conc = disc = ta = tb = 0
    for i in range(n - 1):
        da = np.sign(a[i + 1:] - a[i])
        db = np.sign(b[i + 1:] - b[i])
        prod = da * db
        conc += int(np.sum(prod > 0))
        disc += int(np.sum(prod < 0))
        ta += int(np.sum((da == 0) & (db != 0)))
        tb += int(np.sum((db == 0) & (da != 0)))
    denom = math.sqrt(float(conc + disc + ta) * float(conc + disc + tb))
    return float((conc - disc) / denom) if denom > 0 else float("nan")


def f0_membership(res) -> dict:
    """Per pending task key: deadline and number of scenarios s with the key in F0^s."""
    out = {}
    for r in res.per_scenario[0]:
        for key, info in r["pending_completion"].items():
            k = tuple(key) if isinstance(key, (list, tuple)) else key
            ent = out.setdefault(k, {"deadline_t": float(info["deadline_t"]), "n_in_F0": 0})
            if float(info["completed_t"]) <= float(info["deadline_t"]):
                ent["n_in_F0"] += 1
    return out


def obligation_exceedance(res, obligation_ids, e_low: float):
    """exc[p][oid] = per-scenario exceedance of E_low at the deadline under policy p.

    0 if the obligation is satisfied (e_z <= E_low) within its window in that scenario,
    else max(e_z(deadline) - E_low, 0) with e_z at the last rollout step t <= deadline.
    An obligation whose deadline precedes the first rollout step (no policy can act on
    it) has no tracked value and contributes 0 for every policy.
    """
    exc = []
    for pol_res in res.per_scenario:
        d = {}
        for oid in obligation_ids:
            vals = []
            for r in pol_res:
                o = r.get("obligations", {}).get(oid, {})
                if math.isfinite(float(o.get("satisfied_t", math.inf))):
                    vals.append(0.0)
                else:
                    e = float(o.get("e_deadline", math.nan))
                    vals.append(max(e - float(e_low), 0.0) if math.isfinite(e) else 0.0)
            d[oid] = vals
        exc.append(d)
    return exc


def service_feasibility(res, *, protect_late: bool):
    """Per candidate: (on-time violation, late violation) flags and per-scenario |F0^s|.

    F0^s = {j : C^s_j(pi_0) <= d_j}; a candidate is service-feasible iff for every
    scenario s and j in F0^s, C^s_j(pi_a) <= d_j.  Optional: for baseline-late j
    with finite C^s_j(pi_0), C^s_j(pi_a) <= C^s_j(pi_0).  Uncompleted or dropped
    tasks have completion time +inf.
    """
    base = res.per_scenario[0]
    n_s = len(base)
    f0 = [sum(1 for info in base[s]["pending_completion"].values()
              if float(info["completed_t"]) <= float(info["deadline_t"])) for s in range(n_s)]
    out = []
    for i in range(1, len(res.per_scenario)):
        ontime_viol = False
        late_viol = False
        for s in range(n_s):
            pc0 = base[s]["pending_completion"]
            pca = res.per_scenario[i][s]["pending_completion"]
            for key, info in pc0.items():
                d = float(info["deadline_t"])
                c0 = float(info["completed_t"])
                ca = float(pca[key]["completed_t"]) if key in pca else math.inf
                if c0 <= d:
                    if not (ca <= d):
                        ontime_viol = True
                elif protect_late and math.isfinite(c0):
                    if not (ca <= c0):
                        late_viol = True
        out.append((ontime_viol, late_viol))
    return out, f0


def per_scenario_service_violations(res, *, protect_late: bool):
    """Per candidate, per scenario: [on-time violation, late violation] (same rule as service_feasibility)."""
    base = res.per_scenario[0]
    out = []
    for i in range(1, len(res.per_scenario)):
        rows = []
        for s in range(len(base)):
            pc0 = base[s]["pending_completion"]
            pca = res.per_scenario[i][s]["pending_completion"]
            ov = lv = False
            for key, info in pc0.items():
                d = float(info["deadline_t"]); c0 = float(info["completed_t"])
                ca = float(pca[key]["completed_t"]) if key in pca else math.inf
                if c0 <= d:
                    ov = ov or not (ca <= d)
                elif protect_late and math.isfinite(c0):
                    lv = lv or not (ca <= c0)
            rows.append([bool(ov), bool(lv)])
        out.append(rows)
    return out


def obligation_satisfaction(res, obligation_ids):
    """sat[p][oid] = per-scenario bool list: obligation satisfied within its window under policy p."""
    sat = []
    for pol_res in res.per_scenario:
        d = {}
        for oid in obligation_ids:
            d[oid] = [math.isfinite(float(r.get("obligations", {}).get(oid, {}).get("satisfied_t", math.inf)))
                      for r in pol_res]
        sat.append(d)
    return sat


def obligation_open_state(res, obligation_ids):
    """opn[p][oid] = per-scenario (open, e_z at the last tracked step) under policy p.

    User decision 2026-10-22: an obligation whose deadline lies after t0 + H and that is
    unmet at t0 + H is OPEN in that scenario (neither met nor failed); its e_z at t0 + H
    is the engine's e_deadline (the last tracked step).  Engines that report no "open"
    flag (deadline within H, or older results) give open = False."""
    opn = []
    for pol_res in res.per_scenario:
        d = {}
        for oid in obligation_ids:
            d[oid] = [(bool(r.get("obligations", {}).get(oid, {}).get("open", False)),
                       float(r.get("obligations", {}).get(oid, {}).get("e_deadline", math.nan)))
                      for r in pol_res]
        opn.append(d)
    return opn


def terminal_table(res):
    """Decision 30: per policy, per scenario [TERMINAL_FIELDS] (None if the engine gave no summary)."""
    out = []
    for pol_res in res.per_scenario:
        rows = []
        for r in pol_res:
            ts = r.get("terminal_summary")
            if ts is None:
                return None
            by = ts["unfinished_by_stream"]
            rows.append([int(by.get("reactive", 0)), int(by.get("predictive", 0)), int(by.get("deviation", 0)),
                         int(ts["reactive_uncompleted"]), float(ts["residual_exposure_rate"]),
                         int(ts["robots_busy"])])
        out.append(rows)
    return out


def _pol_values(res, p, key):
    return [float(r.get(key, math.nan)) if r.get(key) is not None else math.nan for r in res.per_scenario[p]]


class PlanProcedure:
    """Runs the decision procedure at every replan of one simulation run."""

    def __init__(self, cfg: PlanConfig, engine: Any = None, info_provider: Optional[Callable] = None):
        """``info_provider`` (decision 17): None = instant full sharing (one shared
        snapshot, unchanged behaviour).  Otherwise a callable
        ``info_provider(L, snapshot, robot_id, oracle=False) -> snapshot`` returning the
        decision snapshot evaluated with robot ``robot_id``'s information set
        (scenario_rollout.robot_information_snapshot); with ``oracle=True`` the snapshot
        is the truth snapshot and only its policy side is restricted."""
        cfg.validate()
        if info_provider is not None and cfg.timed_recovery:
            # User answer Q5 (2026-10-22): unsupported, stays a clear error (the obligation
            # ledger and bounded-violation comparison are fleet-level, pi_0 is per robot);
            # listed in docs/STATED_ASSUMPTIONS.md.
            raise ValueError("per-robot information sets are not supported with timed recovery")
        self.cfg = cfg
        self.engine = engine if engine is not None else RolloutEngine(cfg.pool_workers, cfg.scenario_chunk)
        self._own_engine = engine is None
        self.info_provider = info_provider
        self.records = []
        self._dev_counter = 0
        self._oracle_rng = np.random.default_rng([int(cfg.seed) & 0xFFFFFFFF, 0x0BAC1E])
        self._key_ctx = None            # (deterring_modes, tau) for task keys at finalize
        # timed-recovery ledger
        self.obligations = []           # every obligation ever created (dicts)
        self._active_by_cell = {}       # cell -> outstanding obligation (status "outstanding")
        self._latched = set()           # cells waiting for a reset (e <= E_low) after violation/relaxation
        self._cell_owner_cache = None
        self._log_fh = None
        if cfg.log_path:
            os.makedirs(os.path.dirname(os.path.abspath(cfg.log_path)) or ".", exist_ok=True)
            self._log_fh = open(cfg.log_path, "w", encoding="utf-8")
        self.summary = None

    # ------------------------------------------------------------------ utils
    def _next_dev_id(self) -> int:
        self._dev_counter += 1
        return -(1_000_000 + self._dev_counter)

    def _decision_seed(self, idx: int) -> int:
        ss = np.random.SeedSequence([int(self.cfg.seed) & 0xFFFFFFFF, 0x91A9, int(idx)])
        return int(ss.generate_state(1)[0] & 0x7FFFFFFF)

    def _oracle_seed(self, idx: int) -> int:
        """Decision 31: oracle scenarios come from a seed stream independent of the planner's."""
        ss = np.random.SeedSequence([int(self.cfg.seed) & 0xFFFFFFFF, 0x0AC1E5, int(idx)])
        return int(ss.generate_state(1)[0] & 0x7FFFFFFF)

    def _evaluate(self, snap, cands, *, n_scenarios, seed, deadline):
        # C_plan (follow-up 2026-10-22): one-intervention world only, no continuation
        kw = ({"one_intervention": True, "continuation": False}
              if self.cfg.valuation == "one_intervention" else {})
        return self.engine.evaluate(snap, cands, n_scenarios=int(n_scenarios), seed=seed,
                                    reactive_deadline_s=float(self.cfg.reactive_deadline_s), deadline=deadline, **kw)

    def _U(self, res):
        """(U_mean, U_se, J_mean, J_se) under the configured valuation."""
        if self.cfg.valuation == "one_intervention":
            J1 = np.asarray(res.J_one, float)
            sq = math.sqrt(max(J1.shape[1], 1))
            J_se = J1.std(axis=1, ddof=1) / sq if J1.shape[1] > 1 else np.zeros(J1.shape[0])
            return (np.asarray(res.U_one_mean, float), np.asarray(res.U_one_se, float), J1.mean(axis=1), J_se)
        return (np.asarray(res.U_mean, float), np.asarray(res.U_se, float), np.asarray(res.J_mean, float),
                np.asarray(res.J_se, float))

    def close(self):
        if self._own_engine and self.engine is not None:
            self.engine.close()
        if self._log_fh is not None:
            self._log_fh.close()
            self._log_fh = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------- timed recovery (Eq. 4)
    def _cell_owner(self, L):
        if self._cell_owner_cache is None:
            W, H, NX, NY = float(L["W"]), float(L["H"]), int(L["NX"]), int(L["NY"])
            _, _, XX, YY = sr._node_grid(W, H, NX, NY)
            owner = np.full(XX.shape, -1, np.int64)
            for cid, poly in enumerate(L["cells"]):
                if not poly:
                    continue
                ins = sr.points_in_polygon(XX, YY, poly) & (owner < 0)
                owner[ins] = cid
            self._cell_owner_cache = owner
        return self._cell_owner_cache

    def cell_exposure(self, L):
        """Planner forecast exposure e_z(t) of every cell: sum over the cell's nodes of
        w * lambda_hat with the planner forecast (the same world the rollouts use)."""
        t = float(L["t"])
        W, H, NX, NY = float(L["W"]), float(L["H"]), int(L["NX"]), int(L["NY"])
        fc, store = sr.planner_forecast_from_sim_locals(L, t0=t, horizon_s=float(L["dt"]))
        _, w_bar = sr._weight_grids(L, W, H, NX, NY, 8)
        ns = sr.RolloutSnapshot.__new__(sr.RolloutSnapshot)
        ns.forecast = fc
        ns.nx, ns.ny, ns.W, ns.H = NX, NY, W, H
        ns.region_mask = np.ones((NY, NX), bool)
        ns.w_node = w_bar
        ns.w_bg_node = w_bar
        ns.cfg = sr.B5Config(dt=float(L["dt"]), W=W, H=H)
        ns.t0 = t
        world = sr._World(ns, store if store is not None else list(L["recent_deterrences"]))
        rate = world.node_exposure_rate(t)
        owner = self._cell_owner(L)
        return {cid: float(np.sum(rate[owner == cid])) for cid in range(len(L["cells"]))}

    def monitor(self, L):
        """Per-step trigger / reset / violation bookkeeping (no-op unless timed recovery is on)."""
        if self.cfg.exposure_log_path:
            e_log = self.cell_exposure(L)
            with open(self.cfg.exposure_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": float(L["t"]), "e": {str(k): v for k, v in e_log.items()}}) + "\n")
        if not self.cfg.timed_recovery:
            return
        t = float(L["t"])
        e = self.cell_exposure(L)
        E_high, E_low, T = float(self.cfg.E_high), float(self.cfg.E_low), float(self.cfg.T_response_s)
        for cid, ez in e.items():
            ob = self._active_by_cell.get(cid)
            if ob is not None:
                if ez <= E_low:
                    ob["status"] = "discharged"
                    ob["resolved_t"] = t
                    del self._active_by_cell[cid]
                elif t > float(ob["deadline_t"]):
                    ob["status"] = "violated"
                    ob["resolved_t"] = t
                    # decision 28: violation size = exceedance of E_low at the deadline
                    ob["violation_size"] = max(float(ob.get("e_last", ez)) - E_low, 0.0)
                    del self._active_by_cell[cid]
                    self._latched.add(cid)
                else:
                    ob["e_last"] = float(ez)
                continue
            if cid in self._latched:
                if ez <= E_low:
                    self._latched.discard(cid)
                continue
            if ez > E_high:
                ob = {"id": f"ob{len(self.obligations) + 1}", "cell": int(cid), "trigger_t": t,
                      "deadline_t": t + T, "e_trigger": float(ez), "status": "outstanding", "resolved_t": None,
                      "e_last": float(ez), "violation_size": None, "bounded": False}
                self.obligations.append(ob)
                self._active_by_cell[cid] = ob

    def outstanding_obligations(self, t):
        return [ob for ob in self._active_by_cell.values() if ob["status"] == "outstanding"
                and float(ob["deadline_t"]) >= float(t)]

    # ------------------------------------------------------------ candidates
    @staticmethod
    def _forced_robots(active_tasks):
        return {str(tr.get("assigned_primary")) for tr in active_tasks
                if tr.get("_forced_first") and str(tr.get("state", "")).strip().lower() == "active"}

    def generate_candidates(self, snap, gen=None):
        if gen is None:
            gen = sr.generation_details(snap)
        cands = []
        for rs in snap.robots:
            entry = gen.get(rs.rid)
            if entry is None:
                continue
            for sd in entry["seeds"]:
                for mode in entry["modes"]:
                    cands.append(sr.Candidate(rs.rid, float(sd["x"]), float(sd["y"]), str(mode),
                                              label=str(sd.get("origin", ""))))
        return cands

    @staticmethod
    def _b5_rank(gen, c):
        """Decision 12: rank (1 = best) of candidate c under B5's own generation score among
        its robot's (seed, cue) pairs; None if B5 scored no such pair."""
        sc = (gen.get(c.robot_id) or {}).get("scores") or {}
        own = sc.get((float(c.x), float(c.y), str(c.mode)))
        if own is None:
            return None, None
        return 1 + sum(1 for v in sc.values() if v > own), float(own)

    # -------------------------------------------------------------- decision
    def decide(self, L) -> list:
        """Run the decision at the simulator's Stage 3; return the deviation rows to inject."""
        cfg = self.cfg
        if cfg.observe_only:
            return []
        t0 = float(L["t"])
        idx = len(self.records)
        wall0 = time.perf_counter()
        deadline = wall0 + float(cfg.compute_budget_s)
        if self._key_ctx is None:
            self._key_ctx = (copy.deepcopy(L["deterring_modes"]), float(L["tau_service_s"]))
        # (the simulator calls monitor(L) every step before Stage 3, so the ledger is current)
        snap0 = sr.decision_snapshot_from_sim_locals(L, horizon_s=cfg.horizon_s,
                                                     reactive_deadline_s=cfg.reactive_deadline_s)
        per_robot = self.info_provider is not None
        robot_snaps = None
        if per_robot:
            # Decision 17 (follow-up 2026-10-22): every robot's candidates are generated and
            # evaluated with that robot's own information set; pi_0 is evaluated per robot.
            robot_snaps = {rs.rid: self.info_provider(L, snap0, rs.rid) for rs in snap0.robots}
        deadlines = [float(p.deadline_t) for p in snap0.pending_reactive]
        max_deadline = max(deadlines) if deadlines else -math.inf
        assert max_deadline <= t0 + float(cfg.horizon_s) + 1e-9, \
            f"horizon {cfg.horizon_s} s does not cover a pending deadline at {max_deadline} (t={t0})"
        obligations = self.outstanding_obligations(t0) if cfg.timed_recovery else []
        snap0.obligations = [{"id": ob["id"], "cell": ob["cell"], "deadline_t": ob["deadline_t"],
                              "e_low": float(cfg.E_low)} for ob in obligations]
        if per_robot:
            for s in robot_snaps.values():
                s.obligations = list(snap0.obligations)
        ob_ids = [ob["id"] for ob in obligations]
        if per_robot:
            # B5's generation at t0 for robot r, run on r's own snapshot (its estimator and
            # its effectiveness record): r's candidates and r's B5 ranking (decision 12)
            gen = {}
            for rs in snap0.robots:
                ent = sr.generation_details(robot_snaps[rs.rid]).get(rs.rid)
                if ent is not None:
                    gen[rs.rid] = ent
        else:
            gen = sr.generation_details(snap0)
        cands = self.generate_candidates(snap0, gen)
        forced = self._forced_robots(L["active_tasks"])
        # logged only (no ceiling, user decision 2026-10-22 AUDIT round)
        rho = float(cfg.reservation_fraction)
        share = {rs.rid: float(L["robots"][rs.rid].predictive_share(t0)) for rs in snap0.robots}
        status = {}
        cand_log = []
        for i, c in enumerate(cands):
            st = None
            if c.robot_id in forced:
                st = "robot_committed"
            status[i] = st
            rank, b5s = self._b5_rank(gen, c)
            cand_log.append({"robot": c.robot_id, "x": c.x, "y": c.y, "mode": c.mode, "origin": c.label,
                             "status": st, "b5_score": b5s, "b5_rank": rank, "rounds": []})
        remaining = [i for i in range(len(cands)) if status[i] is None]
        dec_seed = self._decision_seed(idx)
        commitments = []          # (candidate index, row, admitted record)
        rounds = []
        timed_out = False
        snap_k = snap0
        snaps_k = robot_snaps
        J_exec = math.nan
        J_exec_se = math.nan
        J_exec_by_robot = None
        relaxed_ids = []          # "drop": removed from the constraint set
        bounded_ids = []          # "bounded_violation": kept, exceedance minimised
        f0_round0 = None
        bounded = cfg.obligation_relaxation == "bounded_violation"
        while remaining:
            # evaluation groups: one shared snapshot, or one snapshot per robot (its own pi_0)
            if per_robot:
                groups = [(rs.rid, snaps_k[rs.rid], [i for i in remaining if cands[i].robot_id == rs.rid])
                          for rs in snap0.robots]
                groups = [g for g in groups if g[2]]
            else:
                groups = [(None, snap_k, list(remaining))]
            try:
                evals = [self._evaluate(s_g, [cands[i] for i in idx_g], n_scenarios=cfg.n_scenarios,
                                        seed=dec_seed, deadline=deadline) for _, s_g, idx_g in groups]
            except sr.EvaluationTimeout:
                timed_out = True
                break
            remaining = [i for _, _, idx_g in groups for i in idx_g]
            g_of, jl_of = [], []
            for gi, (_, _, idx_g) in enumerate(groups):
                for jl in range(len(idx_g)):
                    g_of.append(gi)
                    jl_of.append(jl)
            n_pol = len(remaining)
            svc, f0, eta_app = [], [], []
            sat_g, J0_g = [], []
            open_g = []
            U_mean, U_se, Ja_mean, Ja_se = [], [], [], []
            f0_now = []
            for gi, res in enumerate(evals):
                svc_g, f0_g = service_feasibility(res, protect_late=bool(cfg.protect_late_tasks))
                svc.extend(svc_g)
                f0.extend(f0_g)
                f0_now.append((groups[gi][0], f0_membership(res)))
                sat_g.append(obligation_satisfaction(res, ob_ids) if ob_ids else None)
                open_g.append(obligation_open_state(res, ob_ids) if ob_ids else None)
                Um, Us, Jm, Js = self._U(res)
                U_mean.extend(Um)
                U_se.extend(Us)
                Ja_mean.extend(Jm[1:])
                Ja_se.extend(Js[1:])
                J0_g.append((float(Jm[0]), float(Js[0])))
                eta_app.extend(_pol_values(res, jl + 1, "candidate_eta_planner") for jl in range(len(groups[gi][2])))
            U_mean = np.asarray(U_mean, float)
            U_se = np.asarray(U_se, float)
            if f0_round0 is None:
                f0_round0 = f0_now

            def _sat(j, oid):
                """(pi_0 of the candidate's group, candidate) per-scenario satisfaction lists."""
                s_g = sat_g[g_of[j]]
                return s_g[0][oid], s_g[jl_of[j] + 1][oid]

            def _ob_dominance_violated(j, oid):
                """Dominance of one kept obligation in some scenario (user decision 2026-10-22):
                pi_0 meets it (within its window, or by t0 + H when the deadline is later)
                and the candidate does not; or neither meets it, it is OPEN under both
                (deadline after t0 + H) and the candidate's e_z at t0 + H exceeds pi_0's."""
                s0s, sas = _sat(j, oid)
                o_g = open_g[g_of[j]]
                o0s, oas = o_g[0][oid], o_g[jl_of[j] + 1][oid]
                for s0, sa, (op0, e0), (opa, ea) in zip(s0s, sas, o0s, oas):
                    if s0 and not sa:
                        return True
                    if (not s0) and (not sa) and op0 and opa and _finite(e0) and _finite(ea) \
                            and float(ea) > float(e0):
                        return True
                return False

            def _reasons(cons_ids):
                out = []
                for j in range(n_pol):
                    r = None
                    if cfg.service_protection and svc[j][0]:
                        r = "infeasible_service"
                    elif cfg.service_protection and svc[j][1]:
                        r = "infeasible_late"
                    elif ob_ids and any(_ob_dominance_violated(j, oid) for oid in cons_ids):
                        r = "infeasible_obligation"
                    elif cfg.eta_floor is not None and any(
                            _finite(v) and float(v) < float(cfg.eta_floor) for v in eta_app[j]):
                        # q_hat at application (Plan Eq. 1-2, processed chronologically in each
                        # scenario); below the floor in any scenario where it is applied
                        r = "floor"
                    elif not (U_mean[j] > float(cfg.eps_gate) + float(cfg.gate_se_multiplier) * float(U_se[j])):
                        r = "gate"
                    out.append(r)
                return out

            reasons = _reasons([oid for oid in ob_ids if oid not in bounded_ids])
            # obligation relaxation: no feasible policy (pi_0 or candidate) satisfies it in every scenario
            # (timed recovery runs with the shared snapshot only: one group)
            if ob_ids and not rounds:
                sat = sat_g[0]
                unsat = []
                for oid in ob_ids:
                    ok0 = all(sat[0][oid])
                    ok_c = any(all(sat[j + 1][oid]) for j in range(n_pol) if reasons[j] in (None, "gate"))
                    if not ok0 and not ok_c:
                        unsat.append(oid)
                if bounded:
                    # decision 28: keep them, no dominance constraint, exceedance minimised below
                    bounded_ids = list(unsat)
                    if bounded_ids:
                        reasons = _reasons([oid for oid in ob_ids if oid not in bounded_ids])
                else:
                    relaxed_ids = list(unsat)
                    # explicit relaxation: dropped from the constraint set from the next round on
                    ob_ids = [oid for oid in ob_ids if oid not in relaxed_ids]
            admissible = [j for j, r in enumerate(reasons) if r is None]
            feasible_js = [j for j, r in enumerate(reasons) if r in (None, "gate")]
            top_pool = feasible_js if feasible_js else list(range(n_pol))
            top_j = max(top_pool, key=lambda j: U_mean[j]) if top_pool else None
            # pi_0 estimate reported for the round: the top candidate's group (per-robot
            # information: the top candidate's robot; shared: the one shared pi_0)
            gref = g_of[top_j] if top_j is not None else 0
            res_ref = evals[gref]
            rnd = {
                "round": len(rounds), "n_candidates": n_pol, "cand_indices": [int(i) for i in remaining],
                "J0_mean": J0_g[gref][0], "J0_se": J0_g[gref][1],
                "J0_cont_mean": float(res_ref.J_mean[0]), "J0_cont_se": float(res_ref.J_se[0]),
                "F0_sizes": [int(v) for v in f0], "eval_wall_s": float(sum(e.wall_time_s for e in evals)),
                "chosen": None,
            }
            if per_robot:
                rnd["J0_robot"] = groups[gref][0]
                rnd["per_robot"] = {}
                for gi, (rid_g, _s, idx_g) in enumerate(groups):
                    ent = {"cand_indices": [int(i) for i in idx_g], "J0_mean": J0_g[gi][0], "J0_se": J0_g[gi][1],
                           "J0_cont_mean": float(evals[gi].J_mean[0]), "J0_cont_se": float(evals[gi].J_se[0]),
                           "eval_wall_s": float(evals[gi].wall_time_s)}
                    tt = terminal_table(evals[gi])
                    if tt is not None:
                        ent["terminal_summary"] = {"fields": list(TERMINAL_FIELDS), "per_policy": tt}
                    rnd["per_robot"][str(rid_g)] = ent
            else:
                tt = terminal_table(evals[0])
                if tt is not None:
                    rnd["terminal_summary"] = {"fields": list(TERMINAL_FIELDS), "per_policy": tt}
            if cfg.log_per_scenario:
                rows_u, rows_v = [], []
                for res in evals:
                    Umat = res.U_one if cfg.valuation == "one_intervention" else res.U
                    rows_u.extend(np.asarray(Umat, float).tolist())
                    rows_v.extend(per_scenario_service_violations(res, protect_late=bool(cfg.protect_late_tasks)))
                rnd["U_per_scenario"] = rows_u
                rnd["viol_per_scenario"] = rows_v
            for j, i in enumerate(remaining):
                ev = [v for v in eta_app[j] if _finite(v)]
                cand_log[i]["rounds"].append({"round": len(rounds), "U_mean": float(U_mean[j]),
                                              "U_se": float(U_se[j]), "J_mean": float(Ja_mean[j]),
                                              "q_hat_app_min": (min(ev) if ev else None),
                                              "q_hat_app_max": (max(ev) if ev else None),
                                              "reason": reasons[j]})
            rnd["top"] = int(remaining[top_j]) if top_j is not None else None
            jb = None
            if admissible:
                if bounded_ids:
                    exc = obligation_exceedance(evals[0], bounded_ids, float(cfg.E_low))
                    # aggregation: mean over scenarios, summed over the kept obligations
                    X = [float(sum(_m(exc[p][oid]) for oid in bounded_ids)) for p in range(n_pol + 1)]
                    # user decision 2026-10-22: for an obligation OPEN at t0 + H (deadline later)
                    # the size is the exceedance of E_low at t0 + H, logged as a horizon proxy
                    o0 = open_g[0][0] if open_g and open_g[0] is not None else {}
                    rnd["obligation_exceedance"] = {"ids": list(bounded_ids), "X_pi0": X[0],
                                                    "X": [X[j + 1] for j in range(n_pol)],
                                                    "horizon_proxy_ids": [oid for oid in bounded_ids
                                                                          if any(op for op, _ in o0.get(oid, []))]}
                    jc = min(admissible, key=lambda j: (X[j + 1], -U_mean[j], j))
                    # pi_0 (U = 0) is preferred unless the candidate's exceedance is not larger;
                    # an admissible candidate has U > eps_gate >= 0, so it wins exact ties
                    if X[jc + 1] <= X[0]:
                        jb = jc
                    else:
                        for j in admissible:
                            reasons[j] = "obligation_exceedance"
                            cand_log[remaining[j]]["rounds"][-1]["reason"] = "obligation_exceedance"
                else:
                    # fleet-level argmax (per-robot information: across the robots' own U)
                    jb = max(admissible, key=lambda j: (U_mean[j], -j))
                    # ties go to the lowest index (accepted 2026-10-22); count exact ties
                    rnd["exact_u_tie"] = bool(sum(1 for j in admissible if U_mean[j] == U_mean[jb]) > 1)
            if jb is None:
                for j, i in enumerate(remaining):
                    status[i] = reasons[j]
                if per_robot:
                    # no fleet estimate of the executed policy: each robot's own pi_0 estimate
                    J_exec, J_exec_se = math.nan, math.nan
                    J_exec_by_robot = {str(groups[gi][0]): J0_g[gi][0] for gi in range(len(groups))}
                else:
                    J_exec, J_exec_se = J0_g[0]
                rounds.append(rnd)
                break
            ib = remaining[jb]
            c = cands[ib]
            res_b, jlb = evals[g_of[jb]], jl_of[jb]
            row = sr.forced_task_row(c, t0=t0, task_id=self._next_dev_id(), deterring_modes=L["deterring_modes"],
                                     tau_service_s=float(L["tau_service_s"]))
            arr = [v - t0 for v in _pol_values(res_b, jlb + 1, "candidate_arrival_t") if _finite(v)]
            comp = [v for v in _pol_values(res_b, jlb + 1, "candidate_completed_t") if _finite(v)]
            qa = [v for v in eta_app[jb] if _finite(v)]
            choice = (gen.get(c.robot_id) or {}).get("choice")
            same = bool(choice is not None and str(choice.get("type")) == "deterring"
                        and abs(float(choice["x"]) - c.x) < 1e-9 and abs(float(choice["y"]) - c.y) < 1e-9
                        and str(choice.get("mode")) == str(c.mode))
            adm = {"candidate": int(ib), "robot": c.robot_id, "x": c.x, "y": c.y, "mode": c.mode,
                   "origin": c.label, "task_id": int(row["id"]), "round": len(rounds),
                   "U_mean": float(U_mean[jb]), "U_se": float(U_se[jb]),
                   # decision 12
                   "b5_choice": choice, "differs_from_b5": (not same),
                   "b5_rank": cand_log[ib]["b5_rank"], "b5_score": cand_log[ib]["b5_score"],
                   "n_robot_candidates": len((gen.get(c.robot_id) or {}).get("scores") or {}),
                   # decision 13 (predicted, per scenario where the candidate arrives within H)
                   "pred_travel_s_mean": _m(arr), "pred_travel_s_min": (min(arr) if arr else None),
                   "pred_travel_s_max": (max(arr) if arr else None), "pred_arrived_scenarios": len(arr),
                   "pred_completion_t_mean": _m(comp),
                   # decision 26
                   "q_hat_app_mean": _m(qa), "q_hat_app_min": (min(qa) if qa else None)}
            commitments.append((ib, row, adm))
            status[ib] = "admitted"
            rnd["chosen"] = int(ib)
            rnd["chosen_U_mean"] = float(U_mean[jb])
            rnd["chosen_U_se"] = float(U_se[jb])
            if per_robot:
                J_exec, J_exec_se = math.nan, math.nan
                J_exec_by_robot = {str(c.robot_id): float(Ja_mean[jb])}
            else:
                J_exec, J_exec_se = float(Ja_mean[jb]), float(Ja_se[jb])
            rounds.append(rnd)
            for j, i in enumerate(remaining):
                if i != ib and cands[i].robot_id == c.robot_id and reasons[j] is None:
                    status[i] = "not_selected"
                elif i != ib and cands[i].robot_id == c.robot_id:
                    status[i] = reasons[j]
            snap_k = dataclasses.replace(snap_k, active_tasks=list(snap_k.active_tasks) + [copy.deepcopy(row)])
            if per_robot:
                # task state is centralized: the commitment enters every robot's information
                snaps_k = {rid: dataclasses.replace(s, active_tasks=list(s.active_tasks) + [copy.deepcopy(row)])
                           for rid, s in snaps_k.items()}
            remaining = [i for i in remaining if cands[i].robot_id != c.robot_id]
        for i in remaining:
            if status[i] is None:
                status[i] = "timeout" if timed_out else status[i]
        for i in range(len(cands)):
            if status[i] is None:
                status[i] = "timeout"
            cand_log[i]["status"] = status[i]
        runtime = time.perf_counter() - wall0
        for oid in relaxed_ids:
            for ob in self.obligations:
                if ob["id"] == oid and ob["status"] == "outstanding":
                    ob["status"] = "relaxed"
                    ob["resolved_t"] = t0
                    self._active_by_cell.pop(ob["cell"], None)
                    self._latched.add(ob["cell"])
        for oid in bounded_ids:
            for ob in self.obligations:
                if ob["id"] == oid:
                    ob["bounded"] = True
        f0_list = []
        if f0_round0 is not None:
            for rid_g, memb in f0_round0:
                for k, v in memb.items():
                    ent = {"key": k, "deadline_t": v["deadline_t"], "n_in_F0": int(v["n_in_F0"]),
                           "n_scenarios": int(cfg.n_scenarios)}
                    if per_robot:
                        ent["robot"] = str(rid_g)     # protected under that robot's pi_0
                    f0_list.append(ent)
        rec = {
            "decision": idx, "t": t0, "seed": dec_seed, "n_candidates": len(cands),
            "valuation": cfg.valuation,
            "n_evaluated": sum(1 for cl in cand_log if cl["rounds"]),
            "robot_share": share, "rho": rho, "forced_robots": sorted(forced),
            "rounds": rounds, "candidates": cand_log, "timed_out": bool(timed_out), "runtime_s": float(runtime),
            "admitted": [adm for _, _, adm in commitments],
            "J_hat_executed": J_exec, "J_hat_executed_se": J_exec_se,
            # C_plan (one-intervention valuation): J_hat_executed is the ONE-INTERVENTION J
            # (no future interventions of any robot), not an estimate of the executed
            # policy's exposure; it is excluded from plan_realized_minus_pred_*.
            "J_hat_executed_kind": ("one_intervention_J" if cfg.valuation == "one_intervention"
                                    else "continuation_J"),
            # final status counts of this decision's candidates (decision-level rejection reasons)
            "rejected_counts": {k: int(sum(1 for cl in cand_log if cl["status"] == k)) for k in REJECTION_REASONS},
            "exact_u_tie": bool(any(rnd.get("exact_u_tie") for rnd in rounds)),
            "pending": len(snap0.pending_reactive), "max_deadline_margin_s": float(t0 + cfg.horizon_s - max_deadline)
            if deadlines else None,
            "obligations_outstanding": ob_ids, "obligations_relaxed": relaxed_ids,
            "obligations_bounded": bounded_ids,
            "f0_protected": f0_list, "service_protection": bool(cfg.service_protection),
            "oracle": None,
        }
        if per_robot:
            rec["information_sets"] = "per_robot"
            # User answer Q4 (2026-10-22): Prop. 2 per robot, i.e. EVERY robot's own J-hat of the
            # executed policy (pi_0 plus all commitments of this decision) on its own snapshot.
            # Robots whose decision evaluations already contain exactly that policy reuse it
            # (source "decision"); the others get one pi_0 evaluation of their final snapshot
            # with the decision's seed and scenario count (source "diagnostic", outside the
            # decision runtime, like the oracle).  Only for decisions that completed a round
            # (as J_hat_executed in shared mode).
            by_robot, src = {}, {}
            if rounds:
                for rid_e, v in (J_exec_by_robot or {}).items():
                    by_robot[rid_e], src[rid_e] = float(v), "decision"
                w_diag = time.perf_counter()
                for rs in snap0.robots:
                    if str(rs.rid) in by_robot:
                        continue
                    res_e = self._evaluate(snaps_k[rs.rid], [], n_scenarios=cfg.n_scenarios, seed=dec_seed,
                                           deadline=None)
                    by_robot[str(rs.rid)] = float(self._U(res_e)[2][0])
                    src[str(rs.rid)] = "diagnostic"
                rec["J_hat_executed_by_robot_diag_wall_s"] = float(time.perf_counter() - w_diag)
            rec["J_hat_executed_by_robot"] = by_robot
            rec["J_hat_executed_by_robot_source"] = src
        # ---------------- oracle evaluation (diagnostic; not part of the decision budget)
        if rounds and float(self._oracle_rng.random()) < float(cfg.oracle_fraction):
            rec["oracle"] = self._oracle(L, cands, cand_log, rounds, commitments, idx)
        self.records.append(rec)
        return [copy.deepcopy(row) for _, row, _ in commitments]

    def _oracle(self, L, cands, cand_log, rounds, commitments, idx):
        """Truth-snapshot evaluation with plan_oracle_scenarios independent scenarios (decision 31).

        Per-robot information: each candidate's policies are the ones its robot evaluated,
        so the oracle snapshot's policy side is that robot's (world = truth)."""
        cfg = self.cfg
        w0 = time.perf_counter()
        oseed = self._oracle_seed(idx)
        n_o = int(cfg.oracle_scenarios)
        base = sr.decision_snapshot_from_sim_locals(L, horizon_s=cfg.horizon_s,
                                                    reactive_deadline_s=cfg.reactive_deadline_s, oracle=True)
        bases = {}

        def base_for(rid):
            if self.info_provider is None:
                return base
            if rid not in bases:
                bases[rid] = self.info_provider(L, base, rid, oracle=True)
            return bases[rid]

        out = []
        all_rounds = []
        for k, rnd in enumerate(rounds):
            top = rnd.get("top")
            chosen = rnd.get("chosen")
            if cfg.oracle_all_candidates:
                # user decision 2026-10-22: the oracle evaluates EVERY candidate of every round
                # (on that round's snapshot: the earlier rounds' commitments included)
                idxs = list(rnd.get("cand_indices") or [])
            else:
                idxs = [top] if top is not None else []
            if not idxs:
                continue
            if self.info_provider is None:
                groups = [(None, idxs)]
            else:
                order = []
                for i in idxs:
                    if cands[i].robot_id not in order:
                        order.append(cands[i].robot_id)
                groups = [(rid, [i for i in idxs if cands[i].robot_id == rid]) for rid in order]
            by_cand = {}
            for rid, idx_g in groups:
                b = base_for(rid if rid is not None else cands[idx_g[0]].robot_id)
                snap = dataclasses.replace(b, active_tasks=list(b.active_tasks)
                                           + [copy.deepcopy(row) for _, row, _ in commitments[:k]])
                res = self._evaluate(snap, [cands[i] for i in idx_g], n_scenarios=n_o, seed=oseed, deadline=None)
                U_o, U_o_se, J_o, J_o_se = self._U(res)
                for jl, i in enumerate(idx_g):
                    by_cand[i] = (float(U_o[jl]), float(U_o_se[jl]), float(J_o[0]), float(J_o_se[0]),
                                  float(J_o[jl + 1]), float(J_o_se[jl + 1]))
            if cfg.oracle_all_candidates:
                idx_o = [i for _, idx_g in groups for i in idx_g]
                U_plan = [next(e["U_mean"] for e in cand_log[i]["rounds"] if e["round"] == k) for i in idx_o]
                UA = [by_cand[i][0] for i in idx_o]
                all_rounds.append({"round": k, "cand_indices": idx_o, "U_oracle": UA,
                                   "U_oracle_se": [by_cand[i][1] for i in idx_o],
                                   "U_planner": U_plan,
                                   "robots": [str(cands[i].robot_id) for i in idx_o],
                                   "chosen": (int(chosen) if chosen is not None else None),
                                   # decision 12: rank agreement planner U vs oracle U in this round
                                   "kendall_tau": kendall_tau_b(U_plan, UA)})
            if top is None:
                continue
            U_t, U_t_se, J0_t, J0_t_se, Ja_t, Ja_t_se = by_cand[top]
            # planner estimates of the same two policies in the same round
            J0_hat = float(rnd["J0_mean"])
            ca = next((e for e in cand_log[top]["rounds"] if e["round"] == k), None)
            out.append({
                "round": k, "candidate": int(top), "admitted": bool(chosen == top),
                "J0_hat": J0_hat, "J0_hat_se": float(rnd["J0_se"]),
                "Ja_hat": float(ca["J_mean"]) if ca else math.nan,
                "U_hat": float(ca["U_mean"]) if ca else math.nan, "U_hat_se": float(ca["U_se"]) if ca else math.nan,
                "J0_oracle": J0_t, "J0_oracle_se": J0_t_se,
                "Ja_oracle": Ja_t, "Ja_oracle_se": Ja_t_se,
                "U_oracle": U_t, "U_oracle_se": U_t_se,
            })
        all_round0 = next((a for a in all_rounds if a["round"] == 0), None)
        return {"rounds": out, "all_round0": all_round0, "all_rounds": all_rounds, "n_scenarios": n_o,
                "seed": oseed, "wall_s": time.perf_counter() - w0}

    # ------------------------------------------------------------- summary
    def _task_key_fns(self):
        modes, tau = self._key_ctx

        def key_fn(task):
            return (sr.task_action_kind(task, modes, tau), sr.task_action_name(task, modes, tau),
                    round(float(task.get("x", float("nan"))), 2), round(float(task.get("y", float("nan"))), 2),
                    round(float(task.get("time", float("nan"))), 0))

        def is_direct(task):
            return sr.task_action_kind(task, modes, tau) == "deterring" and \
                sr.task_action_name(task, modes, tau) == "direct_detection"
        return key_fn, is_direct

    def _attach_realized(self, completed_tasks, active_tasks, t_end):
        """Decisions 13 and 29: realized travel of admitted deviations and realized deadline
        outcome of every F0-protected pending task (from the simulator's task rows)."""
        rows = {}
        for tr in list(completed_tasks or []) + list(active_tasks or []):
            rows.setdefault(tr.get("id"), tr)
        done = {}
        if self._key_ctx is not None:
            key_fn, is_direct = self._task_key_fns()
            for tr in completed_tasks or []:
                if not is_direct(tr) or tr.get("t_done") is None:
                    continue
                for k in (tr.get("_member_task_keys") or [key_fn(tr)]):
                    k = tuple(k)
                    done[k] = min(done.get(k, math.inf), float(tr["t_done"]))
        for rec in self.records:
            t0 = float(rec["t"])
            for adm in rec["admitted"]:
                tr = rows.get(adm["task_id"])
                sh = None if tr is None else tr.get("started_hold")
                td = None if tr is None else tr.get("t_done")
                adm["real_arrival_t"] = None if sh is None else float(sh)
                adm["real_travel_s"] = None if sh is None else float(sh) - t0
                adm["real_completion_t"] = None if td is None else float(td)
            for f in rec.get("f0_protected", []):
                ct = done.get(tuple(f["key"]), math.inf)
                f["realized_completed_t"] = ct
                if ct <= f["deadline_t"]:
                    f["met"] = True
                elif f["deadline_t"] <= float(t_end):
                    f["met"] = False
                else:
                    f["met"] = None        # deadline after the run end: censored

    def finalize(self, *, exposure_event_log, t_end: float, t_report_offset: float = 0.0,
                 completed_tasks=None, active_tasks=None) -> dict:
        """Close the pool, attach realized exposure, travel and service outcomes, write the
        JSONL log and return summary metrics."""
        H = float(self.cfg.horizon_s)
        ev = np.asarray(exposure_event_log, float).reshape(-1, 2) if len(exposure_event_log) else np.zeros((0, 2))
        for rec in self.records:
            t0 = float(rec["t"])
            sel = (ev[:, 0] > t0) & (ev[:, 0] <= t0 + H)
            rec["realized_exposure"] = float(ev[sel, 1].sum())
            rec["realized_window_complete"] = bool(t0 + H <= float(t_end) + 1e-9)
        self._attach_realized(completed_tasks, active_tasks, t_end)
        if self._log_fh is not None:
            for rec in self.records:
                self._log_fh.write(json.dumps(rec, default=_json_default, allow_nan=True) + "\n")
            self._log_fh.write(json.dumps({"obligations": self.obligations}, default=_json_default) + "\n")
            self._log_fh.flush()
        self.summary = self.summary_metrics()
        self.close()
        return self.summary

    def summary_metrics(self) -> dict:
        recs = self.records
        rt = [r["runtime_s"] for r in recs]
        counts = {k: 0 for k in REJECTION_REASONS}
        n_cand = 0
        u_adm, u_adm_se = [], []
        f0 = []
        floor_disagree = 0
        for r in recs:
            n_cand += r["n_candidates"]
            for c in r["candidates"]:
                if c["status"] in counts:
                    counts[c["status"]] += 1
                for e in c["rounds"]:
                    lo, hi = e.get("q_hat_app_min"), e.get("q_hat_app_max")
                    if lo is not None and hi is not None and hi - lo > 1e-12:
                        floor_disagree += 1
            for rnd in r["rounds"]:
                f0.extend(rnd["F0_sizes"])
                if rnd.get("chosen") is not None:
                    u_adm.append(rnd["chosen_U_mean"])
                    u_adm_se.append(rnd["chosen_U_se"])
        orc = [o for r in recs if r.get("oracle") for o in r["oracle"]["rounds"]]
        e0 = [o["J0_hat"] - o["J0_oracle"] for o in orc]
        ea = [o["Ja_hat"] - o["Ja_oracle"] for o in orc if _finite(o["Ja_hat"])]
        eu = [o["U_hat"] - o["U_oracle"] for o in orc if _finite(o["U_hat"])]
        rel0 = [abs(o["J0_hat"] - o["J0_oracle"]) / o["J0_oracle"] for o in orc if o["J0_oracle"] > 0]
        adm_orc = [o for o in orc if o["admitted"]]
        taus = [r["oracle"]["all_round0"]["kendall_tau"] for r in recs
                if r.get("oracle") and r["oracle"].get("all_round0")
                and _finite(r["oracle"]["all_round0"]["kendall_tau"])]
        # C_plan: J_hat_executed is the one-intervention J, not an estimate of the executed
        # policy's exposure, so it is kept out of plan_realized_minus_pred_* (reported apart)
        real = [(r["J_hat_executed"], r["realized_exposure"]) for r in recs
                if r.get("realized_window_complete") and _finite(r["J_hat_executed"])
                and r.get("J_hat_executed_kind", "continuation_J") == "continuation_J"]
        real_one = [(r["J_hat_executed"], r["realized_exposure"]) for r in recs
                    if r.get("realized_window_complete") and _finite(r["J_hat_executed"])
                    and r.get("J_hat_executed_kind") == "one_intervention_J"]
        adms = [a for r in recs for a in r["admitted"]]
        ranks = [a["b5_rank"] for a in adms if a.get("b5_rank") is not None]
        trav = [(a["pred_travel_s_mean"], a["real_travel_s"]) for a in adms
                if _finite(a.get("pred_travel_s_mean")) and a.get("real_travel_s") is not None]
        # decision 29: distinct pending tasks protected (in F0^s for >= 1 / all scenarios) in some decision
        prot_any, prot_all = {}, {}
        for r in recs:
            for f in r.get("f0_protected", []):
                k = tuple(f["key"])
                if f["n_in_F0"] >= 1:
                    prot_any[k] = f.get("met")
                if f["n_in_F0"] >= f["n_scenarios"]:
                    prot_all[k] = f.get("met")
        term0 = [row for r in recs for rnd in r["rounds"][:1] if rnd.get("terminal_summary")
                 for row in rnd["terminal_summary"]["per_policy"][0]]
        # per-robot information sets: every robot's own pi_0 terminal rows
        term0 += [row for r in recs for rnd in r["rounds"][:1] for ent in (rnd.get("per_robot") or {}).values()
                  if ent.get("terminal_summary") for row in ent["terminal_summary"]["per_policy"][0]]
        n_dec = len(recs)
        n_to = int(sum(1 for r in recs if r["timed_out"]))
        # decision-level rejection reasons (user decision 2026-10-22): per decision, the
        # number of candidates ending with each reason; groups feasibility (service + late)
        # and obligation (infeasible_obligation + obligation_exceedance)
        per_dec = {k: [int((r.get("rejected_counts") or {}).get(k, 0)) for r in recs] for k in REJECTION_REASONS}
        out = {
            "plan_decision_count": n_dec,
            "plan_candidates_total": int(n_cand),
            "plan_candidates_per_decision_mean": (n_cand / n_dec) if recs else float("nan"),
            "plan_evaluated_candidates_total": int(sum(r["n_evaluated"] for r in recs)),
            "plan_rounds_total": int(sum(len(r["rounds"]) for r in recs)),
            "plan_deviations_admitted": int(sum(len(r["admitted"]) for r in recs)),
            "plan_decisions_with_deviation": int(sum(1 for r in recs if r["admitted"])),
            **{f"plan_rejected_{k}": int(v) for k, v in counts.items()},
            **{f"plan_rejected_{k}_per_decision_mean": _m(v) for k, v in per_dec.items()},
            "plan_rejected_feasibility": int(counts["infeasible_service"] + counts["infeasible_late"]),
            "plan_rejected_obligation": int(counts["infeasible_obligation"] + counts["obligation_exceedance"]),
            "plan_rejected_feasibility_per_decision_mean": _m(
                [a + b for a, b in zip(per_dec["infeasible_service"], per_dec["infeasible_late"])]),
            "plan_rejected_obligation_per_decision_mean": _m(
                [a + b for a, b in zip(per_dec["infeasible_obligation"], per_dec["obligation_exceedance"])]),
            "plan_exact_u_tie_count": int(sum(1 for r in recs if r.get("exact_u_tie"))),
            "plan_runtime_mean_s": _m(rt), "plan_runtime_p95_s": _q(rt, 95), "plan_runtime_p99_s": _q(rt, 99),
            "plan_runtime_max_s": float(np.max(rt)) if rt else float("nan"),
            "plan_timeouts": n_to,
            "plan_timeout_rate": (n_to / n_dec) if n_dec else float("nan"),
            "plan_U_admitted_mean": _m(u_adm), "plan_U_admitted_se_mean": _m(u_adm_se),
            "plan_F0_size_mean": _m(f0),
            "plan_floor_q_hat_scenario_disagreements": int(floor_disagree),
            "plan_oracle_rounds": len(orc),
            "plan_oracle_scenarios": int(self.cfg.oracle_scenarios),
            "plan_oracle_decisions": int(sum(1 for r in recs if r.get("oracle"))),
            "plan_oracle_wall_s_total": float(sum(r["oracle"]["wall_s"] for r in recs if r.get("oracle"))),
            "plan_oracle_J0_se_mean_raw_units": _m([o["J0_oracle_se"] for o in orc]),
            "plan_oracle_U_se_mean_raw_units": _m([o["U_oracle_se"] for o in orc]),
            # SECONDARY Prop. 2 (user decision 2026-10-22): raw errors in exposure units
            # (planner world J vs oracle truth-world J; unit-mixed across loads and cells)
            "plan_pred_err_J0_bias_raw_units": _m(e0), "plan_pred_err_J0_mean_abs_raw_units": _m(np.abs(e0)),
            "plan_pred_err_J0_p95_abs_raw_units": _q(np.abs(e0), 95),
            "plan_pred_err_J0_max_abs_raw_units": float(np.max(np.abs(e0))) if e0 else float("nan"),
            "plan_pred_err_J0_rel_mean": _m(rel0),
            "plan_pred_err_Ja_bias_raw_units": _m(ea), "plan_pred_err_Ja_mean_abs_raw_units": _m(np.abs(ea)),
            "plan_pred_err_Ja_p95_abs_raw_units": _q(np.abs(ea), 95),
            "plan_pred_err_U_bias_raw_units": _m(eu), "plan_pred_err_U_mean_abs_raw_units": _m(np.abs(eu)),
            "plan_pred_err_U_p95_abs_raw_units": _q(np.abs(eu), 95),
            "plan_pred_err_U_max_abs_raw_units": float(np.max(np.abs(eu))) if eu else float("nan"),
            "plan_oracle_U_sign_agree_fraction": _m([float(np.sign(o["U_hat"]) == np.sign(o["U_oracle"]))
                                                      for o in orc if _finite(o["U_hat"])]),
            "plan_oracle_admitted_rounds": len(adm_orc),
            "plan_oracle_admitted_U_oracle_mean_raw_units": _m([o["U_oracle"] for o in adm_orc]),
            "plan_oracle_admitted_U_oracle_positive_fraction": _m([float(o["U_oracle"] > 0) for o in adm_orc]),
            "plan_oracle_kendall_tau_n": len(taus),
            "plan_oracle_kendall_tau_mean": _m(taus),
            "plan_oracle_kendall_tau_median": _q(taus, 50),
            **self._prop2_scale_free(recs, None, "plan_prop2_"),
            "plan_dev_differs_from_b5_fraction": _m([float(a["differs_from_b5"]) for a in adms]),
            "plan_dev_b5_rank_mean": _m(ranks),
            "plan_dev_b5_rank1_fraction": _m([float(k == 1) for k in ranks]),
            "plan_dev_travel_n": len(trav),
            "plan_dev_travel_pred_mean_s": _m([p for p, _ in trav]),
            "plan_dev_travel_real_mean_s": _m([q for _, q in trav]),
            "plan_dev_travel_err_mean_s": _m([q - p for p, q in trav]),
            "plan_dev_travel_err_mean_abs_s": _m([abs(q - p) for p, q in trav]),
            "plan_F0_protected_tasks": len(prot_any),
            "plan_F0_protected_missed": int(sum(1 for v in prot_any.values() if v is False)),
            "plan_F0_protected_censored": int(sum(1 for v in prot_any.values() if v is None)),
            "plan_F0_protected_all_scen_tasks": len(prot_all),
            "plan_F0_protected_all_scen_missed": int(sum(1 for v in prot_all.values() if v is False)),
            "plan_terminal_pi0_reactive_uncompleted_mean": _m([row[3] for row in term0]),
            "plan_terminal_pi0_residual_rate_mean": _m([row[4] for row in term0]),
            "plan_terminal_pi0_robots_busy_mean": _m([row[5] for row in term0]),
            "plan_realized_windows": len(real),
            "plan_realized_minus_pred_mean_raw_units": _m([b - a for a, b in real]),
            "plan_realized_minus_pred_mean_abs_raw_units": _m([abs(b - a) for a, b in real]),
            # C_plan only: realized exposure minus the one-intervention J (not a Prop. 2 error)
            "plan_realized_minus_one_intervention_J_windows": len(real_one),
            "plan_realized_minus_one_intervention_J_mean_raw_units": _m([b - a for a, b in real_one]),
            "plan_obligations_created": len(self.obligations),
            "plan_obligations_discharged": sum(1 for o in self.obligations if o["status"] == "discharged"),
            "plan_obligations_violated": sum(1 for o in self.obligations if o["status"] == "violated"),
            "plan_obligations_relaxed": sum(1 for o in self.obligations if o["status"] == "relaxed"),
            "plan_obligations_bounded": sum(1 for o in self.obligations if o.get("bounded")),
            "plan_obligation_violation_size_mean": _m([o["violation_size"] for o in self.obligations
                                                        if o.get("violation_size") is not None]),
            "plan_obligations_outstanding_at_end": sum(1 for o in self.obligations if o["status"] == "outstanding"),
        }
        if self.info_provider is not None:
            out.update(self._per_robot_prediction_metrics(recs))
        return out

    @staticmethod
    def _prop2_scale_free(recs, robot, prefix) -> dict:
        """PRIMARY Prop. 2 metrics (user decision 2026-10-22), scale free, on the oracle-sampled
        decisions; ``robot`` None = every candidate, else only that robot's candidates.

          sign_agree_fraction: sign(U_planner) == sign(U_oracle), over every oracle-evaluated
            candidate (all candidates of every round with plan_oracle_all_candidates, else
            the top candidate of each round);
          kendall_tau_mean / _median / _n: Kendall tau-b between planner U and oracle U per
            round (rounds with >= 2 candidates of the robot; all-candidates oracle only);
          admitted_oracle_U_positive_fraction: admitted deviations with oracle U > 0.
        """
        sign, taus, adm = [], [], []
        for r in recs:
            o = r.get("oracle")
            if not o:
                continue
            all_rounds = o.get("all_rounds")
            if all_rounds:
                for a in all_rounds:
                    sel = [j for j, rid in enumerate(a.get("robots") or []) if robot is None or rid == str(robot)]
                    up = [a["U_planner"][j] for j in sel]
                    uo = [a["U_oracle"][j] for j in sel]
                    sign.extend(float(np.sign(x) == np.sign(y)) for x, y in zip(up, uo) if _finite(x))
                    if len(sel) >= 2:
                        tau = kendall_tau_b(up, uo)
                        if _finite(tau):
                            taus.append(tau)
                    ch = a.get("chosen")
                    if ch is not None and ch in a["cand_indices"]:
                        j = a["cand_indices"].index(ch)
                        if j in sel:
                            adm.append(float(a["U_oracle"][j] > 0))
            else:
                cand_robot = {i: str(c["robot"]) for i, c in enumerate(r["candidates"])}
                for e in o["rounds"]:
                    if robot is not None and cand_robot.get(e["candidate"]) != str(robot):
                        continue
                    if _finite(e["U_hat"]):
                        sign.append(float(np.sign(e["U_hat"]) == np.sign(e["U_oracle"])))
                    if e["admitted"]:
                        adm.append(float(e["U_oracle"] > 0))
        return {
            f"{prefix}sign_agree_fraction": _m(sign),
            f"{prefix}sign_agree_n": len(sign),
            f"{prefix}kendall_tau_mean": _m(taus),
            f"{prefix}kendall_tau_median": _q(taus, 50),
            f"{prefix}kendall_tau_n": len(taus),
            f"{prefix}admitted_oracle_U_positive_fraction": _m(adm),
            f"{prefix}admitted_oracle_n": len(adm),
        }

    @classmethod
    def _per_robot_prediction_metrics(cls, recs) -> dict:
        """User answer Q4 (2026-10-22), per-robot information sets only: Prop. 2 per robot.

        PRIMARY (scale free, user decision 2026-10-22): per robot r, the plan_prop2_* metrics
        over r's own candidates (r's U estimates vs the oracle on r's policy side), and their
        mean and spread (SD, ddof=0) across robots.
        SECONDARY (raw units): for every robot, realized J minus that robot's own J-hat of the
        executed policy over the decisions with a complete realized window; then the mean and
        the spread (SD over robots, ddof=0, and max - min) of the per-robot mean errors."""
        err = {}
        rids = set()
        for r in recs:
            for c in r.get("candidates", []):
                rids.add(str(c["robot"]))
            if not r.get("realized_window_complete"):
                continue
            for rid, v in (r.get("J_hat_executed_by_robot") or {}).items():
                rids.add(str(rid))
                if _finite(v):
                    err.setdefault(str(rid), []).append(float(r["realized_exposure"]) - float(v))
        out = {}
        means, abss = [], []
        for rid in sorted(err):
            e = np.asarray(err[rid], float)
            out[f"plan_pr_realized_minus_pred_n_{rid}"] = int(e.size)
            out[f"plan_pr_realized_minus_pred_mean_raw_units_{rid}"] = _m(e)
            out[f"plan_pr_realized_minus_pred_mean_abs_raw_units_{rid}"] = _m(np.abs(e))
            means.append(_m(e))
            abss.append(_m(np.abs(e)))
        m = np.asarray(means, float)
        out.update({
            "plan_pr_robots": len(means),
            "plan_pr_realized_minus_pred_mean_raw_units": _m(m),
            "plan_pr_realized_minus_pred_spread_sd_raw_units": float(np.std(m)) if m.size else float("nan"),
            "plan_pr_realized_minus_pred_spread_range_raw_units": float(m.max() - m.min()) if m.size else float("nan"),
            "plan_pr_realized_minus_pred_mean_abs_raw_units": _m(abss),
        })
        per = {rid: cls._prop2_scale_free(recs, rid, "") for rid in sorted(rids)}
        for rid, d in per.items():
            for k, v in d.items():
                out[f"plan_pr_prop2_{k}_{rid}"] = v
        for k in ("sign_agree_fraction", "kendall_tau_mean", "admitted_oracle_U_positive_fraction"):
            vals = np.asarray([d[k] for d in per.values() if _finite(d[k])], float)
            out[f"plan_pr_prop2_{k}_robot_mean"] = _m(vals)
            out[f"plan_pr_prop2_{k}_robot_spread_sd"] = float(np.std(vals)) if vals.size else float("nan")
        return out


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)
