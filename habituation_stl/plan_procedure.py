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
   scores at t (``generation_seeds``), for robots that are free (no deviation
   still executing) and below the predictive-time ceiling.  pi_0 and all
   candidates are evaluated by Monte Carlo continuation rollouts with common
   random numbers (``scenario_rollout.evaluate``), one region (the whole
   field) for every robot so U is comparable across robots.
4. Feasibility: service protection of pending reactive tasks (Plan Sec. 4),
   optional baseline-late condition, optional timed-recovery obligations
   (Plan Eq. 4).
5. Admission U(a) > eps_gate; fleet-level argmax; execute its first action
   (commit the deviation), add the commitment to the snapshot and repeat with
   the remaining robots' candidates (sequential commitment, multiagent
   rollout) until none is admissible or the computation budget is exhausted.
6. Log predicted benefit, active constraints, runtime, timeouts, and the
   realized exposure; on a sampled fraction of decisions, evaluate pi_0 and
   the top candidate on a full-observability (truth) snapshot to measure the
   estimation error of Plan Proposition 2.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from habituation_stl import scenario_rollout as sr

REJECTION_REASONS = (
    "ceiling",              # robot's predictive-time share >= rho (reservation as a ceiling)
    "robot_committed",      # robot already executes a deviation (earlier decision or earlier round)
    "infeasible_service",   # some scenario: a task in F0^s finishes after its deadline
    "infeasible_late",      # some scenario: a baseline-late task finishes later than under pi_0
    "infeasible_obligation",  # some scenario: an obligation pi_0 satisfies is not satisfied
    "gate",                 # feasible but U(a) <= eps_gate
    "not_selected",         # admissible but another robot's candidate had larger U in its round
    "timeout",              # never evaluated, or its round did not finish within the budget
)


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
    reservation_fraction: float = 0.0        # rho: ceiling on a robot's predictive-time share
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
    # violations for every candidate, and oracle evaluation of all round-0 candidates.
    log_per_scenario: bool = False
    oracle_all_candidates: bool = False
    exposure_log_path: Optional[str] = None

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


class RolloutEngine:
    """Default evaluator: scenario_rollout.evaluate on one lazily created RolloutPool."""

    def __init__(self, n_workers: Optional[int] = None, scenario_chunk: int = 0):
        self.n_workers = n_workers
        self.scenario_chunk = int(scenario_chunk)
        self.pool = None

    def evaluate(self, snapshot, candidates, *, n_scenarios, seed, reactive_deadline_s, deadline=None):
        if self.pool is None:
            self.pool = sr.RolloutPool(self.n_workers)
        return sr.evaluate(snapshot, candidates, n_scenarios=n_scenarios, seed=seed, pool=self.pool,
                           reactive_deadline_s=reactive_deadline_s, deadline=deadline,
                           scenario_chunk=self.scenario_chunk, slim=True)

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


class PlanProcedure:
    """Runs the decision procedure at every replan of one simulation run."""

    def __init__(self, cfg: PlanConfig, engine: Any = None):
        cfg.validate()
        self.cfg = cfg
        self.engine = engine if engine is not None else RolloutEngine(cfg.pool_workers, cfg.scenario_chunk)
        self._own_engine = engine is None
        self.records = []
        self._dev_counter = 0
        self._oracle_rng = np.random.default_rng([int(cfg.seed) & 0xFFFFFFFF, 0x0BAC1E])
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
                    del self._active_by_cell[cid]
                    self._latched.add(cid)
                continue
            if cid in self._latched:
                if ez <= E_low:
                    self._latched.discard(cid)
                continue
            if ez > E_high:
                ob = {"id": f"ob{len(self.obligations) + 1}", "cell": int(cid), "trigger_t": t,
                      "deadline_t": t + T, "e_trigger": float(ez), "status": "outstanding", "resolved_t": None}
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

    def generate_candidates(self, snap):
        seeds = sr.generation_seeds(snap)
        cands = []
        for rs in snap.robots:
            entry = seeds.get(rs.rid)
            if entry is None:
                continue
            sds, modes = entry
            for sd in sds:
                for mode in modes:
                    cands.append(sr.Candidate(rs.rid, float(sd["x"]), float(sd["y"]), str(mode),
                                              label=str(sd.get("origin", ""))))
        return cands

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
        # (the simulator calls monitor(L) every step before Stage 3, so the ledger is current)
        snap0 = sr.decision_snapshot_from_sim_locals(L, horizon_s=cfg.horizon_s,
                                                     reactive_deadline_s=cfg.reactive_deadline_s)
        deadlines = [float(p.deadline_t) for p in snap0.pending_reactive]
        max_deadline = max(deadlines) if deadlines else -math.inf
        assert max_deadline <= t0 + float(cfg.horizon_s) + 1e-9, \
            f"horizon {cfg.horizon_s} s does not cover a pending deadline at {max_deadline} (t={t0})"
        obligations = self.outstanding_obligations(t0) if cfg.timed_recovery else []
        snap0.obligations = [{"id": ob["id"], "cell": ob["cell"], "deadline_t": ob["deadline_t"],
                              "e_low": float(cfg.E_low)} for ob in obligations]
        ob_ids = [ob["id"] for ob in obligations]
        cands = self.generate_candidates(snap0)
        forced = self._forced_robots(L["active_tasks"])
        rho = float(cfg.reservation_fraction)
        share = {rs.rid: float(L["robots"][rs.rid].predictive_share(t0)) for rs in snap0.robots}
        status = {}
        cand_log = []
        for i, c in enumerate(cands):
            st = None
            if c.robot_id in forced:
                st = "robot_committed"
            elif not (share[c.robot_id] < rho):
                st = "ceiling"
            status[i] = st
            cand_log.append({"robot": c.robot_id, "x": c.x, "y": c.y, "mode": c.mode, "origin": c.label,
                             "status": st, "rounds": []})
        remaining = [i for i in range(len(cands)) if status[i] is None]
        dec_seed = self._decision_seed(idx)
        commitments = []          # (candidate index, row)
        rounds = []
        timed_out = False
        snap_k = snap0
        J_exec = math.nan
        J_exec_se = math.nan
        relaxed_ids = []
        while remaining:
            try:
                res = self.engine.evaluate(snap_k, [cands[i] for i in remaining], n_scenarios=int(cfg.n_scenarios),
                                           seed=dec_seed, reactive_deadline_s=float(cfg.reactive_deadline_s),
                                           deadline=deadline)
            except sr.EvaluationTimeout:
                timed_out = True
                break
            svc, f0 = service_feasibility(res, protect_late=bool(cfg.protect_late_tasks))
            sat = obligation_satisfaction(res, ob_ids) if ob_ids else None
            U_mean = np.asarray(res.U_mean, float)
            U_se = np.asarray(res.U_se, float)
            reasons = []
            for j, i in enumerate(remaining):
                r = None
                if cfg.service_protection and svc[j][0]:
                    r = "infeasible_service"
                elif cfg.service_protection and svc[j][1]:
                    r = "infeasible_late"
                elif sat is not None and any(
                        any(s0 and not sa for s0, sa in zip(sat[0][oid], sat[j + 1][oid])) for oid in ob_ids):
                    r = "infeasible_obligation"
                elif not (U_mean[j] > float(cfg.eps_gate) + float(cfg.gate_se_multiplier) * float(U_se[j])):
                    r = "gate"
                reasons.append(r)
            # obligation relaxation: no feasible policy (pi_0 or candidate) satisfies it in every scenario
            if sat is not None and not rounds:
                for oid in ob_ids:
                    ok0 = all(sat[0][oid])
                    ok_c = any(all(sat[j + 1][oid]) for j in range(len(remaining))
                               if reasons[j] in (None, "gate"))
                    if not ok0 and not ok_c:
                        relaxed_ids.append(oid)
                # explicit relaxation: dropped from the constraint set from the next round on
                ob_ids = [oid for oid in ob_ids if oid not in relaxed_ids]
            admissible = [j for j, r in enumerate(reasons) if r is None]
            rnd = {
                "round": len(rounds), "n_candidates": len(remaining),
                "J0_mean": float(res.J_mean[0]), "J0_se": float(res.J_se[0]),
                "F0_sizes": [int(v) for v in f0], "eval_wall_s": float(res.wall_time_s),
                "chosen": None,
            }
            if cfg.log_per_scenario:
                rnd["cand_indices"] = [int(i) for i in remaining]
                rnd["U_per_scenario"] = np.asarray(res.U, float).tolist()
                rnd["viol_per_scenario"] = per_scenario_service_violations(
                    res, protect_late=bool(cfg.protect_late_tasks))
            for j, i in enumerate(remaining):
                cand_log[i]["rounds"].append({"round": len(rounds), "U_mean": float(U_mean[j]),
                                              "U_se": float(U_se[j]), "J_mean": float(res.J_mean[j + 1]),
                                              "reason": reasons[j]})
            feasible_js = [j for j, r in enumerate(reasons) if r in (None, "gate")]
            top_pool = feasible_js if feasible_js else list(range(len(remaining)))
            rnd["top"] = int(remaining[max(top_pool, key=lambda j: U_mean[j])]) if top_pool else None
            if not admissible:
                for j, i in enumerate(remaining):
                    status[i] = reasons[j]
                J_exec, J_exec_se = float(res.J_mean[0]), float(res.J_se[0])
                rounds.append(rnd)
                break
            jb = max(admissible, key=lambda j: (U_mean[j], -j))
            ib = remaining[jb]
            c = cands[ib]
            row = sr.forced_task_row(c, t0=t0, task_id=self._next_dev_id(), deterring_modes=L["deterring_modes"],
                                     tau_service_s=float(L["tau_service_s"]))
            commitments.append((ib, row))
            status[ib] = "admitted"
            rnd["chosen"] = int(ib)
            rnd["chosen_U_mean"] = float(U_mean[jb])
            rnd["chosen_U_se"] = float(U_se[jb])
            J_exec, J_exec_se = float(res.J_mean[jb + 1]), float(res.J_se[jb + 1])
            rounds.append(rnd)
            for j, i in enumerate(remaining):
                if i != ib and cands[i].robot_id == c.robot_id and reasons[j] is None:
                    status[i] = "not_selected"
                elif i != ib and cands[i].robot_id == c.robot_id:
                    status[i] = reasons[j]
            snap_k = dataclasses.replace(snap_k, active_tasks=list(snap_k.active_tasks) + [copy.deepcopy(row)])
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
        rec = {
            "decision": idx, "t": t0, "seed": dec_seed, "n_candidates": len(cands),
            "n_evaluated": sum(1 for cl in cand_log if cl["rounds"]),
            "robot_share": share, "rho": rho, "forced_robots": sorted(forced),
            "rounds": rounds, "candidates": cand_log, "timed_out": bool(timed_out), "runtime_s": float(runtime),
            "admitted": [{"candidate": int(i), "robot": cands[i].robot_id, "x": cands[i].x, "y": cands[i].y,
                          "mode": cands[i].mode, "origin": cands[i].label, "task_id": int(row["id"])}
                         for i, row in commitments],
            "J_hat_executed": J_exec, "J_hat_executed_se": J_exec_se,
            "pending": len(snap0.pending_reactive), "max_deadline_margin_s": float(t0 + cfg.horizon_s - max_deadline)
            if deadlines else None,
            "obligations_outstanding": ob_ids, "obligations_relaxed": relaxed_ids,
            "oracle": None,
        }
        # ---------------- oracle evaluation (diagnostic; not part of the decision budget)
        if rounds and float(self._oracle_rng.random()) < float(cfg.oracle_fraction):
            rec["oracle"] = self._oracle(L, cands, cand_log, rounds, commitments, dec_seed)
        self.records.append(rec)
        return [copy.deepcopy(row) for _, row in commitments]

    def _oracle(self, L, cands, cand_log, rounds, commitments, dec_seed):
        cfg = self.cfg
        w0 = time.perf_counter()
        base = sr.decision_snapshot_from_sim_locals(L, horizon_s=cfg.horizon_s,
                                                    reactive_deadline_s=cfg.reactive_deadline_s, oracle=True)
        out = []
        if cfg.oracle_all_candidates and rounds and rounds[0].get("cand_indices"):
            idxs = list(rounds[0]["cand_indices"])
            resA = self.engine.evaluate(base, [cands[i] for i in idxs], n_scenarios=int(cfg.n_scenarios),
                                        seed=dec_seed, reactive_deadline_s=float(cfg.reactive_deadline_s),
                                        deadline=None)
            all_round0 = {"cand_indices": idxs, "U_oracle": np.asarray(resA.U_mean, float).tolist(),
                          "U_oracle_se": np.asarray(resA.U_se, float).tolist()}
        else:
            all_round0 = None
        for k, rnd in enumerate(rounds):
            top = rnd.get("top")
            if top is None:
                continue
            snap = dataclasses.replace(base, active_tasks=list(base.active_tasks)
                                       + [copy.deepcopy(row) for _, row in commitments[:k]])
            res = self.engine.evaluate(snap, [cands[top]], n_scenarios=int(cfg.n_scenarios), seed=dec_seed,
                                       reactive_deadline_s=float(cfg.reactive_deadline_s), deadline=None)
            # planner estimates of the same two policies in the same round
            J0_hat = float(rnd["J0_mean"])
            ca = next((e for e in cand_log[top]["rounds"] if e["round"] == k), None)
            out.append({
                "round": k, "candidate": int(top), "admitted": bool(rnd.get("chosen") == top),
                "J0_hat": J0_hat, "J0_hat_se": float(rnd["J0_se"]),
                "Ja_hat": float(ca["J_mean"]) if ca else math.nan,
                "U_hat": float(ca["U_mean"]) if ca else math.nan, "U_hat_se": float(ca["U_se"]) if ca else math.nan,
                "J0_oracle": float(res.J_mean[0]), "J0_oracle_se": float(res.J_se[0]),
                "Ja_oracle": float(res.J_mean[1]), "Ja_oracle_se": float(res.J_se[1]),
                "U_oracle": float(res.U_mean[0]), "U_oracle_se": float(res.U_se[0]),
            })
        return {"rounds": out, "all_round0": all_round0, "wall_s": time.perf_counter() - w0}

    # ------------------------------------------------------------- summary
    def finalize(self, *, exposure_event_log, t_end: float, t_report_offset: float = 0.0) -> dict:
        """Close the pool, attach realized exposure, write the JSONL log and return summary metrics."""
        H = float(self.cfg.horizon_s)
        ev = np.asarray(exposure_event_log, float).reshape(-1, 2) if len(exposure_event_log) else np.zeros((0, 2))
        for rec in self.records:
            t0 = float(rec["t"])
            sel = (ev[:, 0] > t0) & (ev[:, 0] <= t0 + H)
            rec["realized_exposure"] = float(ev[sel, 1].sum())
            rec["realized_window_complete"] = bool(t0 + H <= float(t_end) + 1e-9)
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
        for r in recs:
            n_cand += r["n_candidates"]
            for c in r["candidates"]:
                if c["status"] in counts:
                    counts[c["status"]] += 1
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
        real = [(r["J_hat_executed"], r["realized_exposure"]) for r in recs
                if r.get("realized_window_complete") and _finite(r["J_hat_executed"])]
        out = {
            "plan_decision_count": len(recs),
            "plan_candidates_total": int(n_cand),
            "plan_candidates_per_decision_mean": (n_cand / len(recs)) if recs else float("nan"),
            "plan_evaluated_candidates_total": int(sum(r["n_evaluated"] for r in recs)),
            "plan_rounds_total": int(sum(len(r["rounds"]) for r in recs)),
            "plan_deviations_admitted": int(sum(len(r["admitted"]) for r in recs)),
            "plan_decisions_with_deviation": int(sum(1 for r in recs if r["admitted"])),
            **{f"plan_rejected_{k}": int(v) for k, v in counts.items()},
            "plan_runtime_mean_s": _m(rt), "plan_runtime_p95_s": _q(rt, 95), "plan_runtime_p99_s": _q(rt, 99),
            "plan_runtime_max_s": float(np.max(rt)) if rt else float("nan"),
            "plan_timeouts": int(sum(1 for r in recs if r["timed_out"])),
            "plan_U_admitted_mean": _m(u_adm), "plan_U_admitted_se_mean": _m(u_adm_se),
            "plan_F0_size_mean": _m(f0),
            "plan_oracle_rounds": len(orc),
            "plan_pred_err_J0_bias": _m(e0), "plan_pred_err_J0_mean_abs": _m(np.abs(e0)),
            "plan_pred_err_J0_p95_abs": _q(np.abs(e0), 95), "plan_pred_err_J0_max_abs": float(np.max(np.abs(e0))) if e0 else float("nan"),
            "plan_pred_err_J0_rel_mean": _m(rel0),
            "plan_pred_err_Ja_bias": _m(ea), "plan_pred_err_Ja_mean_abs": _m(np.abs(ea)),
            "plan_pred_err_Ja_p95_abs": _q(np.abs(ea), 95),
            "plan_pred_err_U_bias": _m(eu), "plan_pred_err_U_mean_abs": _m(np.abs(eu)),
            "plan_pred_err_U_p95_abs": _q(np.abs(eu), 95), "plan_pred_err_U_max_abs": float(np.max(np.abs(eu))) if eu else float("nan"),
            "plan_oracle_U_sign_agree_fraction": _m([float(np.sign(o["U_hat"]) == np.sign(o["U_oracle"]))
                                                      for o in orc if _finite(o["U_hat"])]),
            "plan_oracle_admitted_rounds": len(adm_orc),
            "plan_oracle_admitted_U_oracle_mean": _m([o["U_oracle"] for o in adm_orc]),
            "plan_oracle_admitted_U_oracle_positive_fraction": _m([float(o["U_oracle"] > 0) for o in adm_orc]),
            "plan_realized_windows": len(real),
            "plan_realized_minus_pred_mean": _m([b - a for a, b in real]),
            "plan_realized_minus_pred_mean_abs": _m([abs(b - a) for a, b in real]),
            "plan_obligations_created": len(self.obligations),
            "plan_obligations_discharged": sum(1 for o in self.obligations if o["status"] == "discharged"),
            "plan_obligations_violated": sum(1 for o in self.obligations if o["status"] == "violated"),
            "plan_obligations_relaxed": sum(1 for o in self.obligations if o["status"] == "relaxed"),
            "plan_obligations_outstanding_at_end": sum(1 for o in self.obligations if o["status"] == "outstanding"),
        }
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
