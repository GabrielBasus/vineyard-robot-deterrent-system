"""User decisions of 2026-10-22 (AUDIT round) for the B4-pipeline variants:

  * C: Plan Eq. 3 sums over ALL cells of the field (decision 6), A/B keep local cells.
  * Dual shadow: the forecast-only shadow (stl_shadow_overrides, the variant's own inputs)
    is kept and a full Section 2 shadow (stl_shadow_full_section2: inputs AND dynamics
    rebuilt) is added; A's full shadow is B's primary score on the same snapshot and
    vice versa.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

import habituation_stl  # noqa: F401,E402
from habituation_stl.habituation import HabituationField  # noqa: E402
from habituation_stl.mission_spec import SpecParams  # noqa: E402
from habituation_stl.task_value import Dynamics  # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "b4_variant_A_reference.json"


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
# C: Eq. 3 over ALL cells
# ---------------------------------------------------------------------------
def test_eq3_sums_over_all_cells_not_local_cells():
    from SESTPP import OnlineSESTPP
    from planner_task_estimation import eq3_counterfactual_value, estimate_stl_counterfactual_value

    m = OnlineSESTPP(0.0, 60.0, 0.0, 60.0, 7, 7, sigma=10.0, omega=500.0, omega_inhib=700.0,
                     alpha_inhib=0.3, mu_base=2e-3)
    rng = np.random.default_rng(4)
    m.mu = rng.uniform(1e-3, 3e-3, size=(7, 7))
    m.trigger_mass = rng.uniform(0.0, 4e-3, size=(7, 7))
    m.t_now = 0.0
    m._update_lambda()
    cells = [[(0, 0), (30, 0), (30, 60), (0, 60)], [(30, 0), (60, 0), (60, 60), (30, 60)]]
    hab = HabituationField(2, 2, T_rec=900.0, kappa=0.5)
    sp = SpecParams(horizon=40.0, active_clauses=("exp", "cov", "hab"))
    kw = dict(mode="m1", mode_to_id={"m0": 0, "m1": 1}, hab=hab, spec_params=sp, cell_polys=cells,
              local_cell_ids=[1], last_service_t_by_cell={}, now_t=0.0, completion_lead_s=7.0,
              weight_fn=None, target_cell_id=1, pending_events=[], cue_sigma=8.0, cue_omega=300.0)
    # a candidate near the cell border suppresses nodes on both sides of it
    dyn = Dynamics(omega_e=500.0, omega_u=700.0, beta=(0.5, 0.8), forecast_correction=True,
                   valuation_mode="integrated_exposure_eq3", eq3_dt_s=1.0)
    out = estimate_stl_counterfactual_value(m, 32.0, 25.0, dynamics=dyn, **kw)
    common = dict(cell_polys=cells, weight_fn=None, hab=hab, spec_params=sp, dynamics=dyn, target_cell_id=1,
                  mode_id=1, completion_lead_s=7.0, now_t=0.0, cue_sigma=8.0, cue_omega=300.0,
                  pending_events=[], dt=1.0)
    ref_all = eq3_counterfactual_value(m, 32.0, 25.0, cells=[0, 1], **common)
    ref_local = eq3_counterfactual_value(m, 32.0, 25.0, cells=[1], **common)
    assert ref_all["U"] > ref_local["U"] > 0.0
    assert out["predictive_stl_U"] == ref_all["U"]
    # A/B (STL robustness) keep the robot's local cells
    rob = estimate_stl_counterfactual_value(m, 32.0, 25.0, dynamics=Dynamics(beta=(0.5, 0.8)), **kw)
    assert rob["stl_local_cell_count"] == 1


# ---------------------------------------------------------------------------
# Dual shadow
# ---------------------------------------------------------------------------
_S2_ON = {"stl_forecast_correction": True, "stl_forward_trajectory_correction": True,
          "stl_committed_schedule": True, "stl_queue_aware_lead": True,
          "stl_forecast_planner_update_model": True}
_S2_OFF = {k: False for k in _S2_ON}


def _shadow_run(over, t_end=300.0):
    import DeterrentSystem as ds
    params = _ref_params(t_end=t_end, mu_true=1.0e-4, **over)
    gen = ds.run_simulation_frames_persistent(**params)
    frames, last, L = [], None, None
    for fr in gen:
        frames.append((fr["t"], {k: tuple(v) for k, v in fr["poses"].items()},
                       sorted((tr["id"], tr["type"], tr.get("mode"), tr["assigned_primary"],
                               round(float(tr["x"]), 9), round(float(tr["y"]), 9))
                              for tr in fr["tasks_active"])))
        last = fr
        L = gen.gi_frame.f_locals
    log = list(L["taskgen"].stl_eval_log)
    done = [float(tr["t_done"]) for tr in last["tasks_done"]
            if tr.get("type") == "deterring" and tr.get("t_done") is not None]
    info = {"stl_dynamics": L["stl_dynamics"], "stl_shadow_full_dynamics": L["stl_shadow_full_dynamics"]}
    return frames, log, info, (min(done) if done else math.inf), last["metrics_compact"]


@pytest.fixture(scope="module")
def dual_shadow_runs():
    a = _shadow_run({"stl_shadow_overrides": {"forecast_correction": True}, "stl_shadow_full_section2": _S2_ON})
    b = _shadow_run({**_S2_ON, "stl_shadow_overrides": {"forecast_correction": False},
                     "stl_shadow_full_section2": _S2_OFF})
    return a, b


def test_full_shadow_is_the_other_variants_primary_on_the_same_snapshot(dual_shadow_runs):
    """A's full-set shadow = B's primary score, and B's full-set shadow = A's primary score,
    on every decision where the two runs still hold the same state (identical frames and no
    deterring completion yet; after one, q x beta feedback differs between A and B)."""
    (fa, la, ia, da, _), (fb, lb, ib, db, _) = dual_shadow_runs
    t_div = min(da, db)
    for (ta, pa, ka), (tb, pb, kb) in zip(fa, fb):
        if pa != pb or ka != kb:
            t_div = min(t_div, ta)
            break
    keys = sorted({(r[0], r[1]) for r in la + lb if r[0] < t_div})
    compared = 0
    for key in keys:
        ga = [r for r in la if (r[0], r[1]) == key]
        gb = [r for r in lb if (r[0], r[1]) == key]
        # within one decision the generator may evaluate a different candidate set once a
        # robot's earlier choice differed (score-dependent re-evaluations); compare the
        # decision groups whose candidate sequences coincide (the first decision always does)
        if [r[:4] for r in ga] != [r[:4] for r in gb]:
            continue
        compared += 1
        for ra, rb in zip(ga, gb):
            assert ra[9] == rb[4]          # A's full shadow == B's primary
            assert rb[9] == ra[4]          # B's full shadow == A's primary
    assert keys and keys[0][0] == 0.0
    assert compared >= 3
    # the shadow configurations are literally the other variant's Dynamics
    assert ia["stl_shadow_full_dynamics"] == replace(ib["stl_dynamics"], shadow_overrides=())
    assert ib["stl_shadow_full_dynamics"] == replace(ia["stl_dynamics"], shadow_overrides=())


def test_dual_shadow_metrics_and_primary_unchanged(dual_shadow_runs):
    (fa, la, _ia, _da, ma), _ = dual_shadow_runs
    for k in ("stl_shadow_forecast_top1_agree_fraction", "stl_shadow_forecast_kendall_tau_mean",
              "stl_shadow_forecast_masked_group_fraction", "stl_shadow_full_top1_agree_fraction",
              "stl_shadow_full_kendall_tau_mean", "stl_shadow_full_masked_group_fraction",
              "stl_shadow_full_compared_groups", "stl_travel_recovery_gap_mean",
              "stl_travel_recovery_gap_p90", "stl_travel_recovery_gap_max", "stl_travel_recovery_gap_rel_mean"):
        assert k in ma
    assert ma["stl_shadow_full_compared_groups"] > 0
    # historical names = the forecast-only shadow
    assert _same(ma["stl_shadow_top1_agree_fraction"], ma["stl_shadow_forecast_top1_agree_fraction"])
    # the full shadow is diagnostic only: A's executed run is unchanged without it
    f0, l0, _i0, _d0, m0 = _shadow_run({"stl_shadow_overrides": {"forecast_correction": True}})
    assert f0 == fa
    assert [r[:9] for r in l0] == [r[:9] for r in la]
    assert all(math.isnan(r[9]) for r in l0)
    assert m0["value_weighted_exposure"] == ma["value_weighted_exposure"]


def test_full_shadow_rejects_unknown_flag():
    import DeterrentSystem as ds
    with pytest.raises(ValueError, match="stl_shadow_full_section2"):
        next(ds.run_simulation_frames_persistent(**_ref_params(t_end=5.0, stl_shadow_full_section2={"bogus": 1})))
