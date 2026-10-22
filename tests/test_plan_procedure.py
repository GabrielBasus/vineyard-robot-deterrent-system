"""Tests for planner_procedure="plan" (habituation_stl/plan_procedure.py).

A stub engine replaces the Monte Carlo rollouts so each test controls U(a) and
the per-scenario completion times exactly; the real snapshot construction,
candidate generation, sequential commitment and the simulator overlay run as
in production.
"""
import math
import os
import time
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

from habituation_stl import scenario_rollout as sr  # noqa: E402

T_END = 240.0


def _params(seed=200, **over):
    from experiments.run_plan_completion import build_params
    p = build_params("B5", True, 2e-5, T_END)
    # Evaluation environment (2026-10-16): the original system (legacy estimator,
    # 200-entry truth deterrence memory) with coupled random streams.
    p.update(seed=seed, estimator_mode="legacy", random_stream_mode="coupled",
             truth_deterrence_memory="window200", reservation_fraction=0.25, reservation_window_s=600.0)
    p.update(over)
    return p


class StubEngine:
    """evaluate() returns U_fn(candidate, call) for every scenario; optional infeasibility."""

    def __init__(self, U_fn, *, infeasible_fn=None, n_s=4, timeout=False, ob_sat_fn=None,
                 eta_fn=None, ob_e_fn=None, U1_fn=None):
        self.U_fn = U_fn
        self.infeasible_fn = infeasible_fn or (lambda c, call: False)
        self.ob_sat_fn = ob_sat_fn or (lambda pol_index, ob: True)
        self.eta_fn = eta_fn                     # (candidate, scenario) -> q_hat at application
        self.ob_e_fn = ob_e_fn or (lambda pol_index, ob: math.nan)   # e_z at the deadline
        self.U1_fn = U1_fn                       # one-intervention U (candidate, call)
        self.calls = []
        self.n_s = n_s
        self.timeout = timeout

    def evaluate(self, snapshot, candidates, *, n_scenarios, seed, reactive_deadline_s, deadline=None,
                 one_intervention=False):
        if self.timeout and deadline is not None:
            while time.perf_counter() <= deadline:
                time.sleep(0.001)
            raise sr.EvaluationTimeout(0.0)
        call = len(self.calls)
        self.calls.append({"t0": snapshot.t0, "candidates": list(candidates),
                           "forced": [tr for tr in snapshot.active_tasks if tr.get("_forced_first")],
                           "start_stage": snapshot.start_stage, "obligations": list(snapshot.obligations),
                           "n_scenarios": n_scenarios, "seed": seed, "one_intervention": one_intervention,
                           "deadline": deadline})
        S = self.n_s
        t0 = snapshot.t0
        key = ("synthetic",)
        base = {key: {"created_t": t0, "deadline_t": t0 + 90.0, "completed_t": t0 + 10.0}}

        def res(done_t, pol_index, cand=None):
            obs = {ob["id"]: {"satisfied_t": (t0 + 1.0 if self.ob_sat_fn(pol_index, ob) else math.inf),
                              "min_e": 0.0, "e_deadline": float(self.ob_e_fn(pol_index, ob))}
                   for ob in snapshot.obligations}
            out = []
            for s in range(S):
                r = {"pending_completion": {key: dict(base[key], completed_t=done_t)}, "obligations": obs}
                if cand is not None and self.eta_fn is not None:
                    r["candidate_eta_planner"] = float(self.eta_fn(cand, s))
                out.append(r)
            return out
        per = [res(t0 + 10.0, 0)]
        U = []
        for j, c in enumerate(candidates):
            per.append(res(math.inf if self.infeasible_fn(c, call) else t0 + 10.0, j + 1, c))
            U.append(float(self.U_fn(c, call)))
        U = np.array(U, float)
        J0 = 100.0
        J = np.vstack([np.full(S, J0)] + [np.full(S, J0 - u) for u in U])
        ns = SimpleNamespace(per_scenario=per, J=J, J_mean=J.mean(axis=1), J_se=np.zeros(len(J)),
                             U=J[0][None, :] - J[1:], U_mean=U, U_se=np.zeros(len(U)), wall_time_s=0.0)
        if one_intervention:
            U1 = np.array([float(self.U1_fn(c, call)) for c in candidates], float)
            J1 = np.vstack([np.full(S, 50.0)] + [np.full(S, 50.0 - u) for u in U1])
            ns.J_one = J1
            ns.U_one = J1[0][None, :] - J1[1:]
            ns.U_one_mean = U1
            ns.U_one_se = np.zeros(len(U1))
        return ns

    def close(self):
        pass


def _run(params):
    import DeterrentSystem as ds
    frames = []
    for fr in ds.run_simulation_frames_persistent(**params):
        frames.append({"t": fr["t"], "poses": dict(fr["poses"]),
                       "active": sorted((tr["id"], tr["type"], tr.get("mode"), tr["assigned_primary"],
                                         round(tr["x"], 6), round(tr["y"], 6)) for tr in fr["tasks_active"]),
                       "vwe": fr["metrics_compact"]["value_weighted_exposure"]})
        last = fr
    return frames, last


@pytest.fixture(scope="module")
def b5_run():
    return _run(_params())


def _same_as_b5(frames, b5_frames):
    assert len(frames) == len(b5_frames)
    for a, b in zip(frames, b5_frames):
        assert a == b, f"diverged at t={b['t']}"


def test_stub_nonpositive_U_reproduces_b5(b5_run):
    eng = StubEngine(lambda c, call: -1.0 if hash((c.x, c.y)) % 2 else 0.0)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0))
    _same_as_b5(frames, b5_run[0])
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] == 0
    assert m["plan_decision_count"] == int(T_END // 45) + 1
    assert eng.calls and all(c["start_stage"] == "replan" for c in eng.calls)
    assert m["plan_rejected_gate"] > 0


def test_positive_feasible_candidate_is_executed_by_its_robot():
    target = {}

    def U(c, call):
        if call == 0 and not target:
            target.update(robot=c.robot_id, x=c.x, y=c.y, mode=c.mode)
        if call == 0 and (c.robot_id, c.x, c.y, c.mode) == (target["robot"], target["x"], target["y"], target["mode"]):
            return 5.0
        return -1.0

    eng = StubEngine(U)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0))
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] == 1
    first = frames[0]["active"]
    dev = [a for a in first if a[0] < 0]
    assert len(dev) == 1
    _, ttype, mode, rid, x, y = dev[0]
    assert (ttype, mode, rid) == ("deterring", target["mode"], target["robot"])
    assert (x, y) == (round(target["x"], 6), round(target["y"], 6))
    done = [tr for tr in last["tasks_done"] if tr.get("_plan_deviation")]
    still = [tr for tr in last["tasks_active"] if tr.get("_plan_deviation")]
    assert len(done) + len(still) == 1
    if done:
        assert done[0]["assigned_primary"] == target["robot"] and done[0]["state"] == "done"


def test_infeasible_candidate_is_not_executed(b5_run):
    eng = StubEngine(lambda c, call: 5.0, infeasible_fn=lambda c, call: True)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0))
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] == 0
    assert m["plan_rejected_infeasible_service"] > 0
    _same_as_b5(frames, b5_run[0])


def test_service_protection_off_admits_the_same_candidate():
    eng = StubEngine(lambda c, call: 5.0 if call == 0 else -1.0, infeasible_fn=lambda c, call: True)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_service_protection=False))
    assert last["metrics_compact"]["plan_deviations_admitted"] >= 1


def test_sequential_commitment_removes_committed_robot():
    order = {}

    def U(c, call):
        r = order.setdefault(c.robot_id, len(order))
        return 10.0 - r + 0.001 * (hash((c.x, c.y, c.mode)) % 100)

    eng = StubEngine(U)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0))
    # first decision with candidates from at least two robots that went to a second round
    # (under the legacy estimator only one robot may have candidates at t = 0)
    pairs = [(a, b) for a, b in zip(eng.calls, eng.calls[1:])
             if a["t0"] == b["t0"] and len({c.robot_id for c in a["candidates"]}) >= 2]
    assert pairs, "no decision with candidates of two robots and a second commitment round"
    first, second = pairs[0]
    best = max(first["candidates"], key=lambda c: U(c, 0))
    assert best.robot_id not in {c.robot_id for c in second["candidates"]}
    assert best.robot_id in [tr["assigned_primary"] for tr in second["forced"]]
    assert len(second["forced"]) == len(first["forced"]) + 1


def test_ceiling_blocks_deviations_at_rho(b5_run):
    eng = StubEngine(lambda c, call: 5.0)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                                reservation_fraction=0.0))
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] == 0
    assert m["plan_rejected_ceiling"] > 0
    assert not eng.calls
    # rho = 0 changes nothing else for B5 ("unc" ignores reservation_fraction)
    assert [f["vwe"] for f in frames] == [f["vwe"] for f in b5_run[0]]


def test_timeout_falls_back_to_b5(b5_run):
    eng = StubEngine(lambda c, call: 5.0, timeout=True)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                                plan_compute_budget_s=0.01))
    m = last["metrics_compact"]
    assert m["plan_timeouts"] == m["plan_decision_count"] > 0
    assert m["plan_timeout_rate"] == 1.0
    assert m["plan_deviations_admitted"] == 0
    assert m["plan_rejected_timeout"] > 0
    _same_as_b5(frames, b5_run[0])


class FirstStepEngine(StubEngine):
    """Replays step t0 in the engine from the snapshot: pi_0, or with admit=True the
    first decision's first candidate (admitted by the stub) as pi_a."""

    def __init__(self, admit=False):
        self.admit = admit
        super().__init__(lambda c, call: 5.0 if (admit and call == 0 and c == self._first) else -1.0)
        self.first_step = {}
        self._first = None

    def evaluate(self, snapshot, candidates, **kw):
        import copy as _copy
        call = len(self.calls)
        if self.admit and call > 0:
            return super().evaluate(snapshot, candidates, **kw)
        pol = sr.NOOP
        if self.admit:
            self._first = candidates[0]
            pol = candidates[0]
        snap = _copy.deepcopy(snapshot)
        snap.cfg.jitter_m = 0.0
        tree = sr._ScenarioTree(t=np.zeros(0), x=np.zeros(0), y=np.zeros(0), node=np.zeros(0, np.int64),
                                parent=np.zeros(0, np.int64), kind=np.zeros(0, np.int64), u_thin=np.zeros(0),
                                u_det=np.zeros(0), owner=np.zeros(0, np.int64), w_sched=np.zeros(0),
                                order=np.zeros(0, np.int64), step_start=np.zeros(1, np.int64), jitter_seed=0)
        sim = sr._Sim(snap, tree, pol, scenario=0, reactive_deadline_s=90.0)
        t = snap.t0
        sim._replan(t)
        sim._motion(t)
        # the evaluated candidate carries id -1; its committed copy in the simulator a
        # negative plan-deviation id: compare deviations without their id
        self.first_step[t] = {
            "poses": {rid: tuple(p) for rid, p in sim.pose.items()},
            "active": sorted(((tr["id"] if tr["id"] >= 0 else -1), tr["type"], tr.get("mode"),
                              tr["assigned_primary"], round(tr["x"], 6), round(tr["y"], 6))
                             for tr in sim.active_tasks),
        }
        return super().evaluate(snapshot, candidates, **kw)


@pytest.mark.parametrize("admit", [False, True])
def test_engine_first_step_equals_simulator_replan(monkeypatch, admit):
    """The decision snapshot is the state the B5 dispatcher sees: replaying the replan and
    motion of step t0 in the engine gives the simulator's tasks and poses exactly, for
    pi_0 (nothing admitted) and for an admitted deviation pi_a (B5 plus the deviation).
    Patrol jitter is set to 0 on both sides (residual difference R10)."""
    import TaskGenerator as TG
    orig = TG.TaskGenerator.periodic_patrolling

    def no_jitter(self, *args, **kw):
        kw["jitter_m"] = 0.0
        return orig(self, *args, **kw)

    monkeypatch.setattr(TG.TaskGenerator, "periodic_patrolling", no_jitter)
    eng = FirstStepEngine(admit=admit)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0))
    by_t = {f["t"]: f for f in frames}
    assert len(eng.first_step) >= (1 if admit else 3)
    if admit:
        assert last["metrics_compact"]["plan_deviations_admitted"] == 1
    for t0, st in eng.first_step.items():
        fr = by_t[t0]
        sys_active = sorted(((a[0] if a[0] >= 0 else -1),) + tuple(a[1:]) for a in fr["active"])
        assert st["active"] == sys_active, f"tasks differ at t={t0}"
        for rid, p in st["poses"].items():
            assert p == pytest.approx(tuple(fr["poses"][rid]), abs=1e-12), f"pose of {rid} differs at t={t0}"


def test_timed_recovery_obligation_blocks_violating_candidates(b5_run):
    """E_high = 0 triggers an obligation in every cell at t=0; E_low = -1 never resets it.
    pi_0 satisfies every obligation and no candidate does, so every candidate is
    infeasible while the obligations are outstanding (original deadline 1000 s kept)."""
    eng = StubEngine(lambda c, call: 5.0, ob_sat_fn=lambda pol, ob: pol == 0)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                                plan_E_high=0.0, plan_E_low=-1.0, plan_T_response_s=1000.0))
    m = last["metrics_compact"]
    n_cells = 4
    assert m["plan_obligations_created"] == n_cells
    assert m["plan_obligations_outstanding_at_end"] == n_cells
    assert m["plan_deviations_admitted"] == 0
    assert m["plan_rejected_infeasible_obligation"] > 0
    first = eng.calls[0]
    assert first["t0"] == 0.0 and len(first["obligations"]) == n_cells
    assert all(ob["deadline_t"] == 1000.0 for c in eng.calls for ob in c["obligations"])
    _same_as_b5(frames, b5_run[0])


def test_timed_recovery_violation_at_original_deadline():
    eng = StubEngine(lambda c, call: -1.0)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_E_high=0.0, plan_E_low=-1.0, plan_T_response_s=50.0))
    m = last["metrics_compact"]
    assert m["plan_obligations_created"] == m["plan_obligations_violated"] == 4   # latched, no re-trigger
    assert all(not c["obligations"] for c in eng.calls if c["t0"] > 50.0)


def test_timed_recovery_relaxes_unsatisfiable_obligations():
    eng = StubEngine(lambda c, call: -1.0, ob_sat_fn=lambda pol, ob: False)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_E_high=0.0, plan_E_low=-1.0, plan_T_response_s=50.0,
                           plan_obligation_relaxation="drop"))
    m = last["metrics_compact"]
    assert m["plan_obligations_relaxed"] == m["plan_obligations_created"] == 4
    assert m["plan_obligations_violated"] == 0


def test_engine_tracks_obligations_and_cell_exposure():
    """Engine side of Eq. 4: per-cell forecast exposure along a rollout, first time <= E_low."""
    import copy as _copy
    snap = None

    class Capture(StubEngine):
        def evaluate(self, snapshot, candidates, **kw):
            nonlocal snap
            if snap is None and snapshot.t0 >= 90.0:
                snap = _copy.deepcopy(snapshot)
            return super().evaluate(snapshot, candidates, **kw)

    _run(_params(planner_procedure="plan", plan_engine=Capture(lambda c, call: -1.0), plan_oracle_fraction=0.0))
    assert snap is not None
    t0 = snap.t0
    snap.horizon_s = 30.0
    snap.obligations = [{"id": "always", "cell": 0, "deadline_t": t0 + 20.0, "e_low": math.inf},
                        {"id": "never", "cell": 1, "deadline_t": t0 + 20.0, "e_low": -1.0}]
    res = sr.run_policy(snap, sr.NOOP, n_scenarios=2, seed=3)
    for r in res:
        assert r["obligations"]["always"]["satisfied_t"] == t0 + 1.0
        assert math.isinf(r["obligations"]["never"]["satisfied_t"])
        assert r["obligations"]["never"]["min_e"] > 0.0
    # cell exposures partition the region rate
    world = sr._World(snap, list(snap.world_suppression or []))
    rate = world.node_exposure_rate(t0)
    assert float(rate.sum()) == pytest.approx(world.residual_rate(t0), rel=1e-9)


def test_legacy_procedure_rejects_unknown_mode():
    import DeterrentSystem as ds
    with pytest.raises(ValueError):
        next(ds.run_simulation_frames_persistent(**_params(planner_procedure="bogus")))


def test_plan_requires_unc_dispatch():
    import DeterrentSystem as ds
    with pytest.raises(ValueError):
        next(ds.run_simulation_frames_persistent(**_params(planner_procedure="plan", dispatch_policy="res")))


# ---------------------------------------------------------------------------
# Section 6 decisions (2026-10-21)
# ---------------------------------------------------------------------------
def _records(path):
    import json
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    return [r for r in rows if "decision" in r]


def test_eta_floor_rejects_low_effectiveness_at_application():
    """Decision 26: q_hat at application below the floor in a scenario rejects the candidate."""
    eng = StubEngine(lambda c, call: 5.0, eta_fn=lambda c, s: 0.3 if s == 0 else 0.9)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                                plan_eta_floor=0.4))
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] == 0
    assert m["plan_rejected_floor"] > 0
    assert m["plan_floor_q_hat_scenario_disagreements"] > 0
    eng = StubEngine(lambda c, call: 5.0, eta_fn=lambda c, s: 0.5)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_eta_floor=0.4))
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] >= 1 and m["plan_rejected_floor"] == 0


def test_one_intervention_valuation_gates_on_U_one():
    """Decision 8 (C_plan): admission reads the one-intervention U; feasibility is unchanged."""
    eng = StubEngine(lambda c, call: 5.0, U1_fn=lambda c, call: -1.0)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_valuation="one_intervention"))
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] == 0 and m["plan_rejected_gate"] > 0
    assert eng.calls and all(c["one_intervention"] for c in eng.calls)
    eng = StubEngine(lambda c, call: -1.0, U1_fn=lambda c, call: 5.0)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_valuation="one_intervention"))
    assert last["metrics_compact"]["plan_deviations_admitted"] >= 1
    eng = StubEngine(lambda c, call: -1.0, U1_fn=lambda c, call: 5.0, infeasible_fn=lambda c, call: True)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_valuation="one_intervention"))
    m = last["metrics_compact"]
    assert m["plan_deviations_admitted"] == 0 and m["plan_rejected_infeasible_service"] > 0


def test_bounded_violation_keeps_obligation_and_minimises_exceedance(tmp_path):
    """Decision 28: an obligation no policy satisfies is kept (not dropped); pi_0 is kept when
    every candidate's exceedance at the deadline is larger, and the violation size is recorded."""
    path = tmp_path / "a.jsonl"
    eng = StubEngine(lambda c, call: 5.0, ob_sat_fn=lambda pol, ob: False,
                     ob_e_fn=lambda pol, ob: 10.0 if pol == 0 else 20.0)
    frames, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                                plan_E_high=0.0, plan_E_low=-1.0, plan_T_response_s=50.0,
                                plan_log_path=str(path)))
    m = last["metrics_compact"]
    assert m["plan_obligations_relaxed"] == 0
    assert m["plan_obligations_bounded"] == m["plan_obligations_created"] == 4
    assert m["plan_obligations_violated"] == 4
    assert m["plan_obligation_violation_size_mean"] > 0.0
    assert m["plan_rejected_obligation_exceedance"] > 0
    # while the obligations are outstanding (deadline 50 s) pi_0 is kept
    assert all(not r["admitted"] for r in _records(path) if r["t"] <= 50.0)
    rec = _records(path)[0]
    assert rec["obligations_bounded"] and not rec["obligations_relaxed"]
    ex = rec["rounds"][0]["obligation_exceedance"]
    assert ex["X_pi0"] == pytest.approx(4 * 11.0) and all(x == pytest.approx(4 * 21.0) for x in ex["X"])
    eng = StubEngine(lambda c, call: 5.0, ob_sat_fn=lambda pol, ob: False,
                     ob_e_fn=lambda pol, ob: 20.0 if pol == 0 else 10.0)
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=0.0,
                           plan_E_high=0.0, plan_E_low=-1.0, plan_T_response_s=50.0))
    assert last["metrics_compact"]["plan_deviations_admitted"] >= 1


def test_oracle_independent_scenarios_and_kendall_tau(tmp_path):
    """Decisions 31 and 12: the oracle uses its own scenario count and seed stream; with
    all round-0 candidates evaluated it reports Kendall tau (stub: oracle U = planner U)."""
    eng = StubEngine(lambda c, call: float(hash((c.x, c.y, c.mode)) % 7) - 3.0)
    path = tmp_path / "o.jsonl"
    _, last = _run(_params(planner_procedure="plan", plan_engine=eng, plan_oracle_fraction=1.0,
                           plan_oracle_scenarios=8, plan_oracle_all_candidates=True, plan_log_path=str(path)))
    m = last["metrics_compact"]
    planner = [c for c in eng.calls if c["n_scenarios"] == 16]
    oracle = [c for c in eng.calls if c["n_scenarios"] == 8]
    assert planner and oracle
    assert not ({c["seed"] for c in planner} & {c["seed"] for c in oracle})
    assert m["plan_oracle_scenarios"] == 8
    assert m["plan_oracle_kendall_tau_n"] > 0 and m["plan_oracle_kendall_tau_mean"] == pytest.approx(1.0)
    recs = [r for r in _records(path) if r["oracle"]]
    assert recs and all(r["oracle"]["n_scenarios"] == 8 for r in recs)


def test_admitted_deviation_ranking_travel_and_f0_logged(tmp_path):
    """Decisions 12, 13, 29: per admitted deviation its B5 rank and whether B5 would do the
    same, predicted vs realized travel; per decision the F0-protected tasks and outcomes."""
    target = {}

    def U(c, call):
        if call == 0 and not target:
            target.update(robot=c.robot_id, x=c.x, y=c.y, mode=c.mode)
        return 5.0 if call == 0 and (c.robot_id, c.x, c.y, c.mode) == tuple(target.values()) else -1.0

    path = tmp_path / "r.jsonl"
    _, last = _run(_params(planner_procedure="plan", plan_engine=StubEngine(U), plan_oracle_fraction=0.0,
                           plan_log_path=str(path)))
    recs = _records(path)
    adm = [a for r in recs for a in r["admitted"]]
    assert len(adm) == 1
    a = adm[0]
    assert a["b5_rank"] is not None and 1 <= a["b5_rank"] <= a["n_robot_candidates"]
    assert isinstance(a["differs_from_b5"], bool)
    done = [tr for tr in last["tasks_done"] + last["tasks_active"] if tr.get("_plan_deviation")]
    sh = done[0].get("started_hold")
    if sh is not None:
        assert a["real_travel_s"] == pytest.approx(float(sh) - recs[0]["t"])
    f0 = recs[0]["f0_protected"]
    assert f0 and f0[0]["n_in_F0"] == 4 and f0[0]["met"] is False   # synthetic key never served
    m = last["metrics_compact"]
    assert m["plan_F0_protected_tasks"] == 1
    assert m["plan_dev_differs_from_b5_fraction"] in (0.0, 1.0)


def test_real_engine_timeout_falls_back_to_b5(b5_run):
    """Decision 16: with the real rollout engine a budget too small for any evaluation makes
    every decision time out; the executed system is B5 and the timeout rate is reported."""
    import psutil
    if psutil.virtual_memory().available < 12 * 1024 ** 3:
        pytest.skip("less than 12 GB available")
    frames, last = _run(_params(planner_procedure="plan", plan_oracle_fraction=0.0, plan_compute_budget_s=0.05,
                                plan_pool_workers=2))
    m = last["metrics_compact"]
    assert m["plan_timeout_rate"] == 1.0 and m["plan_deviations_admitted"] == 0
    _same_as_b5(frames, b5_run[0])


# --------------------------- decision 1: q x beta everywhere
@pytest.fixture(scope="module")
def captured():
    import copy as _copy
    import sys
    store = {}

    class Capture(StubEngine):
        def evaluate(self, snapshot, candidates, **kw):
            if "snap" not in store and snapshot.t0 >= 90.0:
                fr = sys._getframe(1)
                while fr is not None and "L" not in fr.f_locals:
                    fr = fr.f_back
                L = fr.f_locals["L"]
                store["snap"] = _copy.deepcopy(snapshot)
                store["oracle"] = sr.decision_snapshot_from_sim_locals(L, horizon_s=snapshot.horizon_s,
                                                                       reactive_deadline_s=90.0, oracle=True)
                store["stl_local"] = bool(L["stl_forecast_correction"])
            return super().evaluate(snapshot, candidates, **kw)

    _run(_params(planner_procedure="plan", plan_engine=Capture(lambda c, call: -1.0), plan_oracle_fraction=0.0,
                 stl_forecast_correction=True))
    assert "snap" in store
    return store


def _cand_at_robot(snap):
    rs = snap.robots[0]
    mode = sorted(snap.deterring_modes)[0]
    c = sr.Candidate(rs.rid, float(rs.pose[0]), float(rs.pose[1]), mode)
    row = sr.forced_task_row(c, t0=snap.t0, task_id=-5, deterring_modes=snap.deterring_modes,
                             tau_service_s=float(snap.cfg.tau_service_s))
    label = str(sr.task_action(row, deterring_modes=snap.deterring_modes,
                               default_service_time_s=float(snap.cfg.tau_service_s)).name)
    cell, midx, _ = sr._hab_indices(snap, c.x, c.y, label)
    assert cell is not None and midx is not None
    return c, cell, midx


def _run_spied(snap, cand, monkeypatch):
    import Robot as R
    inhib, fb = [], []
    orig = sr._World.add_legacy_inhibition
    origf = R.Robot.ingest_intervention_event

    def spy(self, x, y, mode, weight, sigma, omega):
        inhib.append((str(mode), float(weight)))
        return orig(self, x, y, mode, weight, sigma, omega)

    def spyf(self, x, y, t, weight=1.0, sigma=None, omega_inhib=None, *, mode=None, beta=None, action_id=None):
        fb.append(float(weight))
        return origf(self, x, y, t, weight, sigma, omega_inhib, mode=mode, beta=beta, action_id=action_id)

    monkeypatch.setattr(sr._World, "add_legacy_inhibition", spy)
    monkeypatch.setattr(R.Robot, "ingest_intervention_event", spyf)
    r = sr.run_policy(snap, cand, n_scenarios=1, seed=5)[0]
    monkeypatch.undo()
    return r, inhib, fb


def test_q_times_beta_in_planner_world_candidate_continuation_and_feedback(captured, monkeypatch):
    """Decision 1: the snapshot carries stl_forecast_correction from the simulator; every
    application in a rollout (the candidate and the B5 continuation) stamps the planner
    world and the robot feedback with q_hat * beta, q_hat the planner effectiveness at
    application; without the flag the stamp is beta."""
    import copy as _copy
    assert captured["stl_local"] is True
    snap = _copy.deepcopy(captured["snap"])
    assert snap.cfg.stl_forecast_correction is True and snap.forecast.form == "legacy"
    snap.horizon_s = 150.0
    c, cell, midx = _cand_at_robot(snap)
    snap.habituation.eta[cell, midx] = 0.5
    r_on, inhib_on, fb_on = _run_spied(snap, c, monkeypatch)
    off = _copy.deepcopy(snap)
    off.cfg.stl_forecast_correction = False
    r_off, inhib_off, fb_off = _run_spied(off, c, monkeypatch)
    iv_on = r_on["interventions"]
    assert len(iv_on) == len(inhib_on) and iv_on
    k = next(i for i, iv in enumerate(iv_on) if iv["candidate"])
    q = iv_on[k]["eta_planner"]
    assert 0.5 <= q < 0.6
    k_off = next(i for i, iv in enumerate(r_off["interventions"]) if iv["candidate"])
    raw = inhib_off[k_off][1]
    assert inhib_on[k][1] == pytest.approx(q * raw, rel=1e-12)
    # every application (continuation included): weight / q_hat is the cue's raw beta
    ratio = {}
    for iv, (mode, w) in zip(iv_on, inhib_on):
        ratio.setdefault(mode, set()).add(round(w / iv["eta_planner"], 12))
        assert w in fb_on            # the executing robot's feedback carries the same amplitude
    assert all(len(v) == 1 for v in ratio.values())
    for iv, (mode, w) in zip(r_off["interventions"], inhib_off):
        assert w == pytest.approx(next(iter(ratio[mode])), rel=1e-9)


def test_oracle_world_uses_truth_eta_policy_uses_planner_q(captured):
    """Decision 1, oracle side: the truth world's suppression entry carries the truth
    effectiveness at application while the policy side keeps the planner q_hat."""
    import copy as _copy
    o = _copy.deepcopy(captured["oracle"])
    assert o.world_habituation is not None and o.world_suppression is not None
    o.horizon_s = 150.0
    c, cell, midx = _cand_at_robot(o)
    o.habituation.eta[cell, midx] = 0.5
    o.world_habituation.eta[cell, midx] = 0.2
    sim = sr._Sim(o, sr._sample_scenario_tree(o, 5, 0), c, scenario=0, reactive_deadline_s=90.0)
    r = sim.run()
    iv = next(iv for iv in r["interventions"] if iv["candidate"])
    assert 0.2 <= iv["eta"] < 0.3 and 0.5 <= iv["eta_planner"] < 0.6
    entry = next(e for e in sim.world_store if e.get("action_id") == -1)
    assert entry["eta"] == iv["eta"]


def test_executed_feedback_uses_planner_q_times_beta(monkeypatch):
    """Decision 1, executed side: the simulator stamps the executing robot's model with
    q_hat * beta (q_hat = planner effectiveness just before depletion) when
    stl_forecast_correction is on, and with beta otherwise."""
    import DeterrentSystem as ds
    import Robot as R

    def collect(stl):
        log = []
        oh = ds._apply_habituation_update
        oi = R.Robot.ingest_intervention_event

        def hab(field, cell, mode, model):
            log.append(("hab", float(field.effectiveness(cell, mode))))
            return oh(field, cell, mode, model)

        def ing(self, x, y, t, weight=1.0, sigma=None, omega_inhib=None, *, mode=None, beta=None, action_id=None):
            log.append(("ing", float(weight), str(mode)))
            return oi(self, x, y, t, weight, sigma, omega_inhib, mode=mode, beta=beta, action_id=action_id)

        monkeypatch.setattr(ds, "_apply_habituation_update", hab)
        monkeypatch.setattr(R.Robot, "ingest_intervention_event", ing)
        p = _params(T_end=900.0, stl_forecast_correction=stl)
        for _ in ds.run_simulation_frames_persistent(**p):
            pass
        monkeypatch.undo()
        own, n_hab, q = [], 0, None
        for e in log:            # truth then planner update per application; next ingest = own robot
            if e[0] == "hab":
                n_hab += 1
                if n_hab % 2 == 0:
                    q = e[1]
            elif q is not None:
                own.append((e[2], e[1], q))
                q = None
        return own

    off = collect(False)
    raw = {}
    for mode, w, _q in off:
        raw.setdefault(mode, set()).add(w)
    assert off and all(len(v) == 1 for v in raw.values())
    on = collect(True)
    assert on
    for mode, w, q in on:
        assert w == pytest.approx(q * next(iter(raw[mode])), rel=1e-12)
    assert any(q < 1.0 - 1e-9 for _, _, q in on)
