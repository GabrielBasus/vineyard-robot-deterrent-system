"""
WS-A follow-ups (b), (d) and decision 17 wiring in the B4 pipeline / B5 scoring.

  * (b) committed-schedule emulation: the robot's predictive-time share decays over
    its reservation window during the emulation, so a predictive task blocked by
    the ceiling becomes eligible at exactly the step the dispatch rule allows.
  * (d) duplicate valuations: every valuation is kept; a repeated valuation of the
    same candidate (robot, x, y, cue) in the same decision is flagged
    is_reevaluation (eval log, binding log); metrics report all and first-only.
  * decision 17: with planner_hab_mode="per_robot", the generator reads the
    candidate robot's own effectiveness field (STL / Eq. 3 valuation incl. q_hat,
    legacy_habituation eta and cue choice); shared mode unchanged bit for bit.
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
from planner_committed_schedule import emulate_robot_schedule
from Robot import SlidingWindowTimeTracker

DATA = Path(__file__).resolve().parent / "data"
SHARED_REF = DATA / "shared_mode_reference_32c83b9.json"


def _run(params, keep_gen=False):
    import DeterrentSystem as ds
    gen = ds.run_simulation_frames_persistent(**params)
    last = None
    loc = None
    for frame in gen:
        last = frame
        if keep_gen and loc is None:
            loc = gen.gi_frame.f_locals
    m = (last or {}).get("metrics_compact") or (last or {}).get("metrics") or {}
    return (m, loc) if keep_gen else m


def _b4_params(t_end=240.0, **over):
    ref = json.loads((DATA / "b4_variant_A_reference.json").read_text())
    p = dict(ref["params"])
    p["stl_active_clauses"] = tuple(p["stl_active_clauses"])
    p.update(T_end=float(t_end), mu_true=1.0e-4, stl_forecast_correction=True,
             stl_forward_trajectory_correction=True, stl_committed_schedule=True,
             stl_queue_aware_lead=True, stl_forecast_planner_update_model=True)
    p.update(over)
    return p


def _b5c_params(t_end=300.0, **over):
    from experiments.run_plan_completion import build_params
    p = build_params("B5_c", True, 1e-4, float(t_end))
    p["seed"] = 200
    # The shared-mode references were recorded at 32c83b9, before PLAN_ENV gained
    # stl_forecast_correction=True (decision 1); pin it so the comparison isolates the wiring.
    p["stl_forecast_correction"] = False
    p.update(over)
    return p


# ---------------------------------------------------------------------------
# (b) predictive-share decay inside the committed-schedule emulation
# ---------------------------------------------------------------------------
RHO = 0.2


def _ceiling_select(calls):
    import DeterrentSystem as ds

    def sel(tasks, t, eta_fn, share, idle):
        out = ds._select_dispatch_policy_task(
            tasks, dispatch_policy="res", predictive_share=share, reservation_fraction=RHO,
            reactive_override_slack_s=90.0, reservation_softening_alpha=0.0,
            predictive_selection_policy="utility", now_t=t, eta_seconds_fn=eta_fn,
            rng=np.random.default_rng(0), reservation_mode="ceiling", robot_is_idle=idle)
        calls.append((t, share, out[0] is not None))
        return out
    return sel


def _pred_task():
    return {"id": 2, "type": "deterring", "mode": "laser", "origin": "model_scored", "x": 10.0,
            "y": 0.0, "time": 999.0, "score": 3.0, "utility": 3.0, "svc": 20.0, "stream": "predictive"}


def _emulate(tracker, calls):
    return emulate_robot_schedule(
        now_t=1000.0, dt=1.0, horizon_s=300.0, pose=(0.0, 0.0), speed_mps=1.0, spin_s=0.0,
        arrival_radius_m=0.5, loiter_until=-1.0, goal_xy=None, tasks=[_pred_task()],
        service_s_fn=lambda tr: float(tr["svc"]), is_deterring_fn=lambda tr: tr["type"] == "deterring",
        stream_fn=lambda tr: tr["stream"], select_fn=_ceiling_select(calls), tracker=tracker)


def test_ceiling_blocked_predictive_task_unblocks_when_share_decays():
    # 150 s of predictive time in [410, 560], idle in [560, 1000]: share(1000) = 0.25 >= rho.
    # At t = 1000 + s the window [t - 600, t] holds 160 - s s of it (s >= 10), so the share is
    # 120/600 = rho at t = 1040 (still blocked) and first < rho at t = 1041.
    live = SlidingWindowTimeTracker(600.0)
    live.record(410.0, 560.0, "predictive")
    live.record(560.0, 1000.0, "idle")
    assert live.predictive_share(1000.0) == pytest.approx(0.25)
    copy_tr = SlidingWindowTimeTracker(600.0)
    copy_tr.record(410.0, 560.0, "predictive")
    copy_tr.record(560.0, 1000.0, "idle")
    calls = []
    res = _emulate(copy_tr, calls)
    first_ok = min(t for t, _s, ok in calls if ok)
    assert first_ok == 1041.0
    for t, share, ok in calls:
        assert ok == (share < RHO)            # the emulation applies the rule itself
        if t <= 1040.0:
            assert not ok
    # the robot waits in place until 1041, travels 10 m (arrives at 1050), holds 20 s
    assert [tc for _, tc in res["completions"]] == [1070.0]
    assert res["free_t"] == 1071.0
    # the live tracker is not advanced by the emulation
    assert live.predictive_share(1000.0) == pytest.approx(0.25)


def test_without_decay_the_task_would_stay_blocked():
    """Control: freezing the share at its decision-time value never unblocks the task."""
    class Frozen:
        def predictive_share(self, t):
            return 0.25

        def record(self, *a):
            pass

    calls = []
    res = _emulate(Frozen(), calls)
    assert res["completions"] == [] and math.isinf(res["free_t"])
    # no predictive history: served at once (travel 1000..1009, hold to 1029)
    calls2 = []
    res2 = _emulate(SlidingWindowTimeTracker(600.0), calls2)
    assert [tc for _, tc in res2["completions"]] == [1029.0]


def test_simulator_passes_a_copy_of_the_live_tracker():
    import DeterrentSystem as ds
    seen = []
    orig = ds.emulate_robot_schedule

    def emu(**kw):
        seen.append(kw["tracker"])
        return orig(**kw)

    ds.emulate_robot_schedule = emu
    try:
        m, loc = _run(_b4_params(t_end=120.0, reservation_mode="ceiling", stl_strict_admission=True,
                                 stl_benefit_gate=0.0), keep_gen=True)
    finally:
        ds.emulate_robot_schedule = orig
    assert seen
    live = {id(r.dispatch_time_tracker) for r in loc["robots"].values()}
    for tr in seen:
        assert isinstance(tr, SlidingWindowTimeTracker)
        assert tr.window_s == 600.0
        assert id(tr) not in live


# ---------------------------------------------------------------------------
# (d) re-evaluations kept and flagged
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def reeval_run(tmp_path_factory):
    import TaskGenerator as tg
    path = tmp_path_factory.mktemp("bind") / "bind.jsonl"
    calls = []
    orig = tg.estimate_stl_counterfactual_value

    def est(model, x, y, **kw):
        calls.append((kw["now_t"], float(x), float(y), str(kw["mode"])))
        return orig(model, x, y, **kw)

    tg.estimate_stl_counterfactual_value = est
    try:
        m, loc = _run(_b4_params(t_end=240.0, stl_binding_log_path=str(path),
                                 stl_binding_log_fraction=1.0), keep_gen=True)
    finally:
        tg.estimate_stl_counterfactual_value = orig
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return m, loc["taskgen"], calls, rows


def test_reevaluations_flagged_per_candidate_and_decision(reeval_run):
    m, taskgen, calls, _rows = reeval_run
    meta = taskgen.stl_eval_meta
    assert len(meta) == len(calls) == len(taskgen.stl_eval_runtime_s)
    seen = set()
    expected = []
    for (t_m, rid, _flag), (t_c, x, y, mode) in zip(meta, calls):
        assert t_m == t_c
        key = (t_c, rid, x, y, mode)
        expected.append(key in seen)
        seen.add(key)
    assert [bool(f) for _, _, f in meta] == expected
    assert any(expected), "no re-evaluation occurred; the test would not exercise the flag"
    assert not all(expected)
    # eval-log rows carry the flag in position 8
    assert all(len(r) == 9 and isinstance(r[8], bool) for r in taskgen.stl_eval_log)


def test_reevaluation_metrics_total_and_first_only(reeval_run):
    m, taskgen, _calls, _rows = reeval_run
    flags = [bool(f) for _, _, f in taskgen.stl_eval_meta]
    assert m["stl_eval_count"] == len(flags)
    assert m["stl_eval_reevaluation_count"] == sum(flags)
    assert m["stl_eval_first_count"] == len(flags) - sum(flags)
    assert m["stl_eval_per_decision_mean"] >= m["stl_eval_per_decision_first_eval_mean"]
    rt = np.asarray(taskgen.stl_eval_runtime_s)
    first = rt[~np.asarray(flags)]
    assert m["stl_eval_runtime_first_eval_mean_ms"] == pytest.approx(float(np.mean(first) * 1e3))
    for k in ("stl_shadow_top1_agree_fraction", "stl_shadow_kendall_tau_mean", "stl_decision_groups",
              "stl_masked_group_fraction"):
        assert f"{k}_first_eval" in m
    # every decision group keeps its first evaluations
    assert m["stl_decision_groups_first_eval"] == m["stl_decision_groups"]


def test_binding_log_rows_carry_reevaluation_flag(reeval_run):
    _m, taskgen, _calls, rows = reeval_run
    assert rows
    assert all(isinstance(r["is_reevaluation"], bool) for r in rows)
    # fraction 1.0: every decision is sampled, so the binding rows are the logged
    # valuations in call order; their flags are a subsequence of the call flags.
    flags = [bool(f) for _, _, f in taskgen.stl_eval_meta]
    assert 0 < sum(r["is_reevaluation"] for r in rows) <= sum(flags)
    assert len(rows) <= len(flags)


# ---------------------------------------------------------------------------
# Decision 17: per-robot effectiveness reads
# ---------------------------------------------------------------------------
def _cmp_ref(name, metrics):
    ref = json.loads(SHARED_REF.read_text())[name]["metrics"]
    diffs = []
    for k, v in ref.items():
        # selected_calibration_* echo the on-disk calibration record (untracked ranking CSV
        # or tracked manifest JSON, last-ulp different): checkout metadata, not behavior.
        if k.startswith("selected_calibration_"):
            continue
        got = metrics.get(k)
        if v is None:
            if not (isinstance(got, float) and math.isnan(got)):
                diffs.append(k)
        elif got != v:
            diffs.append(k)
    return diffs


def test_shared_mode_bit_for_bit_B5c():
    """Pre-change reference (commit 32c83b9): B5_c, mu 1e-4, seed 200, 300 s."""
    assert _cmp_ref("B5_c_shared_mu1e-4_seed200_T300", _run(_b5c_params())) == []


def test_shared_mode_bit_for_bit_B4_B():
    """Pre-change reference (commit 32c83b9): B4 variant B, mu 1e-4, 240 s."""
    assert _cmp_ref("B4_B_shared_mu1e-4_T240", _run(_b4_params())) == []


class _Tagged:
    """Proxy for a HabituationField that logs reads under a tag."""

    def __init__(self, inner, tag, log):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "tag", tag)
        object.__setattr__(self, "_log", log)

    def __getattr__(self, name):
        self._log.append((self.tag, name))
        return getattr(self._inner, name)


def _per_robot_capture(params):
    import TaskGenerator as tg
    log, hab_tags = [], []
    orig_pp = tg.TaskGenerator.periodic_patrolling
    orig_est = tg.estimate_stl_counterfactual_value

    def pp(self, *a, **kw):
        fn = kw.get("stl_hab_for_robot_fn")
        assert fn is not None, "per_robot mode must pass the per-robot accessor"
        kw["stl_hab"] = _Tagged(kw["stl_hab"], "shared", log)
        kw["stl_hab_for_robot_fn"] = lambda rid, _fn=fn: _Tagged(_fn(rid), str(rid), log)
        return orig_pp(self, *a, **kw)

    def est(model, x, y, **kw):
        hab_tags.append(getattr(kw["hab"], "tag", None))
        return orig_est(model, x, y, **kw)

    tg.TaskGenerator.periodic_patrolling = pp
    tg.estimate_stl_counterfactual_value = est
    try:
        m, loc = _run(params, keep_gen=True)
    finally:
        tg.TaskGenerator.periodic_patrolling = orig_pp
        tg.estimate_stl_counterfactual_value = orig_est
    return m, loc, log, hab_tags


def test_per_robot_B4_valuations_read_the_candidate_robots_field():
    m, loc, log, hab_tags = _per_robot_capture(
        _b4_params(t_end=240.0, planner_hab_mode="per_robot", neighbor_delay_s=120.0,
                   neighbor_drop_prob=0.3))
    meta = loc["taskgen"].stl_eval_meta
    assert hab_tags and len(hab_tags) == len(meta)
    assert hab_tags == [rid for _, rid, _ in meta]
    assert not [e for e in log if e[0] == "shared"]
    assert {e[0] for e in log} >= {rid for _, rid, _ in meta}


def test_per_robot_B5_scoring_reads_own_field_only():
    m, loc, log, _ = _per_robot_capture(
        _b5c_params(t_end=300.0, planner_hab_mode="per_robot", neighbor_delay_s=120.0,
                    neighbor_drop_prob=0.3))
    reads = [e for e in log if e[1] == "effectiveness"]
    assert reads, "B5 legacy_habituation scoring never read effectiveness"
    assert not [e for e in log if e[0] == "shared"]
    assert {e[0] for e in reads} <= {str(r) for r in loc["robots"]}
