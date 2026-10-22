"""Parameter building of the evaluation harness (run_plan_completion, run_plan_studies,
reproduce_acc_submission) and the confirmatory analysis.  No simulation is run."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

from experiments import analyze_plan_confirmatory as apc
from experiments import run_plan_completion as rpc
from experiments import run_plan_studies as rps

MU = 1e-4
NEW_B4_FLAGS = ("stl_forward_trajectory_correction", "stl_committed_schedule", "stl_queue_aware_lead",
                "stl_forecast_planner_update_model", "stl_strict_admission", "reservation_mode",
                "stl_valuation_mode", "stl_benefit_gate", "stl_binding_log_path")


def _diff(a: dict, b: dict) -> set:
    return {k for k in set(a) | set(b) if a.get(k, "<absent>") != b.get(k, "<absent>")}


# ---------------------------------------------------------------- PLAN_ENV / variants
def test_plan_env_contents():
    assert rpc.PLAN_ENV == {"estimator_mode": "legacy", "random_stream_mode": "coupled",
                            "truth_deterrence_memory": "complete", "stl_forecast_correction": True}


@pytest.mark.parametrize("hab_on", [True, False])
@pytest.mark.parametrize("mu", list(rpc.LOADS.values()))
def test_every_variant_resolves(mu, hab_on):
    for v in rpc.VARIANTS:
        p = rpc.build_params(v, hab_on, mu, None)
        assert p["mu_true"] == mu
        assert p["enable_habituation"] is hab_on
        for k in ("estimator_mode", "random_stream_mode", "truth_deterrence_memory"):
            assert p[k] == rpc.PLAN_ENV[k], (v, k)
        assert p["stl_forecast_correction"] is (v != "A")
        json.dumps(p, default=str)  # serializable for the run manifest


def test_old_rollout_variants_dropped():
    for old in ("D", "E", "D_adm", "E_adm", "D_cue_adm", "E_cue_adm"):
        assert old not in rpc.VARIANTS
        assert all(old not in (r, t) for r, t, _ in rpc.COMPARISONS)
        with pytest.raises(KeyError):
            rpc.build_params(old, True, MU, None)


def test_variant_A_is_submitted_B4_in_plan_env():
    ladder = rpc._ladder_params(rpc.LADDER_SYSTEMS["B4"], True, MU)
    a = rpc.build_params("A", True, MU, None)
    assert a["stl_forecast_correction"] is False
    assert _diff(ladder, a) <= {"estimator_mode", "random_stream_mode", "truth_deterrence_memory",
                                "stl_forecast_correction", "stl_shadow_overrides"}
    for k in NEW_B4_FLAGS:
        assert k not in a or a[k] == ladder.get(k), k


def test_variants_B_C_Cgate_chain():
    a = rpc.build_params("A", True, MU, None)
    b = rpc.build_params("B", True, MU, None)
    c = rpc.build_params("C", True, MU, None)
    g = rpc.build_params("C_gate", True, MU, None)
    for k in ("stl_forecast_correction", "stl_forward_trajectory_correction", "stl_committed_schedule",
              "stl_queue_aware_lead", "stl_forecast_planner_update_model"):
        assert b[k] is True and c[k] is True and g[k] is True
    assert _diff(a, b) == {"stl_forecast_correction", "stl_forward_trajectory_correction", "stl_committed_schedule",
                           "stl_queue_aware_lead", "stl_forecast_planner_update_model", "stl_shadow_overrides"}
    assert c["stl_valuation_mode"] == "integrated_exposure_eq3"
    assert _diff(b, c) == {"stl_valuation_mode", "stl_shadow_overrides"}
    assert _diff(c, g) == {"stl_strict_admission", "stl_benefit_gate", "reservation_mode"}
    assert g["stl_strict_admission"] is True and g["stl_benefit_gate"] == 0.0 and g["reservation_mode"] == "ceiling"
    assert g["dispatch_policy"] == "res"  # the ceiling is defined for res only


def test_plan_variants():
    ladder_b5 = rpc._ladder_params(rpc.LADDER_SYSTEMS["B5"], True, MU)
    b5c = rpc.build_params("B5_c", True, MU, None)
    assert _diff(ladder_b5, b5c) <= set(rpc.PLAN_ENV)
    b1c = rpc.build_params("B1_c", True, MU, None)
    assert _diff(rpc._ladder_params(rpc.LADDER_SYSTEMS["B1"], True, MU), b1c) <= set(rpc.PLAN_ENV)
    d = rpc.build_params("D_plan", True, MU, None)
    e = rpc.build_params("E_plan", True, MU, None)
    cp = rpc.build_params("C_plan", True, MU, None)
    fl = rpc.build_params("E_plan_floor", True, MU, None)
    tr = rpc.build_params("E_plan_tr", True, MU, None)
    for p in (d, e, cp, fl, tr):
        assert p["planner_procedure"] == "plan" and p["plan_gate_se_multiplier"] == 2.0
        assert p["plan_eps_gate"] == 0.0 and p["plan_compute_budget_s"] >= 1e9
    assert d["plan_service_protection"] is False and e["plan_service_protection"] is True
    assert cp["plan_service_protection"] is False and cp["plan_valuation"] == "one_intervention"
    assert _diff(d, cp) == {"plan_valuation"}
    assert _diff(e, fl) == {"plan_eta_floor"} and fl["plan_eta_floor"] == 0.4
    thr = json.loads(rpc.TIMED_RECOVERY_FILE.read_text())
    assert tr["plan_E_high"] == thr["E_high"] and tr["plan_E_low"] == thr["E_low"]
    assert tr["plan_T_response_s"] == thr["T_response_s"]
    assert _diff(e, tr) == set(rpc.PLAN_TR_KEYS)
    with pytest.raises(ValueError):
        rpc.build_params("E_plan", True, MU, None, {"plan_E_high": 1.0})


def test_legacy_variants_are_pure_ladder():
    for v, sysname in (("B1", "B1_greedy_fixedcue"), ("B5", "B5_greedy_habcue"), ("B4", "B4_res_stl_full_multicue")):
        ladder = rpc._ladder_params(sysname, True, MU)
        p = rpc.build_params(v, True, MU, None)
        assert _diff(ladder, p) == set()
        assert p.get("random_stream_mode", "legacy") == "legacy"
        assert p.get("truth_deterrence_memory", "window200") == "window200"


# ---------------------------------------------------------------- comparisons / metrics
def test_comparisons_cover_the_progression_and_are_matched():
    pairs = {(r, t) for r, t, _ in rpc.COMPARISONS}
    assert pairs == {("A", "B"), ("B", "C"), ("C", "C_gate"), ("C_plan", "D_plan"), ("C_gate", "C_plan"),
                     ("D_plan", "E_plan"), ("B5_c", "E_plan"), ("E_plan", "E_plan_tr"), ("E_plan", "E_plan_floor"),
                     ("B1_c", "B5_c"), ("B5_c", "A")}
    for r, t in pairs:
        assert r in rpc.VARIANTS and t in rpc.VARIANTS
        pr, pt = rpc.build_params(r, True, MU, None), rpc.build_params(t, True, MU, None)
        for k in ("random_stream_mode", "truth_deterrence_memory", "estimator_mode", "mu_true", "T_end",
                  "enable_habituation", "habituation_kappa"):
            assert pr.get(k) == pt.get(k), (r, t, k)


def test_paired_uses_only_common_finite_seeds():
    rows = [{"variant": "B5_c", "habituation_condition": "hab_on", "seed": s, "m": float(s)} for s in (1, 2, 3)]
    rows += [{"variant": "E_plan", "habituation_condition": "hab_on", "seed": s, "m": v}
             for s, v in ((2, 5.0), (3, float("nan")), (4, 1.0))]
    a, b = rpc.paired(rows, "B5_c", "E_plan", "m")
    assert a.tolist() == [2.0] and b.tolist() == [5.0]


def test_report_metrics_include_service_and_mechanism():
    for m in ("reactive_miss_fraction", "reactive_unfinished_total", "reactive_age_at_completion_p90_s",
              "motion_time_deviation_s", "eta_truth_at_application_deviation_mean",
              "cue_reuse_all_interval_mean_s", "plan_runtime_p99_s", "plan_timeout_rate",
              "plan_oracle_kendall_tau_mean", "plan_F0_protected_missed", "plan_dev_travel_err_mean_s"):
        assert m in rpc.REPORT_METRICS, m


def test_run_job_records_scalars_and_burst(monkeypatch):
    import DeterrentSystem as ds

    def fake(**params):
        yield {"metrics_compact": {"value_weighted_exposure": 3.0, "reactive_miss_fraction": 0.5,
                                   "planner_hab_mode": "shared", "outcome_windows": [{"a": 1}],
                                   "big_dict": {"x": 1}}}
    monkeypatch.setattr(ds, "run_simulation_frames_persistent", fake)
    params = rpc.build_params("B5_c", True, MU, 60.0, rps.burst_extra(300))
    row = rpc.run_job({"system": "B5_c_hab_on", "variant": "B5_c", "habituation_condition": "hab_on",
                       "seed": 300, "params": params})
    assert row["value_weighted_exposure"] == 3.0 and row["planner_hab_mode"] == "shared"
    assert row["outcome_windows"] == [{"a": 1}] and "big_dict" not in row
    assert row["arrival_burst_start_s"] == rps.burst_start_s(300)
    assert row["arrival_burst_duration_s"] == 300.0 and row["arrival_burst_factor"] == 2.0


def test_wait_for_memory_polls_until_enough(monkeypatch):
    seq = iter([4.0, 8.0, 20.0])
    monkeypatch.setattr(rpc, "free_memory_gb", lambda: next(seq))
    slept = []
    monkeypatch.setattr(rpc.time, "sleep", lambda s: slept.append(s))
    assert rpc.wait_for_memory(12.0, 300.0) == 20.0
    assert slept == [300.0, 300.0]


class _FakeProc:
    def __init__(self, job, events):
        self.job, self.events, self.polls, self.returncode = job, events, 0, None

    def poll(self):
        self.polls += 1
        if self.polls >= 2:
            Path(self.job["raw_json"]).write_text("{}")
            self.returncode = 0
            return 0
        return None


@pytest.mark.parametrize("overlap", [False, True])
def test_scheduler_limits_memory_checks_and_order(tmp_path, monkeypatch, overlap):
    events, mem_checks, running = [], [], {"ordinary": 0, "plan": 0, "max_ordinary": 0, "max_plan": 0}
    procs = []

    def fake_launch(job):
        kind = "plan" if rpc.is_plan_job(job["params"]) else "ordinary"
        events.append(kind)
        p = _FakeProc(job, events)
        procs.append((kind, p))
        return p, open(tmp_path / f"{len(procs)}.log", "w"), str(tmp_path / f"{len(procs)}.pkl")

    monkeypatch.setattr(rpc, "_launch", fake_launch)
    monkeypatch.setattr(rpc, "wait_for_memory", lambda *a, **k: mem_checks.append(1) or 20.0)
    monkeypatch.setattr(rpc, "free_memory_gb", lambda: 20.0)
    monkeypatch.setattr(rpc.time, "sleep", lambda s: None)
    jobs = []
    for i in range(3):
        jobs.append({"system": f"o{i}", "seed": i, "params": {}, "raw_json": str(tmp_path / f"o{i}.json")})
        jobs.append({"system": f"p{i}", "seed": i, "params": {"planner_procedure": "plan"},
                     "raw_json": str(tmp_path / f"p{i}.json")})
    (tmp_path / "o2.json").write_text("{}")  # already done: resumable, not rerun
    res = rpc.execute_jobs(jobs, max_workers=2, plan_concurrency=2, plan_stagger_s=0.0, overlap=overlap)
    assert res["done"] == 5 and res["failed"] == []
    assert len(mem_checks) == 5          # a memory check before every launch
    if not overlap:
        assert events == ["ordinary", "ordinary", "plan", "plan", "plan"]
    else:
        assert events[:2] == ["ordinary", "plan"]


# ---------------------------------------------------------------- studies
class _Args:
    def __init__(self, root):
        self.root = str(root)
        self.tr_loads = ""
        self.tr_seeds = ""
        self.binding_log_fraction = None


@pytest.fixture(scope="module")
def jobs_by_study(tmp_path_factory):
    root = tmp_path_factory.mktemp("studies")
    args = _Args(root)
    return root, {name: rps.collect_jobs(rps.STUDIES[name](args), root) for name in rps.STUDIES}


def _cells(jobs):
    out = {}
    for j in jobs:
        out.setdefault(j["cell"], []).append(j)
    return out


def test_study_sizes_and_matched_seeds(jobs_by_study):
    _, jobs = jobs_by_study
    expect = {  # study -> (cells, variants per cell, seeds)
        "confirmatory": (3, 9, list(range(300, 330))),
        "zero_hab": (3, 3, list(range(300, 330))),
        "mismatch": (5, 2, list(range(300, 310))),
        "neighbor": (6, 2, list(range(300, 310))),
        "timeout": (2, 1, list(range(200, 210))),
        "disturbance": (2, 2, list(range(300, 310))),
        "floor": (3, 1, list(range(300, 310))),
    }
    for name, (n_cells, n_var, seeds) in expect.items():
        cells = _cells(jobs[name])
        assert len(cells) == n_cells, name
        for cell, js in cells.items():
            by_var = {}
            for j in js:
                by_var.setdefault(j["variant"], []).append(j["seed"])
            assert len(by_var) == n_var, (name, cell)
            for v, s in by_var.items():
                assert sorted(s) == seeds, (name, cell, v)  # same seeds for every system
    assert jobs["timed_recovery"] == []  # size undecided: nothing scheduled
    assert all(not j["params"]["enable_habituation"] for j in jobs["zero_hab"])


def test_mismatch_and_neighbor_params(jobs_by_study):
    _, jobs = jobs_by_study
    kap = sorted({j["params"]["truth_habituation_kappa"] for j in jobs["mismatch"]})
    assert kap == [0.10, 0.25, 0.50, 0.75, 0.90]
    assert {j["params"]["planner_habituation_kappa"] for j in jobs["mismatch"]} == {0.50}
    assert {j["params"]["mu_true"] for j in jobs["mismatch"] + jobs["neighbor"]} == {1e-4}
    combos = {(j["params"]["neighbor_delay_s"], j["params"]["neighbor_drop_prob"]) for j in jobs["neighbor"]}
    assert combos == {(30.0, 0.0), (120.0, 0.0), (300.0, 0.0), (0.0, 0.1), (0.0, 0.3), (0.0, 0.5)}
    assert {j["params"]["planner_hab_mode"] for j in jobs["neighbor"]} == {"per_robot"}


def test_timeout_and_floor_and_disturbance_reuse_identical_params(jobs_by_study, tmp_path):
    root, jobs = jobs_by_study
    budget = [j for j in jobs["timeout"] if j["cell"] == "budget_45s"]
    assert {j["params"]["plan_compute_budget_s"] for j in budget} == {45.0}
    conf = {(j["cell"], j["variant"], j["seed"]): j["params"] for j in jobs["confirmatory"]}
    for j in jobs["floor"]:
        ref = conf[(j["cell"], "E_plan", j["seed"])]
        assert _diff(ref, j["params"]) == {"plan_eta_floor"}
    for j in jobs["disturbance"]:
        ref = conf[("heavy", j["variant"], j["seed"])]
        assert _diff(ref, j["params"]) in ({"travel_speed_error"}, {"arrival_burst"})


def test_arrival_burst_seed_only_and_identical_across_variants(jobs_by_study):
    _, jobs = jobs_by_study
    burst = [j for j in jobs["disturbance"] if "arrival_burst" in j["params"]]
    by_seed = {}
    for j in burst:
        b = j["params"]["arrival_burst"]
        assert b["duration_s"] == 300.0 and b["factor"] == 2.0
        assert 300.0 <= b["start_s"] <= 1200.0
        by_seed.setdefault(j["seed"], set()).add(b["start_s"])
    assert all(len(v) == 1 for v in by_seed.values())  # B5_c and E_plan share the start
    starts = [next(iter(v)) for v in by_seed.values()]
    assert len(set(starts)) == len(starts)  # different seeds, different starts
    assert rps.burst_start_s(305) == rps.burst_start_s(305)
    # same value whichever variant's params are built for the seed
    a = rpc.build_params("B5_c", True, MU, None, rps.burst_extra(301))["arrival_burst"]
    b = rpc.build_params("E_plan", True, MU, None, rps.burst_extra(301))["arrival_burst"]
    assert a == b


def test_persistent_design(jobs_by_study):
    root, jobs = jobs_by_study
    js = jobs["persistent"]
    src = [j for j in js if j["cell"].startswith("depletion_source")]
    main = [j for j in js if not j["cell"].startswith("depletion_source")]
    assert {j["stage"] for j in src} == {0} and {j["stage"] for j in main} == {1}
    for j in src:
        assert j["variant"] == "B5_c" and j["params"]["T_end"] == 1800.0
        assert j["params"]["habituation_T_rec_s"] == 1800.0
    saved = {(j["params"]["mu_true"], j["seed"]): j["params"]["save_final_hab_state_path"] for j in src}
    assert len(_cells(main)) == 4
    for j in main:
        p = j["params"]
        assert p["T_end"] == 5400.0 and p["habituation_T_rec_s"] == 1800.0
        assert p["outcome_window_boundaries_s"] == [1800.0] and p["mu_step_time_s"] == 2700.0
        assert math.isclose(p["mu_true"] * p["mu_step_factor"], 1e-4 if p["mu_true"] == 2e-5 else 2e-5)
        if j["cell"].startswith("depleted"):
            assert p["initial_hab_state_path"] == saved[(p["mu_true"], j["seed"])]
        else:
            assert "initial_hab_state_path" not in p or p["initial_hab_state_path"] is None
    assert {j["variant"] for j in main} == {"B5_c", "D_plan", "E_plan"}
    ordered = rps.order_jobs(js, rps.DEFAULT_ORDER)
    assert all(j["stage"] == 0 for j in ordered[:len(src)])


# ---------------------------------------------------------------- confirmatory analysis
def test_holm_bootstrap_noninferiority():
    rng = np.random.default_rng(0)
    tests = [
        {"kind": "wilcoxon", "p": 0.001},
        {"kind": "ni_bootstrap", "diffs": rng.normal(-0.02, 0.01, 30)},   # clearly noninferior
        {"kind": "ni_bootstrap", "diffs": rng.normal(0.10, 0.01, 30)},    # clearly not
        {"kind": "wilcoxon", "p": 0.04},
    ]
    for t in tests:
        if t["kind"] == "ni_bootstrap":
            t["p"] = apc.bootstrap_ni_p(t["diffs"])
    apc.holm_decisions(tests)
    assert tests[0]["reject"] and tests[1]["reject"]
    assert not tests[2]["reject"]
    assert not tests[3]["reject"]  # step-down stopped at the non-inferiority failure
    assert tests[1]["ub_at_holm_level"] < apc.NI_MARGIN
    # the bound is taken at the hypothesis' own Holm level (alpha / (m - k))
    k = tests[1]["holm_step"] - 1
    assert math.isclose(tests[1]["holm_level"], 0.05 / (4 - k))
    assert math.isclose(tests[1]["ub_at_holm_level"], apc.bootstrap_upper(tests[1]["diffs"], tests[1]["holm_level"]))


def test_confirmatory_family_end_to_end(tmp_path):
    rng = np.random.default_rng(1)
    dirs = {}
    for load in ("spare", "heavy", "overload"):
        raw = tmp_path / load / "raw"
        raw.mkdir(parents=True)
        for s in range(300, 330):
            base = 1000.0 + rng.normal(0, 10)
            for v, vwe, miss in (("B5_c", base, 0.3), ("E_plan", base - 50 + rng.normal(0, 5), 0.3 + rng.normal(0, 0.01))):
                (raw / f"{v}_hab_on_seed_{s}.json").write_text(json.dumps(
                    {"variant": v, "habituation_condition": "hab_on", "seed": s,
                     "value_weighted_exposure": vwe, "reactive_miss_fraction": miss}))
        dirs[load] = tmp_path / load
    tests = apc.run_family(treatment="E_plan", reference="B5_c", dirs=dirs, expected_n=30, out=tmp_path / "out")
    assert len(tests) == 6 and all(t["reject"] for t in tests)
    assert (tmp_path / "out" / "confirmatory_tests.md").exists()


# ---------------------------------------------------------------- Section 7 reproduction
def test_reproduction_jobs_use_original_legacy_setup(tmp_path):
    from experiments import reproduce_acc_submission as rep
    jobs = rep.build_jobs(tmp_path, [300, 301])
    assert len(jobs) == 4 * 3 * 2
    for j in jobs:
        p = j["params"]
        assert j["variant"] in ("B1", "B4", "B5")
        assert p.get("random_stream_mode", "legacy") == "legacy"
        assert p.get("truth_deterrence_memory", "window200") == "window200"
        assert p.get("estimator_mode", "legacy") == "legacy"
        assert not p.get("stl_forecast_correction", False)
        assert "planner_procedure" not in p
