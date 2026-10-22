"""Tests for habituation_stl.scenario_rollout (Monte Carlo B5 continuation rollouts)."""
import copy
import math
import os

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

from habituation_stl import scenario_rollout as sr  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures: a real B5 simulator state (paper configuration)
# ---------------------------------------------------------------------------
def _b5_params(mu, t_end=1800.0, seed=301):
    from experiments.run_plan_completion import build_params
    p = build_params("B5", True, mu, t_end)
    p["seed"] = seed
    return p


def _sim_locals(mu=2e-5, steps=100, seed=301, **over):
    import DeterrentSystem as ds
    p = _b5_params(mu, seed=seed)
    p.update(over)
    gen = ds.run_simulation_frames_persistent(**p)
    for _ in range(steps):
        next(gen)
    return gen, gen.gi_frame.f_locals


@pytest.fixture(scope="module")
def real_state():
    gen, L = _sim_locals(steps=100)
    snap = sr.snapshot_from_sim_locals(L, horizon_s=200.0)
    return gen, L, snap


def _quiet(snap, *, alpha=0.0, keep_robots=True):
    """Copy of a snapshot with deterministic, analytically tractable intensity."""
    s = copy.deepcopy(snap)
    s.forecast = sr.IntensityForecast(form="consistent", bg_node_rate=snap.forecast.bg_node_rate.copy(),
                                      alpha=alpha, sigma=snap.forecast.sigma, omega=snap.forecast.omega)
    s.recent_deterrences = []
    if not keep_robots:
        s.robots = []
        s.active_tasks = []
        s.pending_reactive = []
    return s


# ---------------------------------------------------------------------------
# common random numbers
# ---------------------------------------------------------------------------
def test_pi0_twice_identical_and_noop_gives_zero_U(real_state):
    _, _, snap = real_state
    a = sr.run_policy(snap, sr.NOOP, n_scenarios=3, seed=7)
    b = sr.run_policy(snap, sr.NOOP, n_scenarios=3, seed=7)
    for ra, rb in zip(a, b):
        assert ra["J"] == rb["J"]
        assert ra["counted_exposure"] == rb["counted_exposure"]
        assert ra["interventions"] == rb["interventions"]
    res = sr.evaluate(snap, [sr.Candidate(robot_id=None, label="do nothing")], n_scenarios=3, seed=7, n_workers=1)
    assert np.all(res.U == 0.0)
    assert np.all(res.J[0] == np.array([r["J"] for r in a]))


def test_parallel_matches_serial(real_state):
    _, _, snap = real_state
    r0 = snap.robots[0]
    cands = [sr.Candidate(r0.rid, r0.pose[0], r0.pose[1], "laser")]
    s1 = sr.evaluate(snap, cands, n_scenarios=2, seed=3, n_workers=1)
    s2 = sr.evaluate(snap, cands, n_scenarios=2, seed=3, n_workers=2)
    assert np.array_equal(s1.J, s2.J)


def test_live_state_and_snapshot_not_mutated(real_state):
    _, L, snap = real_state
    eta_live = L["planner_hab"].eta.copy()
    truth_live = L["truth_hab"].eta.copy()
    eta_snap = snap.habituation.eta.copy()
    n_rows = len(snap.taskgen._rows)
    n_active = len(snap.active_tasks)
    tq = list(L["truth_queue"])
    lam = {rid: r.m.lam.copy() for rid, r in L["robots"].items()}
    r0 = snap.robots[0]
    lam_snap = r0.planner.m.lam.copy()
    sr.evaluate(snap, [sr.Candidate(r0.rid, r0.pose[0] + 10, r0.pose[1], "formation")], n_scenarios=2, seed=1,
                n_workers=1)
    assert np.array_equal(L["planner_hab"].eta, eta_live)
    assert np.array_equal(L["truth_hab"].eta, truth_live)
    assert np.array_equal(snap.habituation.eta, eta_snap)
    assert len(snap.taskgen._rows) == n_rows and len(snap.active_tasks) == n_active
    assert list(L["truth_queue"]) == tq
    for rid, r in L["robots"].items():
        assert np.array_equal(r.m.lam, lam[rid])
    assert np.array_equal(r0.planner.m.lam, lam_snap)


# ---------------------------------------------------------------------------
# intensity integral
# ---------------------------------------------------------------------------
def test_zero_intensity_gives_zero_J(real_state):
    _, _, snap = real_state
    s = _quiet(snap)
    s.forecast.bg_node_rate = np.zeros_like(s.forecast.bg_node_rate)
    for r in sr.run_policy(s, sr.NOOP, n_scenarios=2, seed=0):
        assert r["J"] == 0.0 and r["counted_exposure"] == 0.0 and r["detections"] == 0


def test_background_only_J_matches_analytic(real_state):
    _, _, snap = real_state
    s = _quiet(snap, keep_robots=False)
    H = s.horizon_s
    expected = float(np.sum(s.w_bg_node * s.forecast.bg_node_rate)) * H
    res = sr.run_policy(s, sr.NOOP, n_scenarios=4, seed=2)
    for r in res:
        assert r["J"] == pytest.approx(expected, rel=1e-12)
    # counted exposure is an unbiased noisy estimate of the same quantity
    counted = np.array([r["counted_exposure"] for r in res])
    se = math.sqrt(expected * float(np.max(s.w_bg_node))) / math.sqrt(len(res))
    assert abs(counted.mean() - expected) < 4 * se


def test_self_exciting_J_matches_hawkes_mean():
    """Uniform weights, no suppression: E[J] = analytic Hawkes mean count (within MC error)."""
    nx, ny, W, H = 21, 21, 200.0, 200.0
    rate = np.full((ny, nx), 0.05 / (nx * ny))
    alpha, omega, horizon = 0.6, 60.0, 300.0
    snap = _bare_snapshot(nx, ny, W, H, rate, alpha=alpha, omega=omega, sigma=15.0, horizon=horizon)
    res = sr.run_policy(snap, sr.NOOP, n_scenarios=200, seed=11)
    J = np.array([r["J"] for r in res])
    mu_tot = float(rate.sum())
    a = 1.0 - alpha
    # bg arrives at integer steps 1..H; offspring rate integrated to H
    expected = mu_tot * (horizon + alpha / a * (horizon - omega / a * (1 - math.exp(-a * horizon / omega))))
    se = J.std(ddof=1) / math.sqrt(J.size)
    assert abs(J.mean() - expected) < 4 * se + 0.01 * expected


def _bare_snapshot(nx, ny, W, H, rate, *, alpha, omega, sigma, horizon):
    from TaskGenerator import TaskGenerator
    hab = sr.HabituationField(1, 4)
    return sr.RolloutSnapshot(
        t0=0.0, horizon_s=horizon, nx=nx, ny=ny, W=W, H=H, w_node=np.ones((ny, nx)), w_bg_node=np.ones((ny, nx)),
        region_mask=np.ones((ny, nx), bool),
        forecast=sr.IntensityForecast(form="consistent", bg_node_rate=rate, alpha=alpha, sigma=sigma, omega=omega),
        world_cues={"direct_detection": sr.CueParams(1.0, 20.0, 600.0)}, deterring_modes={}, habituation=hab,
        hab_cell_polys=[[(0, 0), (W, 0), (W, H), (0, H)]], mode_to_id={"direct_detection": 0},
        robots=[], active_tasks=[], completed_tasks=[], consumed_task_keys=set(), taskgen=TaskGenerator(),
        recent_deterrences=[], model_deterring_by_robot={}, next_tid=1, last_replan=0.0,
        bus_last_intervention_key_t={}, cfg=sr.B5Config(W=W, H=H), planner_weight_grid=np.ones((ny, nx)))


# ---------------------------------------------------------------------------
# intervention effects
# ---------------------------------------------------------------------------
def test_candidate_suppressing_hotspot_lowers_J(real_state):
    _, _, snap = real_state
    s = copy.deepcopy(snap)
    # a strong recent hotspot of known events in robot r1's zone
    r0 = s.robots[0]
    hx, hy = r0.pose[0] + 15.0, r0.pose[1]
    rng = np.random.default_rng(0)
    pts = np.column_stack([hx + rng.normal(0, 10, 60), hy + rng.normal(0, 10, 60), np.full(60, s.t0 - 5.0)])
    s.forecast.excitation_terms = pts
    res = sr.evaluate(s, [sr.Candidate(r0.rid, hx, hy, "formation")], n_scenarios=8, seed=5, n_workers=1)
    assert res.U_mean[0] > 2 * res.U_se[0] > 0
    for r in res.per_scenario[1]:
        assert math.isfinite(r["candidate_completed_t"])
        assert any(iv["candidate"] for iv in r["interventions"])


def test_cue_depletion_changes_later_b5_cue_choice(real_state):
    """Depleting the cue B5 would choose makes the same B5 rule pick another cue."""
    _, _, snap = real_state
    s = copy.deepcopy(snap)
    tree = sr._sample_scenario_tree(s, 0, 0)
    sims = [sr._Sim(s, tree, sr.NOOP, scenario=0, reactive_deadline_s=90.0) for _ in range(2)]
    # a hot spot at each zone centroid in that robot's own planner field
    for sim in sims:
        for rs in s.robots:
            cx, cy = sr._zone_centroid(rs.zone_polygon)
            for _ in range(30):
                sim.robots[rs.rid].m.add_local_event(cx, cy)
    t = s.t0 + 1.0
    sims[0].gen_log = []
    sr._b5_periodic_patrolling(sims[0], t)
    base = [(rid, cd) for (_t, rid, cands) in sims[0].gen_log for cd in cands if cd["predicted_deltaJ"] > 0]
    assert base, "a positive-value preventive seed is required"
    rid, cd = max(base, key=lambda it: it[1]["predicted_deltaJ"])
    cell = next(i for i, p in enumerate(s.hab_cell_polys) if sr.point_in_polygon(cd["x"], cd["y"], p))
    for _ in range(4):
        sims[1].hab.apply(cell, s.mode_to_id[cd["mode"]])
    sims[1].gen_log = []
    sr._b5_periodic_patrolling(sims[1], t)
    after = [c2 for (_t, r2, cands) in sims[1].gen_log if r2 == rid for c2 in cands
             if (c2["x"], c2["y"]) == (cd["x"], cd["y"])]
    assert after and after[0]["mode"] != cd["mode"]


def test_candidate_depletes_and_changes_rollout_cue_choice(real_state):
    """End to end: after the candidate's application the habituation copy is depleted."""
    _, _, snap = real_state
    r0 = snap.robots[0]
    res = sr.run_policy(snap, sr.Candidate(r0.rid, r0.pose[0], r0.pose[1], "formation"), n_scenarios=1, seed=0)[0]
    cand_iv = [iv for iv in res["interventions"] if iv["candidate"]]
    assert cand_iv and cand_iv[0]["mode"] == "formation"
    cell = next(i for i, p in enumerate(snap.hab_cell_polys) if sr.point_in_polygon(r0.pose[0], r0.pose[1], p))
    base = sr.run_policy(snap, sr.NOOP, n_scenarios=1, seed=0)[0]
    mid = snap.mode_to_id["formation"]
    assert res["terminal"]["habituation_eta"][cell, mid] < base["terminal"]["habituation_eta"][cell, mid]


# ---------------------------------------------------------------------------
# service outcomes
# ---------------------------------------------------------------------------
def test_unreachable_pending_tasks_have_infinite_completion(real_state):
    _, _, snap = real_state
    s = copy.deepcopy(snap)
    s.horizon_s = 5.0
    far = (s.W - 1.0, s.H - 1.0) if s.robots[0].pose[0] < s.W / 2 else (1.0, 1.0)
    row = {"robot_id": s.robots[0].rid, "type": "deterring", "x": far[0], "y": far[1], "time": s.t0,
           "origin": "detection", "score": 0.0}
    s.taskgen._add(row)
    key = sr._Sim(s, sr._sample_scenario_tree(s, 0, 0), sr.NOOP, scenario=0, reactive_deadline_s=90.0)._buffer_key(
        s.taskgen._rows[-1])
    s.pending_reactive.append(sr.PendingReactive(key=key, x=far[0], y=far[1], created_t=s.t0,
                                                 deadline_t=s.t0 + 90.0, assigned_robot=None, active_task_id=None))
    res = sr.run_policy(s, sr.NOOP, n_scenarios=2, seed=0)
    for r in res:
        assert math.isinf(r["pending_completion"][key]["completed_t"])
        assert not r["pending_completion"][key]["on_time"]


def test_reactive_tasks_generated_from_simulated_detections(real_state):
    _, _, snap = real_state
    s = copy.deepcopy(snap)
    s.cfg = copy.deepcopy(s.cfg)
    s.cfg.bird_detection_prob = 1.0
    s.forecast.bg_node_rate = s.forecast.bg_node_rate * 5.0
    res = sr.run_policy(s, sr.NOOP, n_scenarios=1, seed=4)[0]
    assert res["detections"] > 0
    assert len(res["new_reactive"]) > 0
    done = [n for n in res["new_reactive"] if math.isfinite(n["completed_t"])]
    assert done, "some simulated reactive tasks should be served within the horizon"
    for n in done:
        assert n["completed_t"] > n["created_t"]


# ---------------------------------------------------------------------------
# fidelity of the vectorised TaskGenerator port
# ---------------------------------------------------------------------------
def _real_generation(sim, now_t, L):
    from planner_task_extraction import run_task_location_estimation
    c = sim.cfg
    run_task_location_estimation(
        taskgen=sim.taskgen, robots=sim.robots, now_t=now_t, enable_patrolling=True,
        enable_predictive_patrol_tasks=True, include_fallback_patrol=True, enable_model_scored_deterring=True,
        model_deterring_window_s=c.model_deterring_window_s, model_deterring_risk_threshold=c.model_deterring_risk_threshold,
        model_deterring_risk_scale=c.model_deterring_risk_scale, model_deterring_min_recent_points=c.model_deterring_min_recent_points,
        model_deterring_field_threshold=None, model_deterring_min_persistence_replans=c.model_deterring_min_persistence_replans,
        model_deterring_persistence_max_gap_s=c.model_deterring_persistence_max_gap_s,
        model_deterring_score_margin=c.model_deterring_score_margin,
        model_deterring_repeat_block_window_s=c.model_deterring_repeat_block_window_s,
        model_deterring_repeat_block_radius_m=c.model_deterring_repeat_block_radius_m,
        model_deterring_max_eta_s=c.model_deterring_max_eta_s,
        model_deterring_busy_min_support_override=c.model_deterring_busy_min_support_override,
        model_deterring_busy_risk_override=c.model_deterring_busy_risk_override, enable_predicted_deltaJ_gate=False,
        min_predicted_deltaJ_for_model_deterring=0.0, model_deterring_gate_policy="heuristic",
        model_deterring_sprt_alpha=c.model_deterring_sprt_alpha, model_deterring_sprt_beta=c.model_deterring_sprt_beta,
        model_deterring_sprt_patch_radius_m=c.model_deterring_sprt_patch_radius_m, model_deterring_min_sprt_margin=1.25,
        model_deterring_chance_threshold=0.35, model_deterring_min_deltaJ_per_cost=1e5,
        model_deterring_min_selection_weight=0.25, preventive_capacity_remaining_by_robot={},
        preventive_capacity_ready_by_robot={}, task_replan_period_s=c.task_replan_period_s,
        busy_deterring_robots=sr.current_busy_deterring_robots(sim.active_tasks),
        recent_deterrences=list(sim.recent_deterrences), profiles=sim.profiles,
        use_live_robot_pose_for_task_planning=True, pose=sim.pose, rng=np.random.default_rng(0),
        patrol_hotspot_filter_mode="percentile", patrol_hotspot_score_percentile=97.0, patrol_hotspot_keep_top_k=None,
        patrol_feedback_inhibition_retention=1.0, patrol_scoring_mode="shared_response_reduction",
        patrol_shared_detection_range_m=c.detect_range_m, patrol_shared_detection_prob_per_step=c.bird_detection_prob,
        patrol_shared_detection_dwell_s=c.bird_stay_mean_s, patrol_shared_followup_success_prob=0.75,
        patrol_shared_response_eta_decay_s=max(c.bird_stay_mean_s, c.task_replan_period_s, 1.0),
        enable_predictive_lead_time=True, predictive_timing_mode="synthetic", predictive_lead_time_min_s=30.0,
        predictive_lead_time_max_eta_s=120.0, predictive_lead_time_buffer_s=15.0, predictive_lead_time_risk_power=1.0,
        forecast_horizon_s=c.forecast_horizon_s, value_weight_fn=L["value_weight"], deterring_modes=sim.deterring_modes,
        travel_time_fn=None, predictive_utility_mode="legacy_habituation", predictive_fixed_deterring_mode=None,
        stl_hab=sim.hab, stl_cell_polys=sim.snap.hab_cell_polys, stl_mode_to_id=sim.snap.mode_to_id,
        stl_cell_id_for_xy_fn=lambda x, y: next((i for i, p in enumerate(sim.snap.hab_cell_polys)
                                                 if p and sr.point_in_polygon(float(x), float(y), p)), None),
    )


_CMP_KEYS = ("robot_id", "type", "origin", "mode", "time", "support", "persistence", "predictive_opportunity_key",
             "x", "y", "score", "utility", "predicted_deltaJ", "deltaJ_per_cost", "p_event", "risk_conf", "eta_s",
             "cost_eta", "habituation_eta_at_plan", "forecast_event_time", "required_arrival_by_t")


@pytest.mark.parametrize("mu,steps", [(2e-5, 100), (2e-5, 400), (4e-4, 140)])
def test_generation_port_matches_taskgenerator(mu, steps):
    gen, L = _sim_locals(mu=mu, steps=steps, seed=303)
    snap = sr.snapshot_from_sim_locals(L, horizon_s=60.0)
    snap.cfg.jitter_m = 0.0
    tree = sr._sample_scenario_tree(snap, 0, 0)
    for k in range(3):
        now_t = snap.t0 + 1.0 + 45.0 * k
        a = sr._Sim(snap, tree, sr.NOOP, scenario=0, reactive_deadline_s=90.0)
        b = sr._Sim(snap, tree, sr.NOOP, scenario=0, reactive_deadline_s=90.0)
        for sim in (a, b):  # push the planners forward so persistence states differ between rounds
            for rob in sim.robots.values():
                rob.advance_time(now_t - rob.m.t_now)
        n0 = len(a.taskgen._rows)
        _real_generation_nojitter(a, now_t, L)
        sr._b5_periodic_patrolling(b, now_t)
        ra, rb = a.taskgen._rows[n0:], b.taskgen._rows[n0:]
        assert len(ra) == len(rb)
        for x, y in zip(ra, rb):
            for key in _CMP_KEYS:
                va, vb = x.get(key), y.get(key)
                if isinstance(va, float) and isinstance(vb, float) and (math.isfinite(va) or math.isfinite(vb)):
                    assert va == pytest.approx(vb, rel=1e-9, abs=1e-12), key
                elif isinstance(va, float) and isinstance(vb, float):
                    assert math.isnan(va) == math.isnan(vb), key
                else:
                    assert va == vb, key
        assert a.taskgen._deterring_forecast_state.keys() == b.taskgen._deterring_forecast_state.keys()
        assert a.taskgen._deterring_cluster_state.keys() == b.taskgen._deterring_cluster_state.keys()
        assert a.taskgen._next_allowed == b.taskgen._next_allowed
        snap.taskgen = b.taskgen  # carry persistence into the next round


def _real_generation_nojitter(sim, now_t, L):
    """Run the real TaskGenerator with jitter_m=0 (its signature default is 4 m)."""
    import TaskGenerator as TG
    orig = TG.TaskGenerator.periodic_patrolling

    def patched(self, *args, **kw):
        kw["jitter_m"] = 0.0
        return orig(self, *args, **kw)

    TG.TaskGenerator.periodic_patrolling = patched
    try:
        _real_generation(sim, now_t, L)
    finally:
        TG.TaskGenerator.periodic_patrolling = orig


# ---------------------------------------------------------------------------
# agreement with real B5 runs (light version; full study in
# experiments/run_scenario_rollout_agreement.py)
# ---------------------------------------------------------------------------
def test_agreement_with_real_b5_windows():
    import DeterrentSystem as ds
    H = 150.0
    z_J, z_c = [], []
    for seed in (311, 312):
        p = _b5_params(2e-5, t_end=700.0, seed=seed)
        gen = ds.run_simulation_frames_persistent(**p)
        snaps = []
        last = None
        for fr in gen:
            L = gen.gi_frame.f_locals
            t = float(L["t"])
            if t in (100.0, 300.0, 500.0):
                snaps.append(sr.snapshot_from_sim_locals(L, horizon_s=H))
            last = L
            if t >= 650.0:
                break
        log = list(last["exposure_event_log"])
        for snap in snaps:
            real = sum(w for (te, w) in log if snap.t0 < te <= snap.t0 + H)
            res = sr.run_policy(snap, sr.NOOP, n_scenarios=16, seed=seed)
            J = np.array([r["J"] for r in res])
            cnt = np.array([r["counted_exposure"] for r in res])
            sd = cnt.std(ddof=1)
            z_J.append((real - J.mean()) / sd)
            z_c.append((real - cnt.mean()) / sd)
    z_J = np.array(z_J)
    # each real window is one draw from the predicted distribution: z ~ N(0, 1)
    assert np.all(np.abs(z_J) < 4.0)
    assert abs(z_J.mean()) < 4.0 / math.sqrt(z_J.size) + 0.5


# ---------------------------------------------------------------------------
# Section 6 decisions (2026-10-21)
# ---------------------------------------------------------------------------
def _hotspot(snap):
    s = copy.deepcopy(snap)
    r0 = s.robots[0]
    hx, hy = r0.pose[0] + 15.0, r0.pose[1]
    rng = np.random.default_rng(0)
    pts = np.column_stack([hx + rng.normal(0, 10, 60), hy + rng.normal(0, 10, 60), np.full(60, s.t0 - 5.0)])
    s.forecast.excitation_terms = pts
    return s, sr.Candidate(r0.rid, hx, hy, "formation")


def test_one_intervention_counterfactual_isolates_the_candidate(real_state):
    """Decision 8: arm 0 is the world with no future intervention, arm a adds only the
    candidate's suppression at its application time; neither depends on the B5
    continuation (removing every task leaves arm 0 unchanged)."""
    _, _, snap = real_state
    s, cand = _hotspot(snap)
    res = sr.evaluate(s, [cand], n_scenarios=3, seed=5, n_workers=1, one_intervention=True)
    assert res.J_one.shape == (2, 3)
    assert np.array_equal(res.U_one, res.J_one[0][None, :] - res.J_one[1:])
    bare = copy.deepcopy(s)
    bare.active_tasks = []
    bare.pending_reactive = []
    row = sr._Sim(s, sr._sample_scenario_tree(s, 5, 0), cand, scenario=0, reactive_deadline_s=90.0)._candidate_row
    for k in range(3):
        tree = sr._sample_scenario_tree(s, 5, k)
        assert res.J_one[0, k] == sr.one_intervention_J(s, tree, None)
        assert res.J_one[0, k] == sr.one_intervention_J(bare, tree, None)
        t_a = res.per_scenario[1][k]["candidate_completed_t"]
        assert math.isfinite(t_a)
        assert res.J_one[1, k] == sr.one_intervention_J(s, tree, row, t_apply=t_a, robot_id=cand.robot_id)
        assert res.U_one[0, k] > 0.0
    assert np.all(res.U_one_mean > 0)


def test_terminal_summary_per_scenario(real_state):
    """Decision 30: unfinished tasks by stream, uncompleted reactive work, residual rate, busy robots."""
    _, _, snap = real_state
    r = sr.run_policy(snap, sr.NOOP, n_scenarios=1, seed=2)[0]
    ts = r["terminal_summary"]
    assert set(ts["unfinished_by_stream"]) >= {"reactive", "predictive", "deviation"}
    assert sum(ts["unfinished_by_stream"].values()) == len(r["terminal"]["unfinished_tasks"])
    unc = sum(1 for v in r["pending_completion"].values() if math.isinf(v["completed_t"])) + \
        sum(1 for v in r["new_reactive"] if math.isinf(v["completed_t"]))
    assert ts["reactive_uncompleted"] == unc
    assert ts["residual_exposure_rate"] == r["terminal"]["residual_exposure_rate"]
    busy = {u["assigned"] for u in r["terminal"]["unfinished_tasks"] if u["assigned"]}
    assert ts["robots_busy"] == len(busy) <= len(snap.robots)
    slim = sr._slim_result(r)
    for k in ("terminal_summary", "candidate_arrival_t", "candidate_eta_planner", "J_one"):
        assert k in slim


def test_candidate_arrival_and_q_hat_at_application_recorded(real_state):
    """Decisions 13 and 26: the candidate's arrival (hold start) and planner q_hat at application."""
    _, _, snap = real_state
    r0 = snap.robots[0]
    r = sr.run_policy(snap, sr.Candidate(r0.rid, r0.pose[0], r0.pose[1], "formation"), n_scenarios=1, seed=0)[0]
    iv = next(iv for iv in r["interventions"] if iv["candidate"])
    assert r["candidate_eta_planner"] == iv["eta_planner"]
    assert snap.t0 < r["candidate_arrival_t"] <= r["candidate_completed_t"]


def test_restrict_snapshot_to_information(real_state):
    """Decision 17: with no restriction the snapshot is equivalent (shared mode unchanged);
    each restriction replaces only its part."""
    _, _, snap = real_state
    same = sr.restrict_snapshot_to_information(snap)
    a = sr.run_policy(snap, sr.NOOP, n_scenarios=2, seed=4)
    b = sr.run_policy(same, sr.NOOP, n_scenarios=2, seed=4)
    assert [r["J"] for r in a] == [r["J"] for r in b]
    eff = snap.habituation.copy()
    eff.eta[:] = 0.3
    eta0 = snap.habituation.eta.copy()
    ids = {tr.get("id") for tr in snap.active_tasks[:1]}
    r = sr.restrict_snapshot_to_information(snap, effectiveness=eff, received_interventions=[],
                                            known_task_ids=ids, known_pending_keys=set())
    assert np.all(r.habituation.eta == 0.3) and np.array_equal(snap.habituation.eta, eta0)
    assert r.recent_deterrences == [] and r.pending_reactive == []
    assert [tr.get("id") for tr in r.active_tasks] == [tr.get("id") for tr in snap.active_tasks[:1]]
