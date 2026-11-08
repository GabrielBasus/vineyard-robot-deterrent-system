"""
Tests for the B4-pipeline variants A, B, C, C_gate (Plan Sections 2-3, user
decisions 5, 6, 7 and 27 of 2026-10-21).

  * A unchanged bit-for-bit with every new flag at its default (pre-change reference).
  * B: committed-schedule pending timeline (reactive tasks mapped to the cue the
    simulator depletes for direct detections, "laser"), queue-aware lead, same
    habituation update routine in forecasts.
  * C: Eq. 3 value equals a brute-force grid integral of J_H(no cand) - J_H(with cand).
  * C_gate: the reservation ceiling never forces predictive work and blocks it at
    share >= rho.
  * Section 3: inactive-action (hab clause) entries change the number of soft-min
    arguments and thereby the score; binding (time, cell, clause) diagnostics.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import habituation_stl  # noqa: F401  (puts habituation_stl/ on sys.path)
from habituation_stl.habituation import HabituationField, apply_habituation_update
from habituation_stl.mission_spec import SpecParams, build_spec
from habituation_stl.stl import Trace, robustness_at
from habituation_stl.task_value import (
    CellState, Dynamics, clause_binding, forecast_q_hat, robustness_breakdown,
)
from planner_committed_schedule import emulate_robot_schedule
from Robot import SlidingWindowTimeTracker

DATA = Path(__file__).resolve().parent / "data" / "b4_variant_A_reference.json"
_RUNTIME_KEYS = ("stl_eval_runtime_mean_ms", "stl_eval_runtime_p95_ms", "stl_eval_runtime_p99_ms",
                 "stl_eval_runtime_first_eval_mean_ms", "stl_eval_runtime_first_eval_p95_ms",
                 "stl_eval_runtime_first_eval_p99_ms", "stl_eval_runtime_total_s",
                 "stl_eval_runtime_first_eval_total_s")
LASER_ID = 2  # mode_labels = (direct_detection, formation, laser, biosonic)


def _run(params):
    import DeterrentSystem as ds
    last = None
    for frame in ds.run_simulation_frames_persistent(**params):
        last = frame
    return (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}


def _ref_params(t_end=None, **over):
    ref = json.loads(DATA.read_text())
    params = dict(ref["params"])
    params["stl_active_clauses"] = tuple(params["stl_active_clauses"])
    if t_end is not None:
        params["T_end"] = float(t_end)
    params.update(over)
    return params


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


# ---------------------------------------------------------------------------
# A unchanged bit-for-bit
# ---------------------------------------------------------------------------
def test_variant_A_bit_for_bit_with_new_flags_at_defaults():
    ref = json.loads(DATA.read_text())
    params = _ref_params(
        stl_committed_schedule=False, stl_queue_aware_lead=False,
        stl_forecast_planner_update_model=False, stl_binding_log_path=None,
        stl_binding_log_fraction=0.0, reservation_mode="floor",
    )
    m = _run(params)
    diffs = [k for k, v in ref["metrics"].items()
             if k not in _RUNTIME_KEYS and not k.startswith("selected_calibration_")
             and not _same(v, m.get(k))]
    # selected_calibration_* echo the calibration record read from disk (the untracked
    # ranking CSV when present, else the tracked manifest JSON); the two parse to values
    # differing in the last ulp, so they are checkout metadata, not simulation behavior.
    assert diffs == []


# ---------------------------------------------------------------------------
# Same state-update routine (decision 5d)
# ---------------------------------------------------------------------------
def test_simulator_update_is_the_shared_routine():
    import DeterrentSystem as ds
    for model in ("multiplicative", "additive_drop"):
        h1 = HabituationField(2, 3, T_rec=600.0, kappa=0.4, gamma=0.2)
        h2 = h1.copy()
        h1.eta[:] = h2.eta[:] = 0.8
        ds._apply_habituation_update(h1, 1, 2, model)
        apply_habituation_update(h2, 1, 2, model)
        assert np.array_equal(h1.eta, h2.eta)


def test_forecast_uses_planner_update_model():
    hab = HabituationField(2, 2, T_rec=1000.0, kappa=0.3)
    hab.eta[0, 1] = 0.9
    pend = [(10.0, 0, 1), (40.0, 0, 1)]
    dyn = Dynamics(forecast_correction=True, hab_update_model="additive_drop")
    q, post = forecast_q_hat(0, 1, 100.0, hab, dyn, pend)
    manual = hab.copy()
    manual.recover(10.0); apply_habituation_update(manual, 0, 1, "additive_drop")
    manual.recover(30.0); apply_habituation_update(manual, 0, 1, "additive_drop")
    manual.recover(60.0)
    assert q == pytest.approx(manual.effectiveness(0, 1), abs=1e-15)
    apply_habituation_update(manual, 0, 1, "additive_drop")
    assert post == pytest.approx(manual.effectiveness(0, 1), abs=1e-15)
    # default (flag off) keeps the historical hab.apply / (1 - kappa) q path
    q0, post0 = forecast_q_hat(0, 1, 100.0, hab, Dynamics(forecast_correction=True), pend)
    legacy = hab.copy()
    legacy.recover(10.0); legacy.apply(0, 1); legacy.recover(30.0); legacy.apply(0, 1); legacy.recover(60.0)
    assert q0 == legacy.effectiveness(0, 1)
    assert post0 == (1.0 - 0.3) * q0
    assert np.all(hab.eta[0, 1] == 0.9)  # live state untouched


# ---------------------------------------------------------------------------
# Committed schedule emulation (decision 5a/5b)
# ---------------------------------------------------------------------------
def _sel_first_reactive(tasks, t, eta_fn, share, idle):
    rx = [tr for tr in tasks if tr.get("stream") == "reactive"]
    if rx:
        return rx[0], False
    return tasks[0], False


def _emu(tasks, **kw):
    base = dict(now_t=100.0, dt=1.0, horizon_s=300.0, pose=(0.0, 0.0), speed_mps=1.0, spin_s=0.0,
                arrival_radius_m=0.5, loiter_until=-1.0, goal_xy=None, tasks=tasks,
                service_s_fn=lambda tr: float(tr.get("svc", 0.0)),
                is_deterring_fn=lambda tr: tr["type"] == "deterring",
                stream_fn=lambda tr: tr.get("stream", "predictive"),
                select_fn=_sel_first_reactive, tracker=None)
    base.update(kw)
    return emulate_robot_schedule(**base)


def test_schedule_serves_queue_in_rule_order_with_travel_and_holds():
    a = {"id": 1, "type": "deterring", "x": 10.0, "y": 0.0, "svc": 20.0, "stream": "predictive"}
    b = {"id": 2, "type": "deterring", "x": 10.0, "y": 30.0, "svc": 20.0, "stream": "reactive"}
    res = _emu([a, b])
    (t1, c1), (t2, c2) = [(tr["id"], t) for tr, t in res["completions"]]
    # reactive b first: arrival within 0.5 m after ceil(31.12 - 0.5) steps, then 20 s hold
    assert (t1, t2) == (2, 1)
    d_b = math.hypot(10.0, 30.0)
    assert c1 == pytest.approx(100.0 + math.ceil(d_b - 0.5) - 1 + 20.0, abs=1.0)
    assert c2 > c1 + 30.0 + 20.0 - 2.0
    assert res["free_t"] == pytest.approx(c2 + 1.0)
    assert res["free_xy"] == pytest.approx((10.0, 0.0), abs=0.5)
    assert a.get("started_hold") is None and b.get("started_hold") is None  # rows never mutated


def test_schedule_current_hold_and_horizon_cutoff():
    a = {"id": 1, "type": "deterring", "x": 0.0, "y": 0.0, "svc": 20.0, "started_hold": 95.0}
    res = _emu([a], loiter_until=115.0, goal_xy=(0.0, 0.0))
    assert [t for _, t in res["completions"]] == [115.0]
    far = {"id": 3, "type": "deterring", "x": 1000.0, "y": 0.0, "svc": 20.0}
    res2 = _emu([far])
    assert res2["completions"] == [] and math.isinf(res2["free_t"])
    assert _emu([])["free_t"] == 100.0


def test_schedule_advances_share_tracker():
    tr = SlidingWindowTimeTracker(600.0)
    seen = []

    def sel(tasks, t, eta_fn, share, idle):
        seen.append(share)
        return tasks[0], False

    a = {"id": 1, "type": "patrolling", "x": 60.0, "y": 0.0, "stream": "predictive"}
    _emu([a], select_fn=sel, tracker=tr)
    assert seen[0] == 0.0 and seen[-1] == pytest.approx(59.0 / 600.0, abs=2.0 / 600.0)


def _capture_run(**over):
    """Short B run capturing the committed schedules and every STL evaluation."""
    import DeterrentSystem as ds
    import TaskGenerator as tg
    sched, evals = [], []
    orig_emu = ds.emulate_robot_schedule
    orig_est = tg.estimate_stl_counterfactual_value

    def emu(**kw):
        res = orig_emu(**kw)
        sched.append((kw["now_t"], list(kw["tasks"]), res))
        return res

    def est(*a, **kw):
        evals.append(kw)
        return orig_est(*a, **kw)

    ds.emulate_robot_schedule = emu
    tg.estimate_stl_counterfactual_value = est
    try:
        params = _ref_params(t_end=240.0, mu_true=1.0e-4, stl_forecast_correction=True,
                             stl_forward_trajectory_correction=True, stl_committed_schedule=True,
                             stl_queue_aware_lead=True, stl_forecast_planner_update_model=True)
        params.update(over)
        _run(params)
    finally:
        ds.emulate_robot_schedule = orig_emu
        tg.estimate_stl_counterfactual_value = orig_est
    return sched, evals


@pytest.fixture(scope="module")
def b_capture():
    return _capture_run()


def test_B_pending_timeline_includes_reactive_tasks_mapped_to_laser(b_capture):
    sched, evals = b_capture
    found = False
    for now_t, tasks, res in sched:
        for tr, t_c in res["completions"]:
            if tr.get("mode") in (None, "", "none") and tr.get("type") == "deterring":
                rel = t_c - now_t
                for kw in evals:
                    if kw["now_t"] != now_t:
                        continue
                    if any(abs(e[0] - rel) < 1e-9 and e[2] == LASER_ID for e in kw["pending_events"]):
                        found = True
    assert found, "no reactive direct-detection completion reached the q_hat timeline as laser"


def test_B_queue_aware_lead_formula():
    """Lead = free_rel + straight-line travel from where the queue ends + hold."""
    import DeterrentSystem as ds
    import TaskGenerator as tg
    sched, leads = [], []
    orig_emu = ds.emulate_robot_schedule
    orig_est = tg.estimate_stl_counterfactual_value

    def emu(**kw):
        res = orig_emu(**kw)
        sched.append((kw["now_t"], kw["tasks"][0]["assigned_primary"], kw["speed_mps"], res))
        return res

    def est(model, x, y, **kw):
        leads.append((kw["now_t"], float(x), float(y), kw["completion_lead_s"], kw["mode"]))
        return orig_est(model, x, y, **kw)

    ds.emulate_robot_schedule = emu
    tg.estimate_stl_counterfactual_value = est
    try:
        params = _ref_params(t_end=240.0, mu_true=1.0e-4, stl_forecast_correction=True,
                             stl_committed_schedule=True, stl_queue_aware_lead=True,
                             Nrobots=1)
        _run(params)
    finally:
        ds.emulate_robot_schedule = orig_emu
        tg.estimate_stl_counterfactual_value = orig_est
    hold = 20.0
    checked = 0
    for now_t, rid, speed, res in sched:
        if math.isinf(res["free_t"]):
            continue
        fx, fy = res["free_xy"]
        for t_l, x, y, lead, mode in leads:
            if t_l != now_t:
                continue
            exp = (res["free_t"] - now_t) + math.hypot(x - fx, y - fy) / speed + hold
            assert lead == pytest.approx(exp, rel=1e-12, abs=1e-9)
            checked += 1
    assert checked > 0


# ---------------------------------------------------------------------------
# C: Eq. 3 equals a brute-force grid integral
# ---------------------------------------------------------------------------
def test_eq3_matches_bruteforce_grid_integral():
    from SESTPP import OnlineSESTPP
    from ZonePartitioner import point_in_polygon
    from planner_task_estimation import eq3_counterfactual_value

    m = OnlineSESTPP(0.0, 60.0, 0.0, 60.0, 7, 7, sigma=10.0, omega=500.0, omega_inhib=700.0,
                     alpha_inhib=0.3, mu_base=2e-3)
    rng = np.random.default_rng(3)
    m.mu = rng.uniform(1e-3, 3e-3, size=(7, 7))
    m.trigger_mass = rng.uniform(0.0, 4e-3, size=(7, 7))
    m.inhib_channels = {"laser": rng.uniform(0.0, 6e-3, size=(7, 7))}
    m.inhib_channel_omegas = {"laser": 700.0}
    m.t_now = 0.0
    m._update_lambda()
    cells = [[(0, 0), (30, 0), (30, 60), (0, 60)], [(30, 0), (60, 0), (60, 60), (30, 60)]]
    wfn = lambda x, y: 1.0 + 0.01 * x
    hab = HabituationField(2, 2, T_rec=900.0, kappa=0.5)
    hab.eta[1, 1] = 0.6
    params = SpecParams(horizon=40.0, active_clauses=("exp", "cov", "hab"))
    dt = 2.0
    for ftc in (True, False):
        dyn = Dynamics(omega_e=500.0, omega_u=700.0, beta=(0.5, 0.8), forecast_correction=True,
                       forward_trajectory_correction=ftc, feedback_sigma_scale=1.5,
                       feedback_omega_scale=2.0, valuation_mode="integrated_exposure_eq3")
        pend = [(3.0, 1, 1)]
        lead = 7.0
        x, y = 40.0, 25.0
        out = eq3_counterfactual_value(
            m, x, y, cells=[0, 1], cell_polys=cells, weight_fn=wfn, hab=hab, spec_params=params,
            dynamics=dyn, target_cell_id=1, mode_id=1, completion_lead_s=lead, now_t=0.0,
            cue_sigma=8.0, cue_omega=300.0, pending_events=pend, dt=dt)
        q, _ = forecast_q_hat(1, 1, lead, hab, dyn, pend)
        # the candidate stamp exactly as the planner model would receive it
        m2 = OnlineSESTPP(0.0, 60.0, 0.0, 60.0, 7, 7, sigma=10.0, omega=500.0,
                          omega_inhib=700.0, alpha_inhib=0.3)
        m2.add_intervention_event(x, y, weight=q * 0.8, sigma=8.0 * 1.5, omega_inhib=600.0, mode="cand")
        S = m2.inhib_channels["cand"]
        dA = m.dx * m.dy
        J0 = J1 = 0.0
        for k in range(int(round(40.0 / dt))):
            s = k * dt
            for poly in cells:
                for iy in range(7):
                    for ix in range(7):
                        px, py = m.xs[ix], m.ys[iy]
                        if not point_in_polygon(px, py, poly):
                            continue
                        w = wfn(px, py)
                        if ftc:
                            raw = (m.mu[iy, ix] + m.trigger_mass[iy, ix] * math.exp(-s / 500.0)
                                   - m.inhib_mass[iy, ix] * math.exp(-s / 700.0))
                        else:
                            raw = m.lam[iy, ix] * math.exp(-s / 500.0)
                        cand = S[iy, ix] * math.exp(-(s - lead) / 600.0) if s >= lead else 0.0
                        J0 += w * dA * max(0.0, raw) * dt
                        J1 += w * dA * max(0.0, (raw if ftc else max(0.0, raw)) - cand) * dt
        assert out["U"] == pytest.approx(J0 - J1, rel=1e-10)
        assert out["U"] > 0.0
        assert out["q_hat"] == pytest.approx(q)


# ---------------------------------------------------------------------------
# C_gate: reservation ceiling
# ---------------------------------------------------------------------------
def _dispatch(tasks, share, mode):
    import DeterrentSystem as ds
    return ds._select_dispatch_policy_task(
        tasks, dispatch_policy="res", predictive_share=share, reservation_fraction=0.25,
        reactive_override_slack_s=90.0, reservation_softening_alpha=0.0,
        predictive_selection_policy="utility", now_t=100.0,
        eta_seconds_fn=lambda tr: 5.0, rng=np.random.default_rng(0), reservation_mode=mode)


_REACT = {"id": 1, "type": "deterring", "mode": None, "x": 1.0, "y": 1.0, "time": 95.0}
_PRED = {"id": 2, "type": "deterring", "mode": "laser", "origin": "model_scored", "x": 5.0, "y": 5.0,
         "time": 99.0, "score": 3.0, "utility": 3.0}


def test_ceiling_never_forces_predictive_work():
    # floor: below rho the predictive task is served before the waiting reactive one
    assert _dispatch([_REACT, _PRED], 0.0, "floor")[0]["id"] == 2
    # ceiling: reactive keeps priority at any share
    for share in (0.0, 0.1, 0.24, 0.25, 0.9):
        assert _dispatch([_REACT, _PRED], share, "ceiling")[0]["id"] == 1


def test_ceiling_blocks_predictive_at_share_ge_rho():
    assert _dispatch([_PRED], 0.24, "ceiling")[0]["id"] == 2
    for share in (0.25, 0.3, 1.0):
        assert _dispatch([_PRED], share, "ceiling") == (None, False)
        assert _dispatch([_PRED], share, "floor")[0]["id"] == 2  # floor serves it anyway


def test_ceiling_rejected_for_other_policies():
    import DeterrentSystem as ds
    with pytest.raises(ValueError):
        ds._select_dispatch_policy_task(
            [_PRED], dispatch_policy="res-soft", predictive_share=0.0, reservation_fraction=0.25,
            reactive_override_slack_s=90.0, reservation_softening_alpha=0.0,
            predictive_selection_policy="utility", now_t=100.0,
            eta_seconds_fn=lambda tr: 5.0, rng=np.random.default_rng(0), reservation_mode="ceiling")


# ---------------------------------------------------------------------------
# Section 3 diagnostics (decision 27)
# ---------------------------------------------------------------------------
def _params(smooth=True, clauses=("exp", "cov", "hab")):
    return SpecParams(E_star=5.0, T_cov=1200.0, T_react=None, W=600.0, eta_min=0.4, horizon=300.0,
                      monitor_dt=30.0, theta=12.0, smooth=smooth, active_clauses=clauses)


def test_inactive_hab_entries_change_softmin_argument_count_and_score():
    """Plan Sec. 3: an action in cell 0 (eta 0.6 after application); cells 1, 2 have no
    action, so their hab entries are the vacuous eta = 1.  Including them changes the
    number of soft-min arguments of the hab clause and thereby the clause and spec score;
    under classical min the score does not change."""
    times = np.arange(11) * 30.0
    eta_act = np.where(times >= 60.0, 0.6, 1.0)
    sig = {"eta_0": eta_act, "eta_1": np.ones(11), "eta_2": np.ones(11),
           "e_0": np.full(11, 1.0), "e_1": np.full(11, 1.0), "e_2": np.full(11, 1.0),
           "g_0": times, "g_1": times, "g_2": times}
    tr = Trace(times, sig)
    for smooth in (True, False):
        p = _params(smooth=smooth, clauses=("hab",))
        one = clause_binding("hab", [0], tr, p)
        three = clause_binding("hab", [0, 1, 2], tr, p)
        assert (one["n_softmin_args"], three["n_softmin_args"]) == (11, 33)
        _, cl1 = build_spec([0], p)
        _, cl3 = build_spec([0, 1, 2], p)
        r1, r3 = robustness_at(cl1["hab"], tr, 0), robustness_at(cl3["hab"], tr, 0)
        assert one["value"] == pytest.approx(r1, abs=1e-12)
        assert three["value"] == pytest.approx(r3, abs=1e-12)
        if smooth:
            assert r3 < r1 - 1e-6  # extra inactive arguments lower the soft-min
        else:
            assert r3 == r1
        assert three["cell"] == 0 and three["t_s"] == 60.0
    # the spec score (conjunction of clauses) changes with the inactive entries too
    p = _params(smooth=True, clauses=("exp", "cov", "hab"))
    s1, _ = build_spec([0], p)
    s3, _ = build_spec([0, 1, 2], p)
    sig1 = {k: v for k, v in sig.items()}
    assert robustness_at(s1, Trace(times, sig1), 0) != robustness_at(s3, Trace(times, sig1), 0)


def test_identical_present_different_future_exposure_binding():
    """Same current exposure, different future exposure: the binding time of the
    exp clause is t = 0 for both, so the score is identical (the masking case)."""
    times = np.arange(11) * 30.0
    p = _params(smooth=False, clauses=("exp",))
    a = Trace(times, {"e_0": 8.0 * np.exp(-times / 600.0)})
    b = Trace(times, {"e_0": 8.0 * np.exp(-times / 100.0)})
    ba, bb = clause_binding("exp", [0], a, p), clause_binding("exp", [0], b, p)
    assert ba["t_index"] == bb["t_index"] == 0 and ba["value"] == bb["value"]


def test_robustness_breakdown_reports_binding_time_and_cell():
    hab = HabituationField(3, 2, T_rec=1800.0, kappa=0.5)
    states = {0: CellState(e0=2.0, g0=100.0), 1: CellState(e0=6.0, g0=1100.0), 2: CellState(e0=1.0, g0=10.0)}
    dyn = Dynamics(omega_e=600.0, omega_u=900.0, beta=(1.0, 1.0), forecast_correction=True)
    bd = robustness_breakdown((0, 1, 60.0), [0, 1, 2], states, hab, _params(), dyn)
    assert bd["binding_nom"]["exp"]["cell"] == 1 and bd["binding_nom"]["exp"]["t_index"] == 0
    assert bd["binding_nom"]["cov"]["cell"] == 1 and bd["binding_nom"]["cov"]["t_s"] == 300.0
    assert bd["binding_wa"]["hab"]["cell"] == 0
    for side, rho in (("binding_nom", bd["nom"]), ("binding_wa", bd["wa"])):
        for clause, info in bd[side].items():
            assert info["value"] == pytest.approx(rho[clause], abs=1e-12)
    assert bd["n_top_args"] == 3


def test_binding_log_written_on_sampled_decisions(tmp_path):
    path = tmp_path / "bind.jsonl"
    params = _ref_params(t_end=120.0, stl_forecast_correction=True,
                         stl_binding_log_path=str(path), stl_binding_log_fraction=1.0)
    m = _run(params)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows
    r = rows[0]
    for key in ("t", "robot", "binding_clause_nom", "binding_nom", "binding_wa", "U"):
        assert key in r
    assert set(r["binding_nom"]) == {"exp", "cov", "hab"}
    assert {"t_index", "t_s", "cell", "pred", "weight", "n_softmin_args"} <= set(r["binding_nom"]["exp"])
    # logging does not change the run
    m0 = _run(_ref_params(t_end=120.0, stl_forecast_correction=True))
    assert all(_same(v, m.get(k)) for k, v in m0.items()
               if isinstance(v, (int, float)) and k not in _RUNTIME_KEYS)
