"""Unit-fix round (user decisions 2026-10-28 A, B, C, H).

A  PLAN_ENV carries legacy_stamp_units="mass_per_cell" for every evaluated variant, A
   included; A_legacy_units = A on the old setting (old units, old constants and
   thresholds); the ACC reproduction (LEGACY_VARIANTS) stays on the old setting.
B  Excess fields use lam - mu * m(t_now) under "mass_per_cell" and stay lam - mu bit for
   bit under "density".
C  The rollout B5 copy reads cost_w_eta, the patrol cost-weight override and
   deterring_cost_multiplier from the same simulator parameters as the live B5.
"""
import json
import math
import os
import re
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import experiments.run_plan_completion as rpc  # noqa: E402
from SESTPP import (  # noqa: E402
    ConsistentOnlineSESTPP, OnlineSESTPP, excess_at, excess_baseline_grid, excess_field,
)
from habituation_stl import scenario_rollout as sr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W, H, NX, NY = 500.0, 500.0, 60, 48
MU = 1e-4
OLD_PLAN_ENV = {"estimator_mode": "legacy", "random_stream_mode": "coupled",
                "truth_deterrence_memory": "complete", "stl_forecast_correction": True}


def _diff(a: dict, b: dict) -> set:
    return {k for k in set(a) | set(b) if a.get(k, "<absent>") != b.get(k, "<absent>")}


def _model(units, t_now=0.0):
    m = OnlineSESTPP(0.0, W, 0.0, H, NX, NY, sigma=10.0, omega=450.0, omega_inhib=900.0, alpha_in=0.15,
                     alpha_cross=0.0, alpha_inhib=0.9, mu_base=2.5e-5, bg_ema=1e-7, legacy_stamp_units=units)
    rng = np.random.default_rng(3)
    m.mu = rng.uniform(1e-5, 5e-5, size=(NY, NX))
    for k in range(5):
        m.add_local_event(120.0 + 40 * k, 300.0 - 25 * k)
    m.add_intervention_event(200.0, 250.0, weight=1.4, sigma=40.0, omega_inhib=1200.0, mode="laser")
    m.advance_time(t_now)
    return m


# ---------------------------------------------------------------------------
# A: variants and PLAN_ENV
# ---------------------------------------------------------------------------
def test_plan_env_has_mass_per_cell_and_every_eval_variant_uses_it():
    assert rpc.PLAN_ENV["legacy_stamp_units"] == "mass_per_cell"
    for v in rpc.VARIANTS:
        p = rpc.build_params(v, True, MU, None)
        assert p["legacy_stamp_units"] == ("density" if v == "A_legacy_units" else "mass_per_cell"), v


def test_acc_reproduction_stays_on_old_setting():
    for v in rpc.LEGACY_VARIANTS:
        p = rpc.build_params(v, True, MU, None)
        assert p.get("legacy_stamp_units", "density") == "density", v
    import inspect
    import DeterrentSystem as ds
    assert inspect.signature(ds.run_simulation_frames_persistent).parameters["legacy_stamp_units"].default == "density"


def test_acc_extra_comparators_preserve_the_paper_definitions_and_plan_environment():
    b2 = rpc.build_params('B2_c', True, MU, None)
    b3 = rpc.build_params('B3_c', True, MU, None)
    auxiliary = rpc.build_params('B3_multicue_c', True, MU, None)
    for params in (b2, b3, auxiliary):
        assert params['legacy_stamp_units'] == 'mass_per_cell'
        assert params['random_stream_mode'] == 'coupled'
        assert params['truth_deterrence_memory'] == 'complete'
        assert params['dispatch_policy'] == 'res'
        assert params['reservation_fraction'] == 0.25
    assert b2['predictive_utility_mode'] == 'deltaJ'
    assert b2['predictive_fixed_deterring_mode'] == 'laser'
    assert b3['predictive_utility_mode'] == 'stl_robustness'
    assert tuple(b3['stl_active_clauses']) == ('exp', 'cov')
    assert b3['predictive_fixed_deterring_mode'] == 'laser'
    assert auxiliary['predictive_fixed_deterring_mode'] is None
    # Leave the archived reproduction's historical B3 definition intact.
    assert rpc.build_params('B3', True, MU, None)['predictive_fixed_deterring_mode'] is None


def test_complete_truth_memory_retains_more_than_200_relevant_applications():
    import DeterrentSystem as ds
    params = rpc.build_params('B5_c', True, 2e-5, 1.0)
    params['seed'] = 200
    frames = ds.run_simulation_frames_persistent(**params)
    try:
        next(frames)
        local = frames.gi_frame.f_locals
        store = local['truth_deterrence_store']
        assert isinstance(store, list) and store is not local['recent_deterrences']
        store[:] = [dict(t=0.0, eta=1.0, beta=1.0, omega=3600.0) for _ in range(251)]
        local['_prune_truth_deterrence_store'](30.0)
        assert len(store) == 251
        local['_prune_truth_deterrence_store'](3600.0 * 30.0)
        assert store == []
    finally:
        frames.close()


@pytest.mark.parametrize("mu", list(rpc.LOADS.values()))
def test_A_legacy_units_resolves_to_the_old_setting(mu):
    """A_legacy_units = ladder B4 + the pre-2026-10-28 PLAN_ENV + A's overrides, density units."""
    ladder = rpc._ladder_params(rpc.LADDER_SYSTEMS["B4"], True, mu)
    want = {**ladder, **OLD_PLAN_ENV, "legacy_stamp_units": "density",
            **json.loads(json.dumps(rpc._A)), "mu_true": mu}
    got = rpc.build_params("A_legacy_units", True, mu, None)
    assert _diff(want, got) == set()
    a = rpc.build_params("A", True, mu, None)
    assert _diff(a, got) == {"legacy_stamp_units"}


def test_new_units_overrides_apply_to_every_variant_but_A_legacy_units(monkeypatch):
    monkeypatch.setattr(rpc, "NEW_UNITS_OVERRIDES", {"min_hotspot_score": 1.234e-6})
    for v in rpc.VARIANTS:
        p = rpc.build_params(v, True, MU, None)
        if v == "A_legacy_units":
            assert p.get("min_hotspot_score") != 1.234e-6
        else:
            assert p["min_hotspot_score"] == 1.234e-6, v
    for v in rpc.LEGACY_VARIANTS:
        assert rpc.build_params(v, True, MU, None).get("min_hotspot_score") != 1.234e-6


def test_A_legacy_units_in_confirmatory_study_and_compared_with_A():
    import experiments.run_plan_studies as rps
    assert "A_legacy_units" in rps.CONFIRMATORY_VARIANTS
    assert ("A_legacy_units", "A") in {(r, t) for r, t, _ in rpc.COMPARISONS}


# ---------------------------------------------------------------------------
# B: excess fields
# ---------------------------------------------------------------------------
T_OFF_PEAK = 6.0 * 3600.0  # time multiplier != 1


def test_excess_density_is_lam_minus_mu_bit_for_bit():
    m = _model("density", t_now=T_OFF_PEAK)
    assert m.time_multiplier(m.t_now) != 1.0
    assert excess_baseline_grid(m) is m.mu
    assert np.array_equal(excess_field(m), m.lam - m.mu)
    for iy, ix in ((10, 12), (30, 40), (0, 0)):
        assert excess_at(m, iy, ix) == float(m.lam[iy, ix] - m.mu[iy, ix])
    # hotspots: historical field
    field = m.lam - m.mu
    for h in m.hotspots(top_k=5, merge_radius=20.0, use_excess=True):
        iy, ix = m.world_to_idx(h["x"], h["y"])
        assert h["score"] == float(field[iy, ix])


def test_excess_mass_per_cell_is_time_adjusted():
    m = _model("mass_per_cell", t_now=T_OFF_PEAK)
    tm = m.time_multiplier(m.t_now)
    assert tm != 1.0
    np.testing.assert_array_equal(excess_baseline_grid(m), m.mu * tm)
    np.testing.assert_array_equal(excess_field(m), m.lam - m.mu * tm)
    # the excess is exactly the stamped part trigger - inhib where lam is not clipped
    unclipped = (m.mu * tm + m.trigger_mass - m.inhib_mass) > 0
    np.testing.assert_allclose(excess_field(m)[unclipped],
                               (m.trigger_mass - m.inhib_mass)[unclipped], rtol=0, atol=1e-18)
    for iy, ix in ((10, 12), (30, 40), (0, 0)):
        assert excess_at(m, iy, ix) == float(m.lam[iy, ix] - m.mu[iy, ix] * tm)
    field = m.lam - m.mu * tm
    hs = m.hotspots(top_k=5, merge_radius=20.0, use_excess=True)
    assert hs
    for h in hs:
        iy, ix = m.world_to_idx(h["x"], h["y"])
        assert h["score"] == float(field[iy, ix])


def test_consistent_estimator_excess_unchanged():
    m = ConsistentOnlineSESTPP(0.0, W, 0.0, H, NX, NY, alpha=0.2, sigma=10.0, omega=450.0, mu_init=2e-5)
    assert m.legacy_stamp_units == "density"
    assert excess_baseline_grid(m) is m.mu


def test_no_raw_lam_minus_mu_left_in_evaluated_modules():
    """Every excess reader of the evaluated system goes through the flag-aware helpers."""
    pat = re.compile(r"\blam\b(\[[^\]]*\])?\s*-\s*[\w.]*\bmu\b(\[[^\]]*\])?(?!\s*\*)")
    for rel in ("DeterrentSystem.py", "TaskGenerator.py", "habituation_stl/scenario_rollout.py",
                "planner_task_extraction.py", "planner_task_estimation.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        code = [ln.split("#", 1)[0] for ln in src.splitlines()]
        hits = [ln for ln in code if pat.search(ln) and "lam = clip" not in ln]
        assert hits == [], (rel, hits)


def test_task_generator_uses_time_adjusted_excess_with_mass_per_cell(monkeypatch):
    """TaskGenerator hotspot scores under mass_per_cell read lam - mu * m(t)."""
    import TaskGenerator as tgmod
    calls = []
    orig = tgmod.excess_at

    def spy(model, iy, ix):
        v = orig(model, iy, ix)
        calls.append((model.legacy_stamp_units, v,
                      float(model.lam[iy, ix] - model.mu[iy, ix] * model.time_multiplier(model.t_now))))
        return v

    monkeypatch.setattr(tgmod, "excess_at", spy)
    import DeterrentSystem as ds
    p = rpc.build_params("B5_c", True, 4e-4, 200.0)
    p["seed"] = 201
    for _ in ds.run_simulation_frames_persistent(**p):
        pass
    assert calls
    assert {u for u, _, _ in calls} == {"mass_per_cell"}
    assert all(v == w for _, v, w in calls)


# ---------------------------------------------------------------------------
# C: rollout B5 copy cost reads
# ---------------------------------------------------------------------------
def _sim_locals(**over):
    import DeterrentSystem as ds
    p = rpc.build_params("B5_c", True, MU, 30.0)
    p["seed"] = 202
    p.update(over)
    gen = ds.run_simulation_frames_persistent(**p)
    for _ in range(3):
        next(gen)
    return gen, gen.gi_frame.f_locals


def test_rollout_cfg_reads_cost_weights_from_live_parameters():
    gen, L = _sim_locals()
    cfg = sr.B5Config.from_sim_locals(L)
    assert cfg.cost_w_eta == 1.0 and cfg.deterring_cost_multiplier == 1.0
    gen.close()
    gen, L = _sim_locals(patrol_cost_weight=2.5, deterring_cost_multiplier=3.0)
    cfg = sr.B5Config.from_sim_locals(L)
    assert cfg.cost_w_eta == 2.5 and cfg.deterring_cost_multiplier == 3.0
    gen.close()


def test_rollout_cfg_reads_planner_profile_override():
    """A planner profile that overrides the cost weights reaches the rollout copy too."""
    L = {"patrol_cost_weight": 1.0e-300, "deterring_cost_multiplier": 4.86e-08, "dispatch_policy": "unc"}
    cfg = sr.B5Config.from_sim_locals(L)
    assert cfg.cost_w_eta == 1.0e-300 and cfg.deterring_cost_multiplier == 4.86e-08


def test_generation_modes_identity_at_default_and_live_transform_otherwise():
    modes = {"formation": {"beta": 1.0, "w_eta": 1.0}, "laser": {"beta": 2.0, "w_eta": 1.5, "fixed_cost": 0.3},
             "biosonic": {"beta": 0.5}}
    assert sr.generation_deterring_modes(modes, 1.0) is modes
    got = sr.generation_deterring_modes(modes, 2.0)
    assert got == {"formation": {"beta": 1.0, "w_eta": 2.0, "fixed_cost": 0.0},
                   "laser": {"beta": 2.0, "w_eta": 3.0, "fixed_cost": 0.6},
                   "biosonic": {"beta": 0.5, "w_eta": 2.0, "fixed_cost": 0.0}}
    assert modes["laser"]["w_eta"] == 1.5     # input untouched


@pytest.mark.parametrize("mult", [1.0, 2.0])
def test_generation_modes_match_planner_task_extraction(mult):
    """Same catalog and patrol weight as the live generation hands TaskGenerator."""
    import inspect
    import planner_task_extraction as pte
    seen = {}

    class _TG:
        def periodic_patrolling(self, **kw):
            seen["modes"] = kw["deterring_modes"]
            seen["cost_w_eta"] = kw["cost_w_eta"]

    params = inspect.signature(pte.run_task_location_estimation).parameters
    kwargs = {k: None for k, prm in params.items() if prm.default is inspect.Parameter.empty}
    for k in kwargs:
        ann = str(params[k].annotation)
        if "float" in ann:
            kwargs[k] = 1.0
        elif "int" in ann:
            kwargs[k] = 1
        elif "bool" in ann:
            kwargs[k] = True
        elif "str" in ann:
            kwargs[k] = "x"
    modes = {"formation": {"beta": 1.0, "w_eta": 1.0}, "laser": {"beta": 2.0, "w_eta": 1.5, "fixed_cost": 0.3}}
    kwargs.update(taskgen=_TG(), robots={}, deterring_modes=modes, enable_patrolling=True,
                  busy_deterring_robots=set(), recent_deterrences=[], profiles={}, pose={},
                  preventive_capacity_remaining_by_robot={}, preventive_capacity_ready_by_robot={},
                  value_weight_fn=lambda x, y: 1.0, rng=None,
                  deterring_cost_multiplier=mult, patrol_cost_weight=0.7)
    pte.run_task_location_estimation(**kwargs)
    assert seen["modes"] == sr.generation_deterring_modes(modes, mult)
    if mult == 1.0:
        assert seen["modes"] is modes and sr.generation_deterring_modes(modes, mult) is modes
    assert seen["cost_w_eta"] == 0.7 == sr.B5Config.from_sim_locals(
        {"patrol_cost_weight": 0.7, "deterring_cost_multiplier": mult}).cost_w_eta


# ---------------------------------------------------------------------------
# Profile-held matched keys reach the simulator through the harness path (2026-10-28, 3a)
# ---------------------------------------------------------------------------
def test_new_units_overrides_reach_simulator_via_job_file(monkeypatch, tmp_path):
    import pickle
    import DeterrentSystem as ds
    monkeypatch.setattr(rpc, "NEW_UNITS_OVERRIDES", {
        "planner_profile_overrides": {"model_deterring_score_margin": 0.0425, "assigner_w_task_value": 0.0375},
        "deterring_modes_w_eta": {"laser": 0.6},
        "task_refresh_min_score": 2.5e-6,
        "proposed_model_overrides": {"alpha_in": 0.0021}})
    p = rpc.build_params("B5_c", True, MU, 20.0)
    legacy = rpc.build_params("A_legacy_units", True, MU, 20.0)
    assert "planner_profile_overrides" not in legacy and legacy["deterring_modes"]["laser"]["w_eta"] == 1.5
    job = pickle.loads(pickle.dumps(rpc.make_job(tmp_path, "B5_c", True, 200, p)))   # as the job file does
    gen = ds.run_simulation_frames_persistent(**{**job["params"], "seed": 200})
    for _ in range(3):
        next(gen)
    L = gen.gi_frame.f_locals
    assert L["model_deterring_score_margin"] == 0.0425           # profile holds 0.10
    assert L["assigner_w_task_value"] == 0.0375 and L["assigner"].w["w_task_value"] == 0.0375
    assert L["deterring_modes"]["laser"]["w_eta"] == 0.6 and L["deterring_modes"]["formation"]["w_eta"] == 1.0
    assert L["task_refresh_min_score"] == 2.5e-6
    assert next(iter(L["robots"].values())).m.alpha_in == 0.0021
    gen.close()
    # without the overlay the profile value wins over a plain argument (why the overlay exists)
    p2 = rpc.build_params("B5_c", True, MU, 20.0)
    p2.pop("planner_profile_overrides")
    p2["model_deterring_score_margin"] = 0.0425
    gen = ds.run_simulation_frames_persistent(**{**p2, "seed": 200})
    next(gen)
    assert gen.gi_frame.f_locals["model_deterring_score_margin"] == 0.10
    gen.close()


def test_profile_overrides_without_profile_is_an_error():
    import DeterrentSystem as ds
    p = rpc.build_params("B5_c", True, MU, 20.0)
    p["planner_profile"] = ""
    p["planner_profile_overrides"] = {"model_deterring_score_margin": 0.05}
    with pytest.raises(ValueError):
        next(ds.run_simulation_frames_persistent(**{**p, "seed": 200}))
