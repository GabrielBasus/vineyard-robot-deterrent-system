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
                                "stl_forecast_correction", "stl_shadow_overrides", "stl_shadow_full_section2"}
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
                           "stl_queue_aware_lead", "stl_forecast_planner_update_model", "stl_shadow_overrides",
                           "stl_shadow_full_section2"}
    assert c["stl_valuation_mode"] == "integrated_exposure_eq3"
    assert _diff(b, c) == {"stl_valuation_mode", "stl_shadow_overrides", "stl_shadow_full_section2"}
    # no ceiling anywhere (audit round 2026-10-22): C_gate differs from C by the gate only
    assert _diff(c, g) == {"stl_strict_admission", "stl_benefit_gate"}
    assert g["stl_strict_admission"] is True and g["stl_benefit_gate"] == 0.0
    assert "ceiling" not in json.dumps(g)


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
                     ("C", "D_plan"),
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
              "plan_prop2_kendall_tau_mean", "plan_F0_protected_missed", "plan_dev_travel_err_mean_s"):
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
        "zero_hab": (3, 3, list(range(300, 310))),
        "mismatch": (4, 2, list(range(300, 310))),   # kappa 0.50 cell reuses confirmatory/heavy
        "timed_recovery": (3, 1, list(range(300, 310))),
        "neighbor": (7, 2, list(range(300, 310))),   # 6 delay/drop cells + per_robot reference
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
    assert {j["variant"] for j in jobs["timed_recovery"]} == {"E_plan_tr"}
    assert all(not j["params"]["enable_habituation"] for j in jobs["zero_hab"])


def test_mismatch_and_neighbor_params(jobs_by_study):
    _, jobs = jobs_by_study
    kap = sorted({j["params"]["truth_habituation_kappa"] for j in jobs["mismatch"]})
    assert kap == [0.10, 0.25, 0.75, 0.90]   # 0.50 is not rerun
    assert {j["params"]["planner_habituation_kappa"] for j in jobs["mismatch"]} == {0.50}
    assert {j["params"]["mu_true"] for j in jobs["mismatch"] + jobs["neighbor"]} == {1e-4}
    combos = {(j["params"]["neighbor_delay_s"], j["params"]["neighbor_drop_prob"]) for j in jobs["neighbor"]}
    assert combos == {(0.0, 0.0), (30.0, 0.0), (120.0, 0.0), (300.0, 0.0), (0.0, 0.1), (0.0, 0.3), (0.0, 0.5)}
    assert {j["params"]["planner_hab_mode"] for j in jobs["neighbor"]} == {"per_robot"}


def test_mismatch_kappa_050_reuses_confirmatory_heavy_with_identical_effective_params(jobs_by_study, tmp_path):
    root, jobs = jobs_by_study
    st = rps.STUDIES["mismatch"](_Args(root))
    cell = next(c for c in st.cells if c.name == "env_kappa_0p50")
    assert cell.variants == []
    assert sorted(cell.reuse) == [("confirmatory/heavy", "B5_c", "B5_c"), ("confirmatory/heavy", "E_plan", "E_plan")]
    conf = {(j["cell"], j["variant"], j["seed"]): j["params"] for j in jobs["confirmatory"]}
    import inspect
    import DeterrentSystem as ds
    src = inspect.getsource(ds.run_simulation_frames_persistent)
    # the simulator resolves None to habituation_kappa for truth and planner
    assert 'habituation_kappa if truth_habituation_kappa in (None, "") else truth_habituation_kappa' in src
    assert 'habituation_kappa if planner_habituation_kappa in (None, "") else planner_habituation_kappa' in src

    def eff(p):
        q = dict(p)
        for k in ("truth_habituation_kappa", "planner_habituation_kappa"):
            q[k] = q["habituation_kappa"] if q.get(k) in (None, "") else q[k]
        return q

    for v in ("B5_c", "E_plan"):
        mism = rpc.build_params(v, True, rpc.LOADS["heavy"], None, rps.mismatch_extra(0.50))
        for seed in rps.EVAL_SEEDS_10:
            assert _diff(eff(conf[("heavy", v, seed)]), eff(mism)) == set(), (v, seed)
    # the analysis reads the confirmatory runs, restricted to seeds 300-309
    raw = root / "confirmatory" / "heavy" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for seed in (300, 315):
        for v in ("B5_c", "E_plan"):
            (raw / f"{v}_hab_on_seed_{seed}.json").write_text(json.dumps(
                {"variant": v, "habituation_condition": "hab_on", "seed": seed, "value_weighted_exposure": 1.0}))
    rows = rps.cell_rows(root, st, cell)
    assert sorted((r["variant"], r["seed"]) for r in rows) == [("B5_c", 300), ("E_plan", 300)]
    for f in raw.glob("*.json"):
        f.unlink()


def test_binding_log_every_decision_for_A_and_B(jobs_by_study):
    _, jobs = jobs_by_study
    for j in jobs["confirmatory"]:
        p = j["params"]
        if j["variant"] in ("A", "B"):
            assert p["stl_binding_log_fraction"] == 1.0
            assert p["stl_binding_log_path"].endswith(f"{j['system']}_seed_{j['seed']}_binding.jsonl")
        else:
            assert "stl_binding_log_path" not in p


def test_overlap_default_for_all():
    assert rps.resolve_overlap("all", None) is True
    assert rps.resolve_overlap("confirmatory", None) is False
    assert rps.resolve_overlap("all", False) is False
    assert rps.resolve_overlap("confirmatory", True) is True


def test_timed_recovery_study(jobs_by_study):
    _, jobs = jobs_by_study
    thr = rpc.load_timed_recovery()
    for j in jobs["timed_recovery"]:
        for k, v in thr.items():
            assert j["params"][k] == v
    st = rps.STUDIES["timed_recovery"](_Args(jobs_by_study[0]))
    assert all(c.reuse == [(f"confirmatory/{c.name}", "E_plan", "E_plan")] for c in st.cells)


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
    jobs = rep.build_jobs(tmp_path)
    main = [j for j in jobs if not j["cell"].startswith("table_vii")]
    t7 = [j for j in jobs if j["cell"].startswith("table_vii")]
    assert len(main) == 2 * 4 * 3 * 30 and len(t7) == 3 * 3 * 10
    assert {j["seed"] for j in main} == set(range(125, 155)) | set(range(300, 330))
    assert {j["seed"] for j in t7} == set(range(125, 135))
    assert {j["variant"] for j in main} == {"B1", "B4", "B5"}
    assert {j["variant"] for j in t7} == {"B1", "B3", "B4"}
    for j in jobs:
        p = j["params"]
        assert p.get("random_stream_mode", "legacy") == "legacy"
        assert p.get("truth_deterrence_memory", "window200") == "window200"
        assert p.get("estimator_mode", "legacy") == "legacy"
        assert not p.get("stl_forecast_correction", False)
        assert "planner_procedure" not in p
    assert {j["params"]["enable_habituation"] for j in t7} == {True}
    assert {j["params"]["habituation_kappa"] for j in t7} == {0.5}


def _testbench():
    from experiments import reproduce_acc_submission as rep
    tb = rep.find_testbench()
    if tb is None or not (tb / "habituation_stl_joint_sweep").exists():
        pytest.skip("archived ACC results not available")
    return rep, tb


def test_table_vii_archive_matches_paper_exactly():
    rep, tb = _testbench()
    for cell, _load, _mu, src in rep.TABLE7_CELLS:
        rows = rep.archive_rows(tb / "habituation_stl_joint_sweep" / src / "per_run_metrics.csv", rep.TABLE7_SYSTEMS)
        assert sorted({r["seed"] for r in rows}) == rep.TABLE7_SEEDS
        v = rep.table7_values(rows)
        for k, paper in rep.PAPER_TABLE_VII[cell].items():
            nd = 2 if k == "travel" else 1
            assert round(v[k], nd) == paper, (cell, k, v[k], paper)


def test_table_vii_design_matches_joint_sweep_manifest():
    rep, tb = _testbench()
    import sys as _sys
    import experiments.run_habituation_stl_production_ladder as ladder
    for _cell, _load, mu, src in rep.TABLE7_CELLS:
        man = json.loads((tb / "habituation_stl_joint_sweep" / src / "ladder_manifest.json").read_text())["args"]
        saved = _sys.argv
        try:
            _sys.argv = ["ladder", *rpc.PAPER_LADDER_ARGV, "--mu-true", repr(mu)]
            ours = vars(ladder.parse_args())
        finally:
            _sys.argv = saved
        skip = {"outdir", "num_runs", "seed_start", "max_workers", "systems", "merge_existing_raw"}
        compared = 0
        for k, v in man.items():
            if k in skip or k not in ours:
                continue
            assert ours[k] == v, (src, k, ours[k], v)
            compared += 1
        assert compared > 20
        assert man["seed_start"] == 125 and man["num_runs"] == 10
        assert "B3_res_stl_nohab_multicue" in man["systems"]


def test_table_i_and_iv_archive_match_paper():
    rep, tb = _testbench()
    for cell, load, _mu, hab_on in rep.CELLS:
        rows = rep.archive_rows(tb / "acc_submission" / "data" / rep.ARCHIVE_FILES[load], rep.SYSTEMS,
                                "hab_on" if hab_on else "hab_off")
        for s in ("B4", "B5"):
            if (cell, s) in rep.PAPER_VS_B1:
                m, lo, hi, n = rep.paper_table1_interval(rows, s)
                assert n == 30
                assert tuple(round(x, 1) + 0.0 for x in (m, lo, hi)) == \
                    tuple(x + 0.0 for x in rep.PAPER_VS_B1[(cell, s)])
        if cell in rep.PAPER_B4_B5:
            a, b = rep._paired(rows, "B5", "B4", "value_weighted_exposure")
            d = b - a
            pct = 100 * d.mean() / rep._mean(rows, "B1", "value_weighted_exposure")
            paper = rep.PAPER_B4_B5[cell]
            assert round(pct, 1) == paper[0]
            assert f"{int(np.sum(d < 0))}/{d.size}" == paper[2]


# ======================================================================== 2026-10-22 audit round
RESERVATION_KEYS = ("reservation_mode", "reservation_fraction", "reservation_window_s")


def test_reservation_b4_floor_and_none_for_plan_variants():
    """Final user decision 2026-10-22: B4-based variants keep the B4 floor; the B5-based plan
    variants carry NO reservation parameter; no ceiling anywhere."""
    import inspect
    import DeterrentSystem as ds
    sig = inspect.signature(ds.run_simulation_frames_persistent)
    assert sig.parameters["reservation_mode"].default == "floor"   # B4 variants inherit the floor
    for v in rpc.VARIANTS:
        assert "ceiling" not in json.dumps(rpc.build_params(v, True, MU, None)), v
    for v in ("A", "B", "C", "C_gate"):
        p = rpc.build_params(v, True, MU, None)
        assert p["dispatch_policy"] == "res" and p["reservation_fraction"] == 0.25
        assert p["reservation_window_s"] == 600.0 and p.get("reservation_mode", "floor") == "floor"
    for v in ("C_plan", "D_plan", "E_plan", "E_plan_tr", "E_plan_floor"):
        p = rpc.build_params(v, True, MU, None)
        assert not any(k in p for k in RESERVATION_KEYS), v
        assert not any(k in rpc._PLAN for k in RESERVATION_KEYS)
        assert p["dispatch_policy"] == "unc"
    assert not hasattr(rpc, "RESERVATION_FLOOR") and not hasattr(rpc, "TODO_SIM_PLAN_FLOOR_FLAGS")


def test_c_plan_final_params_and_no_stale_todo():
    cp = rpc.build_params("C_plan", True, MU, None)
    ladder = rpc._ladder_params(rpc.LADDER_SYSTEMS["B5"], True, MU)
    want = {**ladder, **rpc.PLAN_ENV, **rpc._PLAN, "plan_service_protection": False,
            "plan_valuation": "one_intervention", "mu_true": MU}
    assert _diff(want, cp) == set()
    src = Path(rpc.__file__).read_text(encoding="utf-8")
    assert "TODO(FU-1)" not in src


def test_variant_A_dual_shadow():
    a = rpc.build_params("A", True, MU, None)
    assert a["stl_shadow_overrides"] == {"forecast_correction": True}     # forecast-only shadow kept
    assert rpc.SHADOW_B_FULL_SECTION2 == rpc._SECTION2                    # full-set shadow content
    assert set(rpc.SHADOW_B_FULL_SECTION2) == {
        "stl_forecast_correction", "stl_forward_trajectory_correction", "stl_committed_schedule",
        "stl_queue_aware_lead", "stl_forecast_planner_update_model"}
    assert all(v is True for v in rpc.SHADOW_B_FULL_SECTION2.values())
    assert a["stl_shadow_full_section2"] == rpc.SHADOW_B_FULL_SECTION2
    b = rpc.build_params("B", True, MU, None)
    assert b["stl_shadow_overrides"] == {"forecast_correction": False}
    assert b["stl_shadow_full_section2"] == {k: False for k in rpc._SECTION2}
    for v in ("C", "C_gate") + tuple(rpc.PLAN_VARIANTS):
        assert "stl_shadow_full_section2" not in rpc.build_params(v, True, MU, None)
    for kind in ("full", "forecast"):
        for m in ("top1_agree_fraction", "kendall_tau_mean", "masked_group_fraction", "compared_groups"):
            for suf in ("", "_first_eval"):
                assert f"stl_shadow_{kind}_{m}{suf}" in rpc.REPORT_METRICS
    assert not hasattr(rpc, "TODO_SIM_A_FULL_SHADOW")


def test_full_shadow_param_accepted_by_simulator():
    import inspect
    import DeterrentSystem as ds
    assert "stl_shadow_full_section2" in inspect.signature(ds.run_simulation_frames_persistent).parameters


def test_report_metrics_audit_round():
    from habituation_stl import plan_procedure as pp
    for m in ("stl_travel_recovery_gap_mean", "stl_travel_recovery_gap_p90", "stl_travel_recovery_gap_max",
              "stl_travel_recovery_gap_rel_mean", "plan_exact_u_tie_count"):
        assert m in rpc.REPORT_METRICS, m
    for m in ("plan_oracle_decisions", "plan_oracle_wall_s_total"):
        assert m in rpc.REPORT_METRICS, m
    reasons = set(rpc.REJECTION_REASONS)
    assert reasons == set(pp.REJECTION_REASONS) | {"feasibility", "obligation"} and "ceiling" not in reasons
    for r in reasons:
        assert f"plan_rejected_{r}" in rpc.REPORT_METRICS and f"plan_rejected_{r}_per_decision_mean" in rpc.REPORT_METRICS
    assert not any("ceiling" in m for m in rpc.REPORT_METRICS)
    assert rpc.PROP2_PRIMARY_METRICS == [
        "plan_prop2_sign_agree_fraction", "plan_prop2_sign_agree_n", "plan_prop2_kendall_tau_mean",
        "plan_prop2_kendall_tau_median", "plan_prop2_kendall_tau_n", "plan_prop2_admitted_oracle_U_positive_fraction",
        "plan_prop2_admitted_oracle_n"]
    for m in rpc.PROP2_SECONDARY_METRICS:
        assert m.endswith("_raw_units") or m in ("plan_pred_err_J0_rel_mean", "plan_realized_minus_one_intervention_J_windows")
    for m in ("plan_realized_minus_pred_mean_raw_units", "plan_oracle_J0_se_mean_raw_units",
              "plan_oracle_U_se_mean_raw_units", "plan_oracle_admitted_U_oracle_mean_raw_units",
              "plan_realized_minus_one_intervention_J_mean_raw_units"):
        assert m in rpc.PROP2_SECONDARY_METRICS
    for m in ("plan_pr_prop2_sign_agree_fraction_robot_mean", "plan_pr_prop2_kendall_tau_mean_robot_spread_sd",
              "plan_pr_realized_minus_pred_spread_range_raw_units"):
        assert m in rpc.PER_ROBOT_METRICS
    for m in rpc.PROP2_PRIMARY_METRICS:
        assert rpc.metric_group(m).startswith("Prop. 2 PRIMARY")
    for m in rpc.PROP2_SECONDARY_METRICS:
        assert rpc.metric_group(m).startswith("Prop. 2 secondary")
    assert len(set(rpc.REPORT_METRICS)) == len(rpc.REPORT_METRICS)


def test_expand_metrics_raw_units_and_per_robot():
    rows = [{"plan_new_err_raw_units": 1.0, "plan_pr_prop2_sign_agree_fraction_r0": 2.0, "x": 1}]
    base = ["value_weighted_exposure"]
    assert rpc.expand_metrics(base, rows) == base + ["plan_new_err_raw_units"]
    pr = rpc.expand_metrics(base, rows, per_robot=True)
    assert "plan_pr_prop2_sign_agree_fraction_r0" in pr and all(m in pr for m in rpc.PER_ROBOT_METRICS)
    assert rpc.metric_group("plan_new_err_raw_units").startswith("Prop. 2 secondary")
    assert rpc.metric_group("plan_pr_prop2_sign_agree_fraction_r0") == "Prop. 2 per robot"


def _rows(variants, seeds, **vals):
    out = []
    for v in variants:
        for s in seeds:
            r = {"variant": v, "habituation_condition": "hab_on", "seed": s,
                 "value_weighted_exposure": 100.0 + s + (0 if v == "B5_c" else -10),
                 "reactive_miss_fraction": 0.30 + (0 if v == "B5_c" else 0.01)}
            r.update({k: f(v, s) for k, f in vals.items()})
            out.append(r)
    return out


def test_paired_detail_reports_dropped_seeds_and_reasons():
    rows = _rows(["B5_c"], [1, 2, 3]) + _rows(["E_plan"], [2, 3, 4])
    rows[2]["m"] = float("nan")
    for r in rows:
        r.setdefault("m", 1.0)
    d = rpc.paired_detail(rows, "B5_c", "E_plan", "m", expected_seeds=[1, 2, 3, 4, 5])
    assert d["seeds"] == [2]
    assert d["dropped"] == [{"seed": 1, "reason": "no E_plan run"},
                            {"seed": 3, "reason": "B5_c value not finite"},
                            {"seed": 4, "reason": "no B5_c run"},
                            {"seed": 5, "reason": "no B5_c run; no E_plan run"}]


def test_analyze_errors_on_missing_seeds_by_default():
    comps = [("B5_c", "E_plan", "E vs B5")]
    rows = _rows(["B5_c"], [1, 2, 3]) + _rows(["E_plan"], [1, 2])
    with pytest.raises(rpc.MissingSeedsError, match="E_plan"):
        rpc.analyze(rows, None, "hab_on", comps, ["value_weighted_exposure"], expected_seeds=[1, 2, 3])
    st = rpc.analyze(rows, None, "hab_on", comps, ["value_weighted_exposure"], expected_seeds=[1, 2, 3],
                     allow_missing=True)
    assert st[0]["n"] == 2 and st[0]["dropped_seeds"] == "3: no E_plan run" and st[0]["n_dropped"] == 1
    # final decision 2026-10-22: a non-finite value of a planned seed in ANY reported metric is
    # an error; with the flag the seed is dropped and listed with its reason
    rows = _rows(["B5_c", "E_plan"], [1, 2, 3], eta=lambda v, s: float("nan") if s == 2 else 0.5)
    with pytest.raises(rpc.MissingSeedsError, match="eta"):
        rpc.analyze(rows, None, "hab_on", comps, ["eta"], expected_seeds=[1, 2, 3])
    st = rpc.analyze(rows, None, "hab_on", comps, ["eta"], expected_seeds=[1, 2, 3], allow_missing=True)
    assert st[0]["dropped_seeds"] == "2: B5_c value not finite; E_plan value not finite"
    rows[0]["reactive_miss_fraction"] = float("nan")
    with pytest.raises(rpc.MissingSeedsError, match="reactive_miss_fraction"):
        rpc.analyze(rows, None, "hab_on", comps, ["reactive_miss_fraction"], expected_seeds=[1, 2, 3])
    # a metric a system does not report at all (no finite value in any run) is not compared
    rows = _rows(["B5_c", "E_plan"], [1, 2, 3], plan_x=lambda v, s: 1.0 if v == "E_plan" else float("nan"))
    assert rpc.analyze(rows, None, "hab_on", comps, ["plan_x"], expected_seeds=[1, 2, 3]) == []
    # the trade-off and the difference of differences also error
    rows = _rows(["B5_c", "E_plan"], [1, 2, 3])
    rows[1]["value_weighted_exposure"] = float("nan")
    with pytest.raises(rpc.MissingSeedsError):
        rpc.tradeoff(rows, "hab_on", expected_seeds=[1, 2, 3])
    assert rpc.tradeoff(rows, "hab_on", expected_seeds=[1, 2, 3], allow_missing=True)[0]["n_exposure"] == 2


def test_analyze_refuses_mixed_commits():
    comps = [("B5_c", "E_plan", "E vs B5")]
    rows = _rows(["B5_c", "E_plan"], [1, 2])
    for r in rows:
        r.update({"git_commit": "aaa", "git_dirty": False, "git_diff_sha1": ""})
    rpc.analyze(rows, None, "hab_on", comps, ["value_weighted_exposure"], expected_seeds=[1, 2])
    rows[-1]["git_commit"] = "bbb"
    with pytest.raises(rpc.MixedCommitsError):
        rpc.analyze(rows, None, "hab_on", comps, ["value_weighted_exposure"], expected_seeds=[1, 2])
    assert rpc.analyze(rows, None, "hab_on", comps, ["value_weighted_exposure"], expected_seeds=[1, 2],
                       allow_mixed=True)
    rows[-1].update({"git_commit": "aaa", "git_dirty": True, "git_diff_sha1": "f" * 40})
    assert rpc.code_key(rows[-1]) != rpc.code_key(rows[0])   # uncommitted changes count as other code
    with pytest.raises(rpc.MixedCommitsError):
        rpc.check_commits(rows)


def test_run_job_records_code_version(monkeypatch):
    import DeterrentSystem as ds
    monkeypatch.setattr(ds, "run_simulation_frames_persistent",
                        lambda **p: iter([{"metrics_compact": {"value_weighted_exposure": 1.0}}]))
    row = rpc.run_job({"system": "B5_c_hab_on", "variant": "B5_c", "habituation_condition": "hab_on",
                       "seed": 300, "params": rpc.build_params("B5_c", True, MU, 60.0)})
    v = rpc.code_version()
    assert row["git_commit"] == v["git_commit"] and len(v["git_commit"]) == 40
    assert row["git_dirty"] == v["git_dirty"] and row["git_diff_sha1"] == v["git_diff_sha1"]


class _FailProc:
    def __init__(self, job, fail_first):
        self.job, self.fail_first, self.polls, self.returncode = job, fail_first, 0, None

    def poll(self):
        self.polls += 1
        if self.polls < 2:
            return None
        if self.fail_first:
            self.returncode = 3
        else:
            Path(self.job["raw_json"]).write_text("{}")
            self.returncode = 0
        return self.returncode


def test_scheduler_retries_and_writes_failure_report(tmp_path, monkeypatch):
    launches = []

    def fake_launch(job):
        n = sum(1 for j in launches if j == job["system"])
        launches.append(job["system"])
        fail = job["system"] == "always" or (job["system"] == "flaky" and n == 0)
        log = Path(job["raw_json"]).with_suffix(".log")
        log.write_text(f"Traceback\nRuntimeError: boom {job['system']} attempt {n + 1}\n")
        return _FailProc(job, fail), open(tmp_path / f"h{len(launches)}.txt", "w"), str(tmp_path / "x.pkl")

    monkeypatch.setattr(rpc, "_launch", fake_launch)
    monkeypatch.setattr(rpc, "wait_for_memory", lambda *a, **k: 20.0)
    monkeypatch.setattr(rpc, "free_memory_gb", lambda: 20.0)
    monkeypatch.setattr(rpc.time, "sleep", lambda s: None)
    raw = tmp_path / "raw"
    raw.mkdir()
    jobs = [{"system": s, "seed": 1, "params": {}, "raw_json": str(raw / f"{s}.json")} for s in ("flaky", "always")]
    res = rpc.execute_jobs(jobs, max_workers=1, plan_concurrency=1, plan_stagger_s=0.0, retries=2)
    assert launches.count("flaky") == 2 and launches.count("always") == 3
    assert [f["system"] for f in res["failed"]] == ["always"] and res["failed"][0]["final"] is True
    recs = [json.loads(x) for x in (raw / "failures.jsonl").read_text().splitlines()]
    assert [(r["system"], r["attempt"]) for r in recs] == [("flaky", 1), ("always", 1), ("always", 2), ("always", 3)]
    assert "RuntimeError: boom always attempt 3" in recs[-1]["error_tail"]
    assert (raw / "flaky.attempt1.log").exists() and (raw / "failures.md").exists()


def test_analyze_did_difference_of_differences():
    rows = []
    for s in (1, 2, 3):
        for v, m in (("B5_c", 10.0), ("E_plan", 8.0 + s), ("B5_c@ref", 10.0), ("E_plan@ref", 7.0)):
            rows.append({"variant": v, "habituation_condition": "hab_on", "seed": s, "m": m})
    st = rpc.analyze_did(rows, ("B5_c", "E_plan"), ("B5_c@ref", "E_plan@ref"), "did", metrics=["m"],
                         expected_seeds=[1, 2, 3])
    assert len(st) == 1 and st[0]["n"] == 3
    assert math.isclose(st[0]["mean_diff"], np.mean([(8.0 + s - 10.0) - (7.0 - 10.0) for s in (1, 2, 3)]))
    assert st[0]["dropped_seeds"] == ""


def test_tradeoff_points_and_outputs(tmp_path):
    rows = _rows(["B5_c", "E_plan", "D_plan"], list(range(300, 310)))
    pts = rpc.tradeoff(rows, "hab_on", expected_seeds=list(range(300, 310)))
    assert [p["variant"] for p in pts] == ["D_plan", "E_plan"]
    b5 = np.mean([100.0 + s for s in range(300, 310)])
    for p in pts:
        assert math.isclose(p["exposure_pct_of_ref"], 100.0 - 1000.0 / b5)
        assert math.isclose(p["miss_diff_pp"], 1.0)
        assert p["exposure_pct_ci_lo"] <= p["exposure_pct_of_ref"] <= p["exposure_pct_ci_hi"]
    flat = rpc.write_tradeoff({"heavy": pts}, tmp_path, "tradeoff", "test")
    assert len(flat) == 2 and (tmp_path / "tradeoff.csv").exists() and (tmp_path / "tradeoff.md").exists()
    pytest.importorskip("matplotlib")
    assert (tmp_path / "tradeoff.png").stat().st_size > 0


def test_neighbor_reference_cell_and_comparisons(jobs_by_study):
    root, jobs = jobs_by_study
    st = rps.STUDIES["neighbor"](_Args(root))
    assert st.per_robot_metrics is True
    ref = next(c for c in st.cells if c.name == rps.NEIGHBOR_REFERENCE_CELL)
    assert ref.variants == ["B5_c", "E_plan"] and ref.seeds == list(range(300, 310)) and ref.mu == rpc.LOADS["heavy"]
    assert ref.extra == {"planner_hab_mode": "per_robot", "neighbor_delay_s": 0.0, "neighbor_drop_prob": 0.0}
    others = [c for c in st.cells if c is not ref]
    assert len(others) == 6
    for c in others:
        assert sorted(c.reuse) == [("neighbor/per_robot_reference", "B5_c", "B5_c@ref"),
                                   ("neighbor/per_robot_reference", "E_plan", "E_plan@ref")]
        pairs = {(r, t) for r, t, _ in c.comparisons}
        assert pairs == {("B5_c", "E_plan"), ("E_plan@ref", "E_plan"), ("B5_c@ref", "B5_c")}
        assert [(d[0], d[1]) for d in c.did] == [(("B5_c", "E_plan"), ("B5_c@ref", "E_plan@ref"))]
    # the reference differs from every delay/drop cell only in the delay/drop parameters
    by = {(j["cell"], j["variant"], j["seed"]): j["params"] for j in jobs["neighbor"]}
    for (cell, v, s), p in by.items():
        if cell != rps.NEIGHBOR_REFERENCE_CELL:
            assert _diff(by[(rps.NEIGHBOR_REFERENCE_CELL, v, s)], p) <= {"neighbor_delay_s", "neighbor_drop_prob"}
    assert sum(1 for j in jobs["neighbor"] if rpc.is_plan_job(j["params"])) == 70   # +10 plan runs


def test_neighbor_analysis_end_to_end_with_per_robot_metrics(tmp_path):
    st = rps.STUDIES["neighbor"](_Args(tmp_path))
    st.cells = st.cells[:2]   # reference + delay_30s
    for c in st.cells:
        raw = tmp_path / "neighbor" / c.name / "raw"
        raw.mkdir(parents=True)
        for s in c.seeds:
            for v in c.variants:
                r = {"variant": v, "habituation_condition": "hab_on", "seed": s,
                     "value_weighted_exposure": 100.0 + s + (5.0 if c.name != st.cells[0].name else 0.0),
                     "reactive_miss_fraction": 0.3}
                if v == "E_plan":
                    r.update({"plan_pr_realized_minus_pred_mean": 1.0, "plan_pr_realized_minus_pred_mean_0": 2.0})
                (raw / f"{v}_hab_on_seed_{s}.json").write_text(json.dumps(r))
    stats = rps.analyze_study(st, tmp_path)
    cells = {s["cell"] for s in stats}
    assert cells == {rps.NEIGHBOR_REFERENCE_CELL, "delay_30s"}
    d = [s for s in stats if s["cell"] == "delay_30s"]
    assert any(s["comparison"].startswith("(E_plan - B5_c) in cell") for s in d)
    e = next(s for s in d if s["reference"] == "E_plan@ref" and s["metric"] == "value_weighted_exposure")
    assert math.isclose(e["mean_diff"], 5.0)
    assert any(s["metric"] == "plan_pr_realized_minus_pred_mean_0" for s in stats)
    assert (tmp_path / "neighbor" / "tradeoff.csv").exists()
    # a missing seed in the reference makes the analysis fail by default
    (tmp_path / "neighbor" / rps.NEIGHBOR_REFERENCE_CELL / "raw" / "E_plan_hab_on_seed_305.json").unlink()
    with pytest.raises(rpc.MissingSeedsError):
        rps.analyze_study(st, tmp_path)
    rps.analyze_study(st, tmp_path, allow_missing=True)
    assert "305: no E_plan" in (tmp_path / "neighbor" / "analysis.md").read_text()


def test_timeout_study_isolated_and_last(jobs_by_study):
    _, jobs = jobs_by_study
    assert all(j["isolated"] and j["stage"] == rps.ISOLATED_STAGE for j in jobs["timeout"])
    assert not any(j["isolated"] for n, js in jobs.items() if n != "timeout" for j in js)
    allj = rps.order_jobs([j for js in jobs.values() for j in js], rps.DEFAULT_ORDER)
    sched = rps.schedule(allj)
    assert sched[-1][2] is True and {j["study"] for j in sched[-1][1]} == {"timeout"}
    assert sched[0][0] == rps.TRACE_STAGE
    assert all(not iso for _, _, iso in sched[:-1])


def test_run_scheduled_isolation_one_run_at_a_time(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rpc, "execute_jobs", lambda jobs, **kw: calls.append((sorted({j["study"] for j in jobs}), kw))
                        or {"done": len(jobs), "failed": []})
    exported = []
    monkeypatch.setattr(rps, "export_traces", lambda root: exported.append(root) or {})

    class A:
        max_workers, plan_concurrency, plan_stagger_s, min_free_gb, poll_s, overlap, retries = 2, 2, 300.0, 12.0, 300.0, True, 1
    args = _Args(tmp_path)
    jobs = rps.order_jobs([j for n in ("traces", "timeout", "floor") for j in rps.collect_jobs(rps.STUDIES[n](args), tmp_path)],
                          rps.DEFAULT_ORDER)
    rps.run_scheduled(jobs, A, tmp_path)
    assert [c[0] for c in calls] == [["traces"], ["floor"], ["timeout"]]
    iso = calls[-1][1]
    assert iso["max_workers"] == 1 and iso["plan_concurrency"] == 1 and iso["overlap"] is False
    assert calls[1][1]["overlap"] is True and calls[1][1]["plan_concurrency"] == 2
    assert exported == [tmp_path]   # traces exported right after the trace stage


def test_trace_study_definition(jobs_by_study):
    _, jobs = jobs_by_study
    js = jobs["traces"]
    assert {(j["variant"], j["seed"], j["params"]["mu_true"]) for j in js} == {
        ("A", 200, 1e-4), ("B", 200, 1e-4), ("E_plan", 200, 1e-4)}
    assert all(j["stage"] == rps.TRACE_STAGE for j in js) and rps.DEFAULT_ORDER[0] == "traces"
    for j in js:
        if j["variant"] in ("A", "B"):
            assert j["params"]["stl_binding_log_fraction"] == 1.0
            assert j["params"]["stl_binding_log_path"].endswith("_seed_200_binding.jsonl")
        else:
            assert rpc.is_plan_job(j["params"]) and j["decision_log"].endswith("_seed_200_decisions.jsonl")
    # the E_plan trace run has the evaluation parameters of E_plan (only the seed differs)
    assert _diff(rpc.build_params("E_plan", True, 1e-4, None), [j for j in js if j["variant"] == "E_plan"][0]["params"]) == set()


def test_export_traces_on_logs(tmp_path):
    raw = rps.cell_dir(tmp_path, "traces", rps.TRACE_CELL) / "raw"
    raw.mkdir(parents=True)
    rec = {"decision": 0, "t": 45.0, "n_candidates": 1, "n_evaluated": 1, "rounds": [{"round": 0, "J0_mean": 5.0}],
           "admitted": [{"robot": "r0", "mode": "laser", "U_mean": 1.0, "U_se": 0.1}], "timed_out": False,
           "candidates": [{"robot": "r0", "mode": "laser", "status": "admitted",
                           "rounds": [{"round": 0, "U_mean": 1.0, "U_se": 0.1}]}]}
    (raw / "E_plan_hab_on_seed_200_decisions.jsonl").write_text(json.dumps(rec) + "\n")
    b = [{"t": 45.0, "robot": "r0", "mode": "laser", "U": 0.1}, {"t": 45.0, "robot": "r0", "mode": "horn", "U": 0.2}]
    (raw / "A_hab_on_seed_200_binding.jsonl").write_text("\n".join(json.dumps(x) for x in b) + "\n")
    res = rps.export_traces(tmp_path)
    assert res["plan_rows"] == 1 and res["binding_rows"] == 2
    assert (tmp_path / "traces" / "candidate_traces" / "plan_traces.md").exists()


def test_persistent_old_design_refuses_to_run():
    from experiments import run_persistent_operation as rpo
    with pytest.raises(SystemExit, match="run_plan_studies --study persistent"):
        rpo.main()


def test_persistent_depleted_start_planner_fresh_no_placeholder(jobs_by_study):
    """The simulator keeps the planner fresh on a depleted start; no extra parameter."""
    _, jobs = jobs_by_study
    assert not hasattr(rps, "TODO_SIM_PLANNER_FRESH")
    dep = [j for j in jobs["persistent"] if j["cell"].startswith("depleted")]
    fresh = {(j["cell"].replace("fresh_", ""), j["variant"], j["seed"]): j["params"]
             for j in jobs["persistent"] if j["cell"].startswith("fresh")}
    for j in dep:
        ref = fresh[(j["cell"].replace("depleted_", ""), j["variant"], j["seed"])]
        assert _diff(ref, j["params"]) == {"initial_hab_state_path"}


def test_compute_estimate_rates():
    assert math.isclose(rps.ORACLE_WALL_FACTOR, 1.08)
    assert math.isclose(rps.RUN_HOURS_1800S[("plan", "heavy")], 41.0 / 60.0 * 1.08)
    assert math.isclose(rps.RUN_HOURS_1800S[("plan", "overload")], 2.0 * 1.08)
    assert math.isclose(rps.RUN_HOURS_1800S_POOL2[("plan", "heavy")], 3 * 2897.0 / 3600.0)
    assert all(v is not None for v in rps.RUN_HOURS_1800S.values())


def test_compute_estimate(tmp_path):
    args = _Args(tmp_path)
    studies = [rps.STUDIES[n](args) for n in ("traces", "neighbor", "timeout")]
    rates = {("plan", "heavy"): 1.0, ("ordinary", "heavy"): 0.1}
    est = rps.compute_estimate(studies, tmp_path, rates, plan_concurrency=2, max_workers=2)
    assert est["runs"]["neighbor/plan/heavy"] == 70 and est["runs"]["neighbor/ordinary/heavy"] == 70
    assert est["runs"]["timeout/plan/heavy"] == 20 and est["runs"]["traces/plan/heavy"] == 1
    w = est["priced_wall_hours_by_stage"]
    assert math.isclose(w["isolated"], 20.0)            # isolated: full wall time, one at a time
    assert math.isclose(w["stage1"], 35.0)              # 70 plan h / 2 slots > 7 ordinary h / 2
    assert math.isclose(w["stage-1"], 1.0)              # never shorter than its longest run
    est2 = rps.compute_estimate([rps.STUDIES["floor"](args)], tmp_path, rates)
    assert est2["unpriced_run_units_1800s"] == {"plan/spare": 10.0, "plan/overload": 10.0}


def test_confirmatory_family_errors_on_missing_seed(tmp_path):
    dirs = {}
    for load in ("spare", "heavy", "overload"):
        raw = tmp_path / load / "raw"
        raw.mkdir(parents=True)
        for s in range(300, 330):
            for v in ("B5_c", "E_plan"):
                if load == "heavy" and v == "E_plan" and s == 317:
                    continue
                (raw / f"{v}_hab_on_seed_{s}.json").write_text(json.dumps(
                    {"variant": v, "habituation_condition": "hab_on", "seed": s,
                     "value_weighted_exposure": 1000.0 - (10 if v == "E_plan" else 0) + s % 7,
                     "reactive_miss_fraction": 0.3}))
        dirs[load] = tmp_path / load
    with pytest.raises(rpc.MissingSeedsError, match="317"):
        apc.run_family(treatment="E_plan", reference="B5_c", dirs=dirs, expected_n=30, out=tmp_path / "out")
    tests = apc.run_family(treatment="E_plan", reference="B5_c", dirs=dirs, expected_n=30, out=tmp_path / "out",
                           allow_missing=True)
    heavy = [t for t in tests if t["load"] == "heavy"]
    assert all(t["n"] == 29 and t["dropped_reasons"] == "317: no E_plan run" for t in heavy)
    assert "317: no E_plan run" in (tmp_path / "out" / "confirmatory_tests.md").read_text()
