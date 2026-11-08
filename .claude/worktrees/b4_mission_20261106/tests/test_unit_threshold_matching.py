"""Machinery of the unit-fix threshold matching (user decisions 2026-10-28 E) and the refit
harness plumbing (decision D)."""
import argparse
import json
import math
import os

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import experiments.run_plan_completion as rpc  # noqa: E402
from experiments import unit_threshold_matching as utm  # noqa: E402

MU = 1e-4
OVR = {"min_hotspot_score": 2e-6, "risk_field_cut": 1e-6, "task_refresh_min_score": 3e-6,
       "model_deterring_score_margin": 0.05, "w_task_value": 0.3, "stl_E_star": 3.0, "stl_kernel_self": 1.7,
       "w_eta__formation": 0.5, "w_eta__laser": 0.7, "w_eta__biosonic": 0.9, "patrol_cost_weight": 0.25}
CONST = {"sigma": 4.0, "omega": 300.0, "omega_inhib": 800.0, "alpha_in": 0.01, "alpha_cross": 0.0,
         "alpha_inhib": 3.0, "mu_base": 1e-6, "bg_ema": 1e-7, "model_feedback_sigma_scale": 1.0,
         "model_feedback_omega_scale": 1.5}


def _diff(a, b):
    return {k for k in set(a) | set(b) if a.get(k, "<absent>") != b.get(k, "<absent>")}


@pytest.mark.parametrize("system", list(utm.SYSTEMS))
def test_old_side_is_the_old_setting(system, monkeypatch):
    monkeypatch.setattr(rpc, "NEW_UNITS_OVERRIDES", {"min_hotspot_score": 9.0})
    p = utm.build_side_params(system, MU, "old", {}, {})
    assert p["legacy_stamp_units"] == "density" and p.get("min_hotspot_score") != 9.0
    if system == "A":
        assert _diff(p, rpc.build_params("A_legacy_units", True, MU, None)) == set()
    assert rpc.NEW_UNITS_OVERRIDES == {"min_hotspot_score": 9.0}   # restored


def test_old_side_refuses_overrides():
    with pytest.raises(SystemExit):
        utm.collect("old", "x", {"alpha_in": 1.0}, {}, t_end=1.0)


def test_new_side_values_reach_the_simulator():
    """Every matched value and refitted constant is what the simulator resolves (profile keys too)."""
    import DeterrentSystem as ds
    p = utm.build_side_params("B", MU, "new", CONST, OVR)
    assert p["legacy_stamp_units"] == "mass_per_cell"
    p["planner_profile_overrides"] = utm.side_profile_overlay(p, "new", OVR)
    assert p["planner_profile"] == "thesis_calibrated_selective_proposed"
    p["seed"] = 200
    p["T_end"] = 20.0
    gen = ds.run_simulation_frames_persistent(**p)
    for _ in range(3):
        next(gen)
    L = gen.gi_frame.f_locals
    assert L["min_hotspot_score"] == 2e-6
    assert L["model_deterring_risk_scale"] == pytest.approx(1e-6 / -math.log(1 - 0.35), rel=1e-12)
    assert L["model_deterring_risk_threshold"] == 0.35
    assert L["task_refresh_min_score"] == 3e-6
    assert L["model_deterring_score_margin"] == 0.05
    assert L["assigner_w_task_value"] == 0.3 and L["assigner"].w["w_task_value"] == 0.3
    assert L["stl_E_star"] == 3.0 and L["stl_kernel_self"] == 1.7
    assert L["deterring_cost_multiplier"] == 1.0 and L["patrol_cost_weight"] == 0.25
    assert {k: v["w_eta"] for k, v in L["deterring_modes"].items()} == {
        "formation": 0.5, "laser": 0.7, "biosonic": 0.9}
    assert L["model_deterring_busy_fallback_p_event_min"] == 0.95
    assert L["model_deterring_busy_fallback_deltaJ_per_cost_min"] == 1e6
    m = next(iter(L["robots"].values())).m
    assert m.legacy_stamp_units == "mass_per_cell"
    assert (m.sigma, m.omega, m.alpha_in, m.alpha_inhib, m.omega_inhib) == (4.0, 300.0, 0.01, 3.0, 800.0)
    assert L["model_feedback_omega_scale"] == 1.5
    gen.close()


def test_load_constants_maps_refit_result(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"deployed_constants": {"model_alpha_in": 0.5, "model_feedback_sigma_scale": 0.7}}))
    assert utm.load_constants(str(f)) == {"alpha_in": 0.5, "model_feedback_sigma_scale": 0.7}


def test_unidentified_assignment_weight_keeps_the_paper_reference():
    old = np.zeros((4, utm.W_GRID.size), dtype=np.uint8)
    new = old.copy()
    new[:, -3:] = 1  # only enormous weights perturb the numerical ranking
    result = utm.match_w_task_value(old, new, np.zeros(4))
    assert result['matched_value'] == utm.OLD_W_TASK_VALUE
    assert result['achieved_share'] == 0.0
    assert result['identified'] is False


def test_assignment_weight_has_explicit_failure_when_no_zero_change_value_exists():
    old = np.zeros((4, utm.W_GRID.size), dtype=np.uint8)
    result = utm.match_w_task_value(old, np.ones_like(old), np.zeros(4))
    assert math.isnan(result['matched_value'])
    assert result['identified'] is False


def test_map_quantile_rule_on_synthetic_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(utm, "OUT_ROOT", tmp_path)
    rng = np.random.default_rng(0)
    for tag, scale, first_change in (("old", 1.0, 100), ("new", 1.0 / 90.0, 40)):
        d = tmp_path / tag
        d.mkdir()
        for system in utm.SYSTEMS:
            arrays = {name: rng.exponential(abs(spec["value"]) * 2.0, 400) *
                      (scale if name in ("min_hotspot_score", "risk_field_cut", "task_refresh_min_score") else 1.0)
                      for name, spec in utm.OLD_THRESHOLDS.items()}
            arrays["busy_risk_field"] = rng.exponential(1e-4, 50) * scale
            arrays["info_busy_fallback_pass"] = np.zeros(7)
            grid = np.zeros((5, utm.W_GRID.size), dtype=np.uint8)
            grid[:, first_change:] = 1        # only absurdly large w changes an assignment
            arrays["assign_change_grid"] = grid
            np.savez(d / f"{system}_1e-04_200.npz", **arrays)
    out = tmp_path / "it1.json"
    rep = utm.cmd_map(argparse.Namespace(old_tag="old", new_tag="new", previous=None, out=str(out)))
    for name in ("min_hotspot_score", "task_refresh_min_score", "w_eta__laser", "stl_kernel_self", "stl_E_star"):
        e = rep["thresholds"][name]
        assert abs(e["q_check_new"] - e["q"]) < 0.01, name
    assert rep["mapped"]["model_deterring_risk_scale"] == pytest.approx(
        rep["mapped"]["risk_field_cut"] / -math.log(1 - 0.35))
    w = rep["thresholds"]["w_task_value"]
    assert w["q"] == 0.0 and w["matched_value"] == utm.W_GRID[39] and w["achieved_share"] == 0.0
    assert rep["busy_fallback"]["new"] == {"checks": 28, "passes": 0}
    assert "q_new_B5_family" in rep["thresholds"]["model_deterring_score_margin"]
    assert rep["converged_1pct"] is False
    rep2 = utm.cmd_map(argparse.Namespace(old_tag="old", new_tag="new", previous=str(out),
                                          out=str(tmp_path / "it2.json")))
    assert rep2["converged_1pct"] is True


def test_calibration_harness_units_field_default_is_historical():
    from diagnostics.diagnostic_sestpp_subsystem import SubsystemConfig, _build_model
    assert SubsystemConfig().model_legacy_stamp_units == "density"
    assert _build_model(SubsystemConfig(NX=6, NY=5)).legacy_stamp_units == "density"
    assert _build_model(SubsystemConfig(NX=6, NY=5, model_legacy_stamp_units="mass_per_cell")).legacy_stamp_units \
        == "mass_per_cell"


def test_refit_equivalent_start_reproduces_old_fit():
    from experiments import refit_sestpp_new_units as rf
    pred, prop = rf.equivalent_start(rf.C001_PREDICTION), rf.equivalent_start(rf.C001_PROPOSED)
    assert prop["alpha_in"] == pytest.approx(0.15 * rf.NODE_AREA) and prop["sigma"] == 10.0
    a = rf._run((rf.C001_PREDICTION, rf.C001_PROPOSED, 0.2, 200, "density"))
    b = rf._run((pred, prop, 0.2, 200, "mass_per_cell"))
    for k in rf.METRIC_KEYS:
        assert b[k] == pytest.approx(a[k], rel=1e-9, abs=1e-12), k
    with pytest.raises(ValueError):
        rf._run((pred, prop, 1.0, 300, "mass_per_cell"))
