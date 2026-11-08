"""Paper Eq. 20 in the legacy rollout world and the legacy stamp-unit flag (2026-10-27).

* Eq. 20: the legacy forecast world advances the existing excitation by passive decay
  only; accepted rollout events stamp offspring only with legacy_future_offspring=True.
* legacy_stamp_units: "density" (historical, bit for bit) reads a stamp amp * G
  (sum G = 1) as a density; "mass_per_cell" stores amp * G / (dx * dy), so one
  detection integrates to alpha_in * omega future events instead of alpha_in * A * omega.
"""
import copy
import math
import os

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

from SESTPP import OnlineSESTPP, canonical_legacy_stamp_units, legacy_stamp_scale  # noqa: E402
from habituation_stl import scenario_rollout as sr  # noqa: E402
from planner_task_estimation import estimate_counterfactual_reduction  # noqa: E402

W, H, NX, NY = 500.0, 500.0, 60, 48
DX, DY = W / (NX - 1), H / (NY - 1)
A = DX * DY


def _model(units="density", **kw):
    p = dict(sigma=10.0, omega=450.0, omega_inhib=900.0, alpha_in=0.15, alpha_cross=0.0,
             alpha_inhib=0.9, mu_base=2.5e-5, bg_ema=1e-7)
    p.update(kw)
    return OnlineSESTPP(0.0, W, 0.0, H, NX, NY, legacy_stamp_units=units, **p)


# ---------------------------------------------------------------------------
# flag plumbing
# ---------------------------------------------------------------------------
def test_flag_values_and_default():
    assert canonical_legacy_stamp_units(None) == "density"
    assert canonical_legacy_stamp_units(" Mass_Per_Cell ") == "mass_per_cell"
    with pytest.raises(ValueError):
        canonical_legacy_stamp_units("mass")
    assert _model().legacy_stamp_units == "density"
    assert legacy_stamp_scale(_model()) == 1.0
    assert legacy_stamp_scale(_model("mass_per_cell")) == 1.0 / A


def test_density_flag_is_the_historical_stamp_bit_for_bit():
    """Old value: grid += amp * G exactly as before (manual reimplementation)."""
    m = _model()
    m.add_local_event(250.0, 250.0)
    m.add_intervention_event(240.0, 255.0, weight=1.8, sigma=40.0, omega_inhib=1200.0, mode="laser")
    ref_T = np.zeros((NY, NX))
    ref_I = np.zeros((NY, NX))
    sr._stamp(ref_T, *m.world_to_idx(250.0, 250.0), 0.15, *m._build_kernel(10.0))
    rad, k = m._build_kernel(40.0)
    sr._stamp(ref_I, *m.world_to_idx(240.0, 255.0), 0.9 * 1.8, rad, k)
    assert np.array_equal(m.trigger_mass, ref_T)
    assert np.array_equal(m.inhib_channels["laser"], ref_I)


def test_mass_per_cell_divides_trigger_and_inhibition_stamps_by_node_area():
    old, new = _model(), _model("mass_per_cell")
    for m in (old, new):
        m.add_local_event(250.0, 250.0)
        m.add_cross_event(100.0, 120.0, weight=0.7)
        m.add_intervention_event(240.0, 255.0, weight=1.8, sigma=40.0, omega_inhib=1200.0, mode="laser")
    np.testing.assert_allclose(new.trigger_mass, old.trigger_mass / A, rtol=1e-12, atol=0)
    np.testing.assert_allclose(new.inhib_channels["laser"], old.inhib_channels["laser"] / A, rtol=1e-12, atol=0)
    np.testing.assert_allclose(new.inhib_mass, old.inhib_mass / A, rtol=1e-12, atol=0)


def test_per_detection_integral_is_alpha_in_omega_with_mass_per_cell():
    """Space-time integral of one interior detection's excitation density."""
    for units, expected in (("density", 0.15 * A * 450.0), ("mass_per_cell", 0.15 * 450.0)):
        m = _model(units)
        m.add_local_event(250.0, 250.0)
        integral = float(np.sum(m.trigger_mass)) * A * m.omega
        assert integral == pytest.approx(expected, rel=1e-12)


# ---------------------------------------------------------------------------
# consumers that stamp with the model kernel themselves
# ---------------------------------------------------------------------------
def _primed(units):
    m = _model(units)
    for k in range(6):
        m.add_local_event(240.0 + 3 * k, 250.0 - 2 * k)
    m.add_intervention_event(230.0, 260.0, weight=1.2, sigma=72.0, omega_inhib=2400.0, mode="formation")
    return m


def test_counterfactual_reduction_new_units_equals_old_units_with_scaled_amplitude():
    """mass_per_cell == density with every stamp amplitude divided by A (alpha_in, alpha_inhib)."""
    new = _primed("mass_per_cell")
    ref = _model("density", alpha_in=0.15 / A, alpha_inhib=0.9 / A)
    for k in range(6):
        ref.add_local_event(240.0 + 3 * k, 250.0 - 2 * k)
    ref.add_intervention_event(230.0, 260.0, weight=1.2, sigma=72.0, omega_inhib=2400.0, mode="formation")
    np.testing.assert_allclose(new.lam, ref.lam, rtol=1e-10, atol=1e-18)
    kw = dict(beta_u=1.8, sigma_u=40.0, omega_u=1200.0, horizon_s=300.0)
    a = estimate_counterfactual_reduction(new, 245.0, 248.0, **kw)
    b = estimate_counterfactual_reduction(ref, 245.0, 248.0, **kw)
    assert a["predicted_reduction_raw"] == pytest.approx(b["predicted_reduction_raw"], rel=1e-9)
    assert a["suppression_amplitude"] == pytest.approx(0.9 * 1.8 / A, rel=1e-12)
    # vectorised port (B5 in the plan rollouts) agrees with the scalar estimator
    base = new.mu * new.time_multiplier(new.t_now)
    avail = np.clip(new.lam - base, 0.0, None) * new.omega * (1.0 - math.exp(-300.0 / new.omega))
    fast = sr.fast_counterfactual_reduction(new, 245.0, 248.0, beta_u=1.8, sigma_u=40.0, omega_u=1200.0,
                                            horizon_s=300.0, mask_grid=None, weight_grid=np.ones((NY, NX)),
                                            available_integral_grid=avail)
    slow = estimate_counterfactual_reduction(new, 245.0, 248.0, weight_fn=lambda x, y: 1.0, **kw)
    assert fast == pytest.approx(slow["predicted_reduction_raw"], rel=1e-9)


def test_counterfactual_reduction_density_flag_unchanged():
    m = _primed("density")
    r = estimate_counterfactual_reduction(m, 245.0, 248.0, beta_u=1.8, sigma_u=40.0, omega_u=1200.0,
                                          horizon_s=300.0)
    assert r["suppression_amplitude"] == 0.9 * 1.8


# ---------------------------------------------------------------------------
# rollout world: paper Eq. 20 and units
# ---------------------------------------------------------------------------
def _legacy_snapshot(model, *, horizon=300.0, future=False, units=None, stage="replan", t0=3600.0):
    from TaskGenerator import TaskGenerator
    hab = sr.HabituationField(1, 4)
    fc = sr.IntensityForecast(
        form="legacy", bg_node_rate=np.array(model.mu, float), sigma=model.sigma, omega=model.omega,
        legacy_trigger_mass=np.array(model.trigger_mass, float), legacy_inhib_channels={},
        legacy_alpha_in=model.alpha_in, legacy_alpha_inhib=model.alpha_inhib,
        legacy_future_offspring=future,
        legacy_stamp_units=model.legacy_stamp_units if units is None else units)
    wbg = np.ones((NY, NX))
    return sr.RolloutSnapshot(
        t0=t0, horizon_s=horizon, nx=NX, ny=NY, W=W, H=H, w_node=wbg.copy(), w_bg_node=wbg,
        region_mask=np.ones((NY, NX), bool), forecast=fc,
        world_cues={"direct_detection": sr.CueParams(1.0, 20.0, 600.0)}, deterring_modes={}, habituation=hab,
        hab_cell_polys=[[(0, 0), (W, 0), (W, H), (0, H)]], mode_to_id={"direct_detection": 0},
        robots=[], active_tasks=[], completed_tasks=[], consumed_task_keys=set(), taskgen=TaskGenerator(),
        recent_deterrences=[], model_deterring_by_robot={}, next_tid=1, last_replan=t0,
        bus_last_intervention_key_t={}, cfg=sr.B5Config(W=W, H=H), planner_weight_grid=wbg.copy(),
        start_stage=stage)


def _passive_J(snap):
    """Exact discrete passive integral of the legacy world (no new trigger stamps)."""
    fc = snap.forecast
    dt = float(snap.cfg.dt)
    n = int(round(snap.horizon_s / dt))
    mu_sum = float(np.sum(snap.w_bg_node * fc.bg_node_rate))
    T_sum = float(np.sum(snap.w_bg_node * fc.legacy_trigger_mass))
    off = 0 if snap.start_stage == "replan" else 1
    J = 0.0
    for k in range(1, n + 1):
        t = snap.t0 + k * dt
        J += (mu_sum * sr.sestpp_time_multiplier(t) + T_sum * math.exp(-(k - off) * dt / fc.omega)) * A * dt
    return J, mu_sum, T_sum


@pytest.mark.parametrize("units", ["density", "mass_per_cell"])
@pytest.mark.parametrize("stage", ["replan", "truth"])
def test_strict_eq20_J0_equals_analytic_passive_integral(units, stage):
    m = _model(units)
    for k in range(8):
        m.add_local_event(200.0 + 9 * k, 260.0 - 5 * k)
    snap = _legacy_snapshot(m, units=units, stage=stage)
    expected, mu_sum, T_sum = _passive_J(snap)
    res = sr.run_policy(snap, sr.NOOP, n_scenarios=3, seed=5)
    for r in res:
        assert r["J"] == pytest.approx(expected, rel=1e-12)
    # continuous form: background + M * omega * (1 - e^{-H/omega}), up to the step quadrature
    Hh, om = snap.horizon_s, m.omega
    shift = 1.0 if stage == "replan" else 0.0
    cont_trig = T_sum * A * om * (1.0 - math.exp(-Hh / om)) * math.exp(-shift / om)
    bg = sum(mu_sum * sr.sestpp_time_multiplier(snap.t0 + k) for k in range(1, int(Hh) + 1)) * A
    assert expected == pytest.approx(bg + cont_trig, rel=1.0 / om)
    # trigger part of J: one detection integrates to alpha_in * omega (mass_per_cell)
    # or alpha_in * A * omega (density) over an unbounded horizon
    per_det = 0.15 * om * (1.0 if units == "mass_per_cell" else A)
    assert T_sum * A * om == pytest.approx(8 * per_det, rel=1e-9)


def test_rollout_events_stamp_offspring_only_with_legacy_future_offspring():
    m = _model("mass_per_cell", mu_base=4e-4)
    for k in range(8):
        m.add_local_event(200.0 + 9 * k, 260.0 - 5 * k)
    strict = _legacy_snapshot(m, horizon=120.0, future=False)
    expected, _, _ = _passive_J(strict)
    tree = sr._sample_scenario_tree(strict, 5, 0)
    assert tree.t.size > 0                    # events exist (background + trigger-born)
    for r in sr.run_policy(strict, sr.NOOP, n_scenarios=2, seed=5):
        assert r["J"] == pytest.approx(expected, rel=1e-12)
    # direct check on the world: an accepted event leaves T unchanged unless future offspring
    for future in (False, True):
        snap = _legacy_snapshot(m, horizon=120.0, future=future)
        world = sr._World(snap, [])
        T0 = world.T.copy()
        ids = np.arange(min(3, tree.t.size))
        world.add_accepted(tree, ids, snap.t0 + 1.0)
        assert world.counted > 0.0            # counted exposure is still accumulated
        if future:
            added = float(np.sum(world.T - T0))
            assert added > 0.0
            # each stamp is alpha_in / A of in-bounds kernel mass (mass_per_cell)
            assert added <= ids.size * 0.15 / A * (1 + 1e-12)
        else:
            assert np.array_equal(world.T, T0)


def test_density_future_offspring_stamp_is_historical():
    m = _model("density")
    m.add_local_event(250.0, 250.0)
    snap = _legacy_snapshot(m, horizon=60.0, future=True)
    # tree from the Eq. 20 world (density offspring trees are supercritical, 2026-10-16)
    tree = sr._sample_scenario_tree(_legacy_snapshot(m, horizon=60.0, future=False), 1, 0)
    world = sr._World(snap, [])
    T0 = world.T.copy()
    ids = np.arange(min(2, tree.t.size))
    world.add_accepted(tree, ids, snap.t0 + 1.0)
    ref = T0.copy()
    for n in tree.node[ids]:
        iy, ix = divmod(int(n), NX)
        sr._stamp(ref, iy, ix, 0.15, world.krad, world.kern)
    assert np.array_equal(world.T, ref)


@pytest.mark.parametrize("units", ["density", "mass_per_cell"])
def test_rollout_inhibition_stamp_matches_live_model(units):
    """The planner world's inhibition stamp equals what the live estimator stores."""
    m = _model(units)
    snap = _legacy_snapshot(m, horizon=30.0)
    world = sr._World(snap, [])
    world.add_legacy_inhibition(230.0, 260.0, "formation", 1.2, 72.0, 2400.0)
    m.add_intervention_event(230.0, 260.0, weight=1.2, sigma=72.0, omega_inhib=2400.0, mode="formation")
    assert np.array_equal(world.I["formation"][0], m.inhib_channels["formation"])


def test_forecast_builder_carries_units_and_rejects_mixed_models():
    a, b = _model("mass_per_cell"), _model("mass_per_cell")
    assert sr._model_stamp_units([a, b]) == "mass_per_cell"
    with pytest.raises(ValueError):
        sr._model_stamp_units([a, _model("density")])


def test_eq3_candidate_stamp_is_in_model_units():
    """Eq. 3 (C, C_gate): the candidate stamp alpha_inhib * q * beta * K is divided by A
    with mass_per_cell, i.e. equals the density model with alpha_inhib / A."""
    from habituation_stl.habituation import HabituationField
    from habituation_stl.mission_spec import SpecParams
    from habituation_stl.task_value import Dynamics
    from planner_task_estimation import eq3_counterfactual_value

    def build(units, alpha_inhib):
        m = OnlineSESTPP(0.0, 60.0, 0.0, 60.0, 7, 7, sigma=10.0, omega=500.0, omega_inhib=700.0,
                         alpha_inhib=alpha_inhib, mu_base=2e-3, legacy_stamp_units=units)
        rng = np.random.default_rng(4)
        m.mu = rng.uniform(1e-3, 3e-3, size=(7, 7))
        m.trigger_mass = rng.uniform(0.0, 4e-3, size=(7, 7))
        m._update_lambda()
        return m

    a10 = (60.0 / 6) ** 2
    cells = [[(0, 0), (30, 0), (30, 60), (0, 60)], [(30, 0), (60, 0), (60, 60), (30, 60)]]
    hab = HabituationField(2, 2, T_rec=900.0, kappa=0.5)
    sp = SpecParams(horizon=40.0, active_clauses=("exp", "cov", "hab"))
    dyn = Dynamics(omega_e=500.0, omega_u=700.0, beta=(0.5, 0.8), forecast_correction=True,
                   valuation_mode="integrated_exposure_eq3", eq3_dt_s=1.0)
    common = dict(cells=[0, 1], cell_polys=cells, weight_fn=None, hab=hab, spec_params=sp, dynamics=dyn,
                  target_cell_id=1, mode_id=1, completion_lead_s=7.0, now_t=0.0, cue_sigma=8.0,
                  cue_omega=300.0, pending_events=[], dt=1.0)
    new = eq3_counterfactual_value(build("mass_per_cell", 30.0), 32.0, 25.0, **common)
    ref = eq3_counterfactual_value(build("density", 30.0 / a10), 32.0, 25.0, **common)
    old = eq3_counterfactual_value(build("density", 30.0), 32.0, 25.0, **common)
    assert new["amp"] == pytest.approx(old["amp"] / a10, rel=1e-12)
    assert new["U"] == pytest.approx(ref["U"], rel=1e-9)
    assert 0.0 < new["U"] < old["U"]


def test_simulator_threads_flag_to_every_legacy_estimator():
    import DeterrentSystem as ds
    from experiments.run_plan_completion import build_params
    p = build_params("B5", True, 1e-4, 30.0)
    p["seed"] = 201
    p["legacy_stamp_units"] = "mass_per_cell"
    gen = ds.run_simulation_frames_persistent(**p)
    for _ in range(5):
        next(gen)
    L = gen.gi_frame.f_locals
    assert {r.m.legacy_stamp_units for r in L["robots"].values()} == {"mass_per_cell"}
    fc, _ = sr.planner_forecast_from_sim_locals(L, t0=5.0, horizon_s=30.0)
    assert fc.legacy_stamp_units == "mass_per_cell"
    gen.close()
    p["legacy_stamp_units"] = "grams"
    with pytest.raises(ValueError):
        next(ds.run_simulation_frames_persistent(**p))
