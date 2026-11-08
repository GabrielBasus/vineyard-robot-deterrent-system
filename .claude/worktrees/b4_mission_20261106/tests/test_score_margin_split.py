"""Phase 2 Q12 (user decision 2026-10-29): the score margin split per valuation scale.

model_deterring_score_margin was one setting compared on three value scales:
  legacy  -- the legacy / B5 utility (B1, B5 and the plan variants' B5 copy pi_0),
  stl     -- the B4 STL robustness value (A, B, A_legacy_units),
  eq3     -- the Plan Eq. 3 integrated-exposure value (C, C_gate).
It is now three settings, model_deterring_score_margin_{legacy,stl,eq3}; each defaults to
the single value, so every run is bit-for-bit unchanged unless one is overridden.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

T_EPLAN = 240.0


def _eplan_U(c, call):
    # deterministic (no hash()): admit roughly one candidate in three
    return 1.0 if (int(round(c.x * 7.0 + c.y * 13.0)) % 3) == 0 else -1.0


def eplan_stub_run(**over):
    """E_plan (B5 + plan procedure + service protection) with the stub engine of
    test_plan_procedure; mu 2e-5, seed 200, 240 s."""
    import DeterrentSystem as ds
    from experiments.run_plan_completion import build_params
    from test_plan_procedure import StubEngine
    eng = StubEngine(_eplan_U)
    p = build_params("E_plan", True, 2e-5, T_EPLAN)
    p.update(seed=200, plan_engine=eng, plan_oracle_fraction=0.0)
    p.update(over)
    frames = []
    last = None
    for fr in ds.run_simulation_frames_persistent(**p):
        frames.append(repr((fr["t"], sorted((str(k), repr(v)) for k, v in fr["poses"].items()),
                            sorted((tr["id"], tr["type"], tr.get("mode"), tr["assigned_primary"],
                                    float(tr["x"]), float(tr["y"])) for tr in fr["tasks_active"]),
                            float(fr["metrics_compact"]["value_weighted_exposure"]))))
        last = fr
    m = last["metrics_compact"]
    tail = {k: repr(m.get(k)) for k in ("plan_deviations_admitted", "plan_decision_count",
                                        "plan_rejected_gate", "value_weighted_exposure")}
    return frames, tail, eng


_RUNTIME_PREFIXES = ("stl_eval_runtime_", "selected_calibration_", "plan_wall", "plan_compute",
                     "wall_", "runtime")


def variant_run(variant, t_end, mu=1e-4, seed=200, keep_locals=False, **over):
    """Short PLAN_ENV run of an evaluation variant; returns (metrics, simulator locals)."""
    import DeterrentSystem as ds
    from experiments.run_plan_completion import build_params
    p = build_params(variant, True, mu, t_end)
    p.update(seed=seed)
    p.update(over)
    gen = ds.run_simulation_frames_persistent(**p)
    last = None
    loc = None
    for fr in gen:
        if keep_locals and loc is None:
            loc = dict(gen.gi_frame.f_locals)
        last = fr
    m =(last or {}).get("metrics_compact") or {}
    return m, loc


def metrics_fingerprint(m) -> str:
    keep = {k: repr(v) for k, v in sorted(m.items())
            if not any(k.startswith(p) or p in k for p in _RUNTIME_PREFIXES)}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()


def eplan_fingerprint(**over) -> str:
    frames, tail, _eng = eplan_stub_run(**over)
    blob = json.dumps({"frames": frames, "tail": tail}, sort_keys=True, default=repr)
    return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Pre-change references (recorded at bdee3ad, before the split)
# ---------------------------------------------------------------------------
EPLAN_STUB_FINGERPRINT_BDEE3AD = "9d27d519f3c839c370f8deab7b18908ad6f4a20a1844d879af74297e9bf2560b"
# metrics_fingerprint of variant_run(v, 180.0) (mu 1e-4, seed 200, habituation on)
SHORT_FINGERPRINTS_BDEE3AD = {
    "B1_c": "f2398cdfa8b170603feaa34ca9d5b1d61a8d9f3ee271c8f3ae5933b5230d6137",
    "A": "eaaa00d94358c45dbcc83d86c951d90f0d8e97aa17411242c98c607636229178",
    "C": "b59a400290274962ec654ae277c739aaef5a1e873f0786f668ba1a967034d608",
}
SCALE_OF = {"B1_c": "legacy", "B5_c": "legacy", "A": "stl", "B": "stl", "A_legacy_units": "stl",
            "C": "eq3", "C_gate": "eq3"}
SPLIT_KEYS = {s: f"model_deterring_score_margin_{s}" for s in ("legacy", "stl", "eq3")}
OTHER = 0.77      # a value on the scales a system does not use
HUGE = 1.0e9      # always prefer the patrol candidate on that scale


# ---------------------------------------------------------------------------
# Selection rule
# ---------------------------------------------------------------------------
def test_scale_follows_the_valuation_actually_used():
    from types import SimpleNamespace as NS
    from TaskGenerator import resolve_score_margin, score_margin_scale
    assert score_margin_scale("legacy") == "legacy"
    assert score_margin_scale("legacy_habituation") == "legacy"
    assert score_margin_scale("stl_robustness", NS(valuation_mode="stl_robustness")) == "stl"
    assert score_margin_scale("stl_robustness", NS(valuation_mode="integrated_exposure_eq3")) == "eq3"
    # comparisons on none of the three scales keep the single margin
    assert score_margin_scale("stl_robustness", None) is None
    assert score_margin_scale("stl_robustness", NS(valuation_mode="integrated_exposure")) is None
    assert score_margin_scale("stl_robustness", NS(valuation_mode="continuation_rollout")) is None
    assert score_margin_scale("deltaJ") == "deltaJ"
    assert score_margin_scale("bernoulli_expected_deltaJ") is None
    assert resolve_score_margin("stl", 0.1) == 0.1
    assert resolve_score_margin("stl", 0.1, legacy=0.2, eq3=0.3) == 0.1
    assert resolve_score_margin("stl", 0.1, stl=0.4) == 0.4
    assert resolve_score_margin(None, 0.1, legacy=0.2, stl=0.3, eq3=0.4) == 0.1


# ---------------------------------------------------------------------------
# Bit for bit at defaults (and with the other scales' margins changed)
# ---------------------------------------------------------------------------
def _a_reference_diffs(**over):
    from test_b4_variants_sections23 import DATA, _RUNTIME_KEYS, _ref_params, _run, _same
    ref = json.loads(DATA.read_text())
    params = _ref_params(
        stl_committed_schedule=False, stl_queue_aware_lead=False,
        stl_forecast_planner_update_model=False, stl_binding_log_path=None,
        stl_binding_log_fraction=0.0, reservation_mode="floor", **over)
    m = _run(params)
    return [k for k, v in ref["metrics"].items()
            if k not in _RUNTIME_KEYS and not k.startswith("selected_calibration_") and not _same(v, m.get(k))]


def test_A_reference_bit_for_bit_split_margins():
    """Variant A pre-change reference: stl margin = the profile value 0.10, other scales changed."""
    assert _a_reference_diffs(model_deterring_score_margin_stl=0.10,
                              model_deterring_score_margin_legacy=OTHER,
                              model_deterring_score_margin_eq3=OTHER) == []


def test_B5c_shared_reference_bit_for_bit_split_margins():
    """B5_c shared-mode pre-change reference: legacy margin = 0.10, other scales changed."""
    from test_followups_b_d_decision17 import _b5c_params, _cmp_ref, _run
    p = _b5c_params(model_deterring_score_margin_legacy=0.10, model_deterring_score_margin_stl=OTHER,
                    model_deterring_score_margin_eq3=OTHER)
    assert _cmp_ref("B5_c_shared_mu1e-4_seed200_T300", _run(p)) == []


def test_E_plan_stub_fingerprint_at_defaults():
    assert eplan_fingerprint() == EPLAN_STUB_FINGERPRINT_BDEE3AD


def test_E_plan_stub_only_the_legacy_margin_matters():
    assert eplan_fingerprint(model_deterring_score_margin_stl=OTHER,
                             model_deterring_score_margin_eq3=OTHER) == EPLAN_STUB_FINGERPRINT_BDEE3AD
    assert eplan_fingerprint(model_deterring_score_margin_legacy=HUGE) != EPLAN_STUB_FINGERPRINT_BDEE3AD


# ---------------------------------------------------------------------------
# Each override changes only the systems on its scale
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("variant", sorted(SCALE_OF))
def test_each_system_uses_the_margin_of_its_scale(variant):
    vals = {"legacy": 0.31, "stl": 0.32, "eq3": 0.33}
    _m, loc = variant_run(variant, 50.0, keep_locals=True, **{SPLIT_KEYS[s]: v for s, v in vals.items()})
    scale = SCALE_OF[variant]
    assert loc["taskgen"].last_score_margin == (scale, vals[scale])
    _m, loc = variant_run(variant, 50.0, keep_locals=True)
    assert loc["taskgen"].last_score_margin == (scale, 0.10)      # profile value, unsplit


@pytest.mark.parametrize("variant", sorted(SHORT_FINGERPRINTS_BDEE3AD))
def test_defaults_bit_for_bit_short(variant):
    m, _ = variant_run(variant, 180.0)
    assert metrics_fingerprint(m) == SHORT_FINGERPRINTS_BDEE3AD[variant]


@pytest.mark.parametrize("scale", ["legacy", "stl", "eq3"])
@pytest.mark.parametrize("variant", sorted(SHORT_FINGERPRINTS_BDEE3AD))
def test_override_changes_only_its_scale(variant, scale):
    m, _ = variant_run(variant, 180.0, **{SPLIT_KEYS[scale]: HUGE})
    changed = metrics_fingerprint(m) != SHORT_FINGERPRINTS_BDEE3AD[variant]
    assert changed == (SCALE_OF[variant] == scale)


def test_rollout_b5_copy_uses_the_legacy_margin():
    """pi_0 of the plan variants (B5Config / _b5_periodic_patrolling) reads the legacy margin."""
    import copy
    from habituation_stl import scenario_rollout as sr
    from test_scenario_rollout import _sim_locals
    gen, L = _sim_locals(mu=4e-4, steps=140, seed=303)
    assert sr.B5Config.from_sim_locals(L).model_deterring_score_margin_legacy is None
    L2 = dict(L)
    L2["model_deterring_score_margin_legacy"] = 0.55
    assert sr.B5Config.from_sim_locals(L2).model_deterring_score_margin_legacy == 0.55
    snap = sr.snapshot_from_sim_locals(L, horizon_s=60.0)
    snap.cfg.jitter_m = 0.0
    tree = sr._sample_scenario_tree(snap, 0, 0)

    def rows(cfg_over):
        s = copy.deepcopy(snap)
        for k, v in cfg_over.items():
            setattr(s.cfg, k, v)
        sim = sr._Sim(s, tree, sr.NOOP, scenario=0, reactive_deadline_s=90.0)
        n0 = len(sim.taskgen._rows)
        sr._b5_periodic_patrolling(sim, s.t0 + 1.0)
        return [(r["robot_id"], r["type"], r.get("mode"), r["x"], r["y"]) for r in sim.taskgen._rows[n0:]]

    base = rows({})
    assert rows({"model_deterring_score_margin_legacy": snap.cfg.model_deterring_score_margin}) == base
    huge_split = rows({"model_deterring_score_margin_legacy": HUGE})
    assert huge_split == rows({"model_deterring_score_margin": HUGE})
    gen.close()


# ---------------------------------------------------------------------------
# planner_profile_overrides delivers each split margin
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("variant", ["B5_c", "A", "C"])
def test_profile_overlay_delivers_each_split_margin(variant, monkeypatch, tmp_path):
    import pickle
    import DeterrentSystem as ds
    import experiments.run_plan_completion as rpc
    vals = {"legacy": 0.0411, "stl": 0.0422, "eq3": 0.0433}
    monkeypatch.setattr(rpc, "NEW_UNITS_OVERRIDES", {
        "planner_profile_overrides": {SPLIT_KEYS[s]: v for s, v in vals.items()}})
    p = rpc.build_params(variant, True, 1e-4, 50.0)
    # a plain argument loses against the overlay
    p[SPLIT_KEYS[SCALE_OF[variant]]] = 0.999
    job = pickle.loads(pickle.dumps(rpc.make_job(tmp_path, variant, True, 200, p)))
    gen = ds.run_simulation_frames_persistent(**{**job["params"], "seed": 200})
    loc = None
    for _fr in gen:
        if loc is None:
            loc = dict(gen.gi_frame.f_locals)
    for s, v in vals.items():
        assert loc[SPLIT_KEYS[s]] == v
    assert loc["model_deterring_score_margin"] == 0.10     # the single margin is untouched
    assert loc["taskgen"].last_score_margin == (SCALE_OF[variant], vals[SCALE_OF[variant]])


def test_plain_split_argument_wins_over_the_profile_single_margin():
    _m, loc = variant_run("A", 50.0, keep_locals=True, model_deterring_score_margin_stl=0.0123)
    assert loc["model_deterring_score_margin"] == 0.10
    assert loc["taskgen"].last_score_margin == ("stl", 0.0123)
