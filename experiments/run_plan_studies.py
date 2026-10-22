"""
run_plan_studies.py -- dispatcher for the Section 6 evaluation studies (decisions 16-26, 29).

Each study writes to its own directory results/plan_studies/<study>/<cell>/ (raw JSON per
run, per-decision JSONL for plan runs, per-run CSV) and is resumable: a run whose raw
JSON exists is never rerun.  Execution uses the memory-safe scheduler of
run_plan_completion.execute_jobs (memory check >= 12 GB before every launch, ordinary
jobs first, then plan runs with --plan-concurrency, default 2).  Jobs of all requested
studies are scheduled together, so the two plan slots stay busy across studies.

Studies (all variants in PLAN_ENV; loads spare 2e-5, heavy 1e-4, overload 4e-4):
  confirmatory  hab on, 3 loads, eval seeds 300-329: B1_c, B5_c, A, B, C, C_gate, C_plan,
                D_plan, E_plan (decisions 2, 3, 8, 23).  Analysis: progression paired
                statistics per load and the predeclared confirmatory family
                (experiments/analyze_plan_confirmatory.py, E_plan vs B5_c).
  zero_hab      hab off, 3 loads, seeds 300-309: B5_c, D_plan, E_plan (decision 20; reduced
                from 30 to 10 seeds by user decision 2026-10-22, budget).
  mismatch      heavy, planner kappa 0.50, environment kappa {0.10, 0.25, 0.50, 0.75, 0.90},
                B5_c and E_plan, seeds 300-309 (decision 19).  The kappa 0.50 cell runs nothing:
                it reuses confirmatory/heavy seeds 300-309 (identical effective parameters;
                user decision 2026-10-22).
  neighbor      heavy, planner_hab_mode per_robot, D in {30, 120, 300} s with p = 0 and
                p in {0.1, 0.3, 0.5} with D = 0, B5_c and E_plan, seeds 300-309 (decision 18),
                plus a per_robot REFERENCE cell with D = 0, p = 0 (user decision 2026-10-22).
                Every delay/drop cell is compared with the reference: E_plan vs E_plan@ref,
                B5_c vs B5_c@ref, and the difference of differences
                (E_plan - B5_c) minus (E_plan@ref - B5_c@ref).  Per-robot Prop. 2 metrics
                (plan_pr_*) are reported.
  timeout       heavy, E_plan with plan_compute_budget_s = 45 vs E_plan without budget,
                dev seeds 200-209 (decision 16).  Runs IN ISOLATION (user decision
                2026-10-22): excluded from the overlap and scheduled after every other job,
                one run at a time with nothing else running, so its wall-clock budget sees an
                otherwise idle machine.  Timeouts are an outcome here (plan_timeout_rate,
                plan_rejected_timeout), never a reason to drop a run.
  traces        pre-evaluation trace study (user decision 2026-10-22): heavy, dev seed 200,
                A and B with the Section 3 binding log of every decision and E_plan with its
                plan decision log; runs FIRST (stage -1), then
                experiments/export_candidate_traces.py exports a few decisions of each kind
                to <root>/traces/candidate_traces.
  disturbance   heavy, B5_c and E_plan, seeds 300-309 (decision 29): travel_speed_error 0.2;
                unforecast arrival burst x2 for 300 s whose start is drawn per seed uniformly
                in [300, 1200] s (user decision 2026-10-22) from
                random_streams.CoupledRandomStreams(seed).arrival_burst_start_s (purpose
                PURPOSE_ARRIVAL_BURST = 15: depends only on the seed, so every system of a seed
                sees the same burst); the drawn start is recorded per run as
                arrival_burst_start_s.  Nominal reference:
                confirmatory/heavy, same seeds.
  floor         E_plan_floor, 3 loads, seeds 300-309; E_plan reference from confirmatory
                (identical parameters) (decision 26).
  persistent    the ONE persistent design (decision 22; experiments/run_persistent_operation.py
                refuses to run): production T_rec 1800 s, 5400 s runs, outcome windows [0, 1800)
                and [1800, 5400], {fresh, depleted} x {spare->heavy, heavy->spare} switching at
                2700 s (mu_step_time_s / mu_step_factor); depleted start = TRUTH cue state at the
                end of an 1800 s B5_c run at the same starting load and seed
                (save_final_hab_state_path, generated first); the PLANNER starts fresh for every
                system (no informed-planner reference); thesis wording for the fresh vs depleted
                difference: "startup after unrecorded prior use".  B5_c, D_plan, E_plan; seeds
                300-309.
  timed_recovery  E_plan_tr vs E_plan (decision 2, exploratory): 3 loads, seeds 300-309,
                thresholds from docs/calibration/timed_recovery_thresholds.json, E_plan
                reference from confirmatory (user decision 2026-10-22).

Section 3 binding log (decision 27): every decision (fraction 1.0, user decision 2026-10-22)
of variants A and B in the confirmatory study is logged to raw/<system>_seed_<seed>_binding.jsonl.
Measured size (heavy 300 s: about 0.59 MB for A and B; overload 600 s: 2.2 MB for A)
projects to about 1-2 GB for 30 seeds x 3 loads x {A, B}, so plain JSONL is kept.

Analysis (user decisions 2026-10-22): every comparison ERRORS if a planned seed of a compared
system is missing or has a non-finite value in ANY reported metric, unless --allow-missing (then the
dropped seeds are listed); runs of different code versions (git commit + uncommitted diff,
recorded in every raw result) are never compared unless --allow-mixed-commits.  A failed run
is retried --retries times (default 1); every failed attempt is written with its log tail to
<cell>/raw/failures.jsonl and failures.md.  Each cell with B5_c also gets the exposure vs
service trade-off (tradeoff.csv/.md/.png in the study directory).

Overlap: ordinary jobs run alongside the plan runs (fastest).  This is the DEFAULT for
--study all (user decision 2026-10-22) and opt-in (--overlap) otherwise; --no-overlap turns
it off.  With overlap, plan decision runtimes (plan_runtime_* metrics) are measured while up
to --max-workers ordinary simulations and a second plan run share the machine, so they are
not idle-machine runtimes.

Usage:
  py -3.10 -m experiments.run_plan_studies --study all --overlap
  py -3.10 -m experiments.run_plan_studies --study confirmatory,zero_hab --dry-run
  py -3.10 -m experiments.run_plan_studies --study confirmatory
  py -3.10 -m experiments.run_plan_studies --study confirmatory --analyze-only
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from experiments.run_habituation_stl_production_ladder import _write_csv
from experiments import run_plan_completion as rpc

DEFAULT_ROOT = Path("results") / "plan_studies"
EVAL_SEEDS_30 = list(range(300, 330))
# User decision 2026-10-22: every 10-seed study uses eval seeds 300-309 for every system.
EVAL_SEEDS_10 = list(range(300, 310))
DEV_SEEDS_10 = list(range(200, 210))
LOADS = rpc.LOADS
CONFIRMATORY_VARIANTS = ["B1_c", "B5_c", "A", "B", "C", "C_gate", "C_plan", "D_plan", "E_plan"]

PERSISTENT_T_END_S = 5400.0          # 3 x T_rec (decision 22)
PERSISTENT_T_REC_S = 1800.0          # production T_rec
PERSISTENT_SWITCH_S = 2700.0         # mid-run demand switch
PERSISTENT_WINDOWS = [1800.0]        # startup window = first T_rec
DEPLETION_RUN_T_END_S = 1800.0       # B5_c run whose final cue state is the depleted start
BURST_DURATION_S = 300.0
BURST_FACTOR = 2.0
BURST_START_WINDOW_S = (300.0, 1200.0)   # user decision 2026-10-22: uniform per seed


def burst_start_s(seed: int) -> float:
    """Decision-29 burst start of ``seed`` (seed-only stream, identical across variants)."""
    from random_streams import CoupledRandomStreams
    return CoupledRandomStreams(int(seed)).arrival_burst_start_s(*BURST_START_WINDOW_S)


def burst_extra(seed: int) -> dict:
    return {"arrival_burst": {"start_s": burst_start_s(seed), "duration_s": BURST_DURATION_S,
                              "factor": BURST_FACTOR}}


def _tag(x: float) -> str:
    return f"{x:.2f}".replace(".", "p")


@dataclass
class Cell:
    """One parameter cell of a study: a set of variants run on the same seeds."""
    name: str
    mu: float
    hab_on: bool
    variants: list
    seeds: list
    extra: dict = field(default_factory=dict)
    t_end: Optional[float] = None
    per_seed_extra: Optional[Callable[[int], dict]] = None
    # rows reused from another cell for the analysis: (study/cell path, variant, alias)
    reuse: list = field(default_factory=list)
    comparisons: list = field(default_factory=list)
    # difference of paired differences: ((ref, trt) in this cell, (ref, trt) aliases of the
    # reference cell, label)
    did: list = field(default_factory=list)
    stage: int = 1                   # 0 runs (and finishes) before 1
    isolated: bool = False           # run after everything else, one run at a time
    skip_reason: Optional[str] = None


@dataclass
class Study:
    name: str
    cells: list
    description: str = ""
    per_robot_metrics: bool = False  # report per-robot Prop. 2 metrics (plan_pr_*)


TRACE_STAGE = -1        # pre-evaluation trace study: runs and finishes first
ISOLATED_STAGE = 99     # isolated cells (timeout study): after every other stage, one run at a time


# ---------------------------------------------------------------------------
# Study definitions
# ---------------------------------------------------------------------------
def _pair(ref, trt, label=None):
    return (ref, trt, label or f"{trt} vs {ref}")


def study_confirmatory(args) -> Study:
    cells = [Cell(name=load, mu=mu, hab_on=True, variants=list(CONFIRMATORY_VARIANTS), seeds=EVAL_SEEDS_30,
                  extra=_binding_extra(args), comparisons=list(rpc.COMPARISONS))
             for load, mu in LOADS.items()]
    return Study("confirmatory", cells, "hab on, 3 loads, 30 eval seeds; progression + confirmatory family")


BINDING_LOG_FRACTION = 1.0   # user decision 2026-10-22: every decision of A and B


def _binding_extra(args) -> dict:
    # Section 3 binding log for A/B (decision 27); the path itself is set per job in collect_jobs.
    frac = getattr(args, "binding_log_fraction", None)
    frac = BINDING_LOG_FRACTION if frac is None else float(frac)
    return {} if not frac else {"__binding_log_fraction": frac}


def study_zero_hab(args) -> Study:
    comps = [_pair("B5_c", "E_plan"), _pair("B5_c", "D_plan"), _pair("D_plan", "E_plan")]
    cells = [Cell(name=load, mu=mu, hab_on=False, variants=["B5_c", "D_plan", "E_plan"], seeds=EVAL_SEEDS_10,
                  comparisons=comps) for load, mu in LOADS.items()]
    return Study("zero_hab", cells, "habituation off, 3 loads, 10 eval seeds (300-309)")


MISMATCH_PLANNER_KAPPA = 0.50
MISMATCH_ENV_KAPPAS = (0.10, 0.25, 0.50, 0.75, 0.90)


def mismatch_extra(k: float) -> dict:
    return {"planner_habituation_kappa": MISMATCH_PLANNER_KAPPA, "truth_habituation_kappa": float(k)}


def study_mismatch(args) -> Study:
    cells = []
    for k in MISMATCH_ENV_KAPPAS:
        c = Cell(name=f"env_kappa_{_tag(k)}", mu=LOADS["heavy"], hab_on=True,
                 variants=["B5_c", "E_plan"], seeds=EVAL_SEEDS_10,
                 extra=mismatch_extra(k), comparisons=[_pair("B5_c", "E_plan")])
        if k == MISMATCH_PLANNER_KAPPA:
            # user decision 2026-10-22: no runs; reuse confirmatory/heavy seeds 300-309, whose
            # effective parameters are identical (truth/planner kappa None -> habituation_kappa 0.50)
            c.variants = []
            c.reuse = [("confirmatory/heavy", "B5_c", "B5_c"), ("confirmatory/heavy", "E_plan", "E_plan")]
        cells.append(c)
    return Study("mismatch", cells, "planner kappa 0.50, environment kappa varied, heavy, 10 seeds")


NEIGHBOR_DELAYS_S = (30.0, 120.0, 300.0)
NEIGHBOR_DROPS = (0.1, 0.3, 0.5)
NEIGHBOR_REFERENCE_CELL = "per_robot_reference"


def neighbor_extra(delay_s: float, drop_p: float) -> dict:
    return {"planner_hab_mode": "per_robot", "neighbor_delay_s": float(delay_s), "neighbor_drop_prob": float(drop_p)}


def study_neighbor(args) -> Study:
    ref_rel = f"neighbor/{NEIGHBOR_REFERENCE_CELL}"
    # user decision 2026-10-22: per_robot reference with D = 0, p = 0 (B5_c and E_plan, heavy,
    # 300-309); every delay/drop cell is compared with it
    cells = [Cell(name=NEIGHBOR_REFERENCE_CELL, mu=LOADS["heavy"], hab_on=True, variants=["B5_c", "E_plan"],
                  seeds=EVAL_SEEDS_10, extra=neighbor_extra(0.0, 0.0), comparisons=[_pair("B5_c", "E_plan")])]
    reuse = [(ref_rel, "B5_c", "B5_c@ref"), (ref_rel, "E_plan", "E_plan@ref")]
    comps = [_pair("B5_c", "E_plan"),
             _pair("E_plan@ref", "E_plan", "E_plan cell vs E_plan per_robot reference (D=0, p=0)"),
             _pair("B5_c@ref", "B5_c", "B5_c cell vs B5_c per_robot reference (D=0, p=0)")]
    did = [(("B5_c", "E_plan"), ("B5_c@ref", "E_plan@ref"),
            "(E_plan - B5_c) in cell minus (E_plan - B5_c) in per_robot reference")]
    for d in NEIGHBOR_DELAYS_S:
        cells.append(Cell(name=f"delay_{int(d)}s", mu=LOADS["heavy"], hab_on=True, variants=["B5_c", "E_plan"],
                          seeds=EVAL_SEEDS_10, extra=neighbor_extra(d, 0.0), reuse=list(reuse),
                          comparisons=list(comps), did=list(did)))
    for p in NEIGHBOR_DROPS:
        cells.append(Cell(name=f"drop_{_tag(p)}", mu=LOADS["heavy"], hab_on=True, variants=["B5_c", "E_plan"],
                          seeds=EVAL_SEEDS_10, extra=neighbor_extra(0.0, p), reuse=list(reuse),
                          comparisons=list(comps), did=list(did)))
    return Study("neighbor", cells, "per-robot information, delayed or dropped neighbor histories vs the "
                 "per_robot D=0, p=0 reference, heavy, 10 seeds", per_robot_metrics=True)


def study_timeout(args) -> Study:
    ref = ("timeout/no_budget", "E_plan", "E_plan@no_budget")
    # user decision 2026-10-22: run in ISOLATION (both cells, so the reference runtimes are
    # measured under the same idle conditions), after everything else, one run at a time
    cells = [
        Cell(name="no_budget", mu=LOADS["heavy"], hab_on=True, variants=["E_plan"], seeds=DEV_SEEDS_10,
             isolated=True),
        Cell(name="budget_45s", mu=LOADS["heavy"], hab_on=True, variants=["E_plan"], seeds=DEV_SEEDS_10,
             extra={"plan_compute_budget_s": 45.0}, reuse=[ref], isolated=True,
             comparisons=[_pair("E_plan@no_budget", "E_plan", "E_plan 45 s budget vs no budget")]),
    ]
    return Study("timeout", cells, "45 s wall-clock budget, heavy, dev seeds 200-209, run in isolation")


TRACE_SEED = 200
TRACE_VARIANTS = ["A", "B", "E_plan"]
TRACE_CELL = "heavy_dev_seed_200"


def study_traces(args) -> Study:
    """Pre-evaluation candidate traces (user decision 2026-10-22): heavy, dev seed 200, A and B
    with the binding log of every decision, E_plan with its plan decision log (every plan
    run writes raw/<system>_seed_<seed>_decisions.jsonl).  Runs first (TRACE_STAGE)."""
    cells = [Cell(name=TRACE_CELL, mu=LOADS["heavy"], hab_on=True, variants=list(TRACE_VARIANTS),
                  seeds=[TRACE_SEED], extra={"__binding_log_fraction": 1.0}, stage=TRACE_STAGE)]
    return Study("traces", cells, "pre-evaluation candidate traces: heavy, dev seed 200, A, B, E_plan")


def export_traces(root: Path, per_kind: int = 2) -> dict:
    """Run experiments/export_candidate_traces.py on the trace study's logs."""
    from experiments import export_candidate_traces as ect
    raw = cell_dir(root, "traces", TRACE_CELL) / "raw"
    plan_logs = sorted(str(p) for p in raw.glob("*_decisions.jsonl")) if raw.exists() else []
    binding_logs = sorted(str(p) for p in raw.glob("*_binding.jsonl")) if raw.exists() else []
    if not plan_logs and not binding_logs:
        print("[studies] traces: no logs found; export skipped", flush=True)
        return {}
    res = ect.export(plan_logs, binding_logs, Path(root) / "traces" / "candidate_traces", per_kind)
    print(f"[studies] traces exported to {Path(root) / 'traces' / 'candidate_traces'}: {res}", flush=True)
    return res


def study_disturbance(args) -> Study:
    nominal = [("confirmatory/heavy", "B5_c", "B5_c@nominal"), ("confirmatory/heavy", "E_plan", "E_plan@nominal")]
    comps = [_pair("B5_c", "E_plan"), _pair("B5_c@nominal", "B5_c", "B5_c disturbed vs nominal"),
             _pair("E_plan@nominal", "E_plan", "E_plan disturbed vs nominal")]
    cells = [Cell(name="travel_speed_error_0p20", mu=LOADS["heavy"], hab_on=True, variants=["B5_c", "E_plan"],
                  seeds=EVAL_SEEDS_10, extra={"travel_speed_error": 0.2}, reuse=nominal, comparisons=comps)]
    burst = Cell(name="arrival_burst_x2_300s_random_start", mu=LOADS["heavy"], hab_on=True,
                 variants=["B5_c", "E_plan"], seeds=EVAL_SEEDS_10, per_seed_extra=burst_extra,
                 reuse=nominal, comparisons=comps)
    cells.append(burst)
    return Study("disturbance", cells, "travel-speed error and unforecast arrival burst, heavy, 10 seeds")


def study_floor(args) -> Study:
    cells = [Cell(name=load, mu=mu, hab_on=True, variants=["E_plan_floor"], seeds=EVAL_SEEDS_10,
                  reuse=[(f"confirmatory/{load}", "E_plan", "E_plan")],
                  comparisons=[_pair("E_plan", "E_plan_floor")]) for load, mu in LOADS.items()]
    return Study("floor", cells, "effectiveness floor 0.4 vs E_plan, 3 loads, 10 seeds")


def hab_state_path(root: Path, start_load: str, seed: int) -> Path:
    return Path(root) / "persistent" / "hab_states" / f"B5_c_{start_load}_T{int(DEPLETION_RUN_T_END_S)}_seed_{int(seed)}.json"


def study_persistent(args) -> Study:
    root = Path(args.root)
    cells = []
    # stage 0: depletion runs (B5_c, 1800 s, same starting load and seed), save final cue state
    for load in ("spare", "heavy"):
        cells.append(Cell(name=f"depletion_source_{load}", mu=LOADS[load], hab_on=True, variants=["B5_c"],
                          seeds=EVAL_SEEDS_10, t_end=DEPLETION_RUN_T_END_S,
                          extra={"habituation_T_rec_s": PERSISTENT_T_REC_S},
                          per_seed_extra=(lambda s, _l=load: {
                              "save_final_hab_state_path": str(hab_state_path(root, _l, s))}),
                          stage=0))
    switches = {"spare_to_heavy": ("spare", LOADS["heavy"] / LOADS["spare"]),
                "heavy_to_spare": ("heavy", LOADS["spare"] / LOADS["heavy"])}
    comps = [_pair("B5_c", "E_plan"), _pair("B5_c", "D_plan"), _pair("D_plan", "E_plan")]
    for start in ("fresh", "depleted"):
        for sw, (load0, factor) in switches.items():
            per_seed = None
            if start == "depleted":
                # User decision 2026-10-22: the TRUTH starts from the truth eta at the end of the
                # B5_c source run; the PLANNER always starts fresh (eta = 1) on a depleted start
                # (simulator behavior of initial_hab_state_path, no extra parameter).
                per_seed = (lambda s, _l=load0: {"initial_hab_state_path": str(hab_state_path(root, _l, s))})
            cells.append(Cell(
                name=f"{start}_{sw}", mu=LOADS[load0], hab_on=True, variants=["B5_c", "D_plan", "E_plan"],
                seeds=EVAL_SEEDS_10, t_end=PERSISTENT_T_END_S,
                extra={"habituation_T_rec_s": PERSISTENT_T_REC_S, "outcome_window_boundaries_s": PERSISTENT_WINDOWS,
                       "mu_step_time_s": PERSISTENT_SWITCH_S, "mu_step_factor": float(factor)},
                per_seed_extra=per_seed, comparisons=comps, stage=1))
    return Study("persistent", cells, "5400 s, fresh/depleted x demand switch, 10 seeds")


def study_timed_recovery(args) -> Study:
    cells = [Cell(name=load, mu=mu, hab_on=True, variants=["E_plan_tr"], seeds=EVAL_SEEDS_10,
                  reuse=[(f"confirmatory/{load}", "E_plan", "E_plan")],
                  comparisons=[_pair("E_plan", "E_plan_tr")]) for load, mu in LOADS.items()]
    return Study("timed_recovery", cells, "E_plan_tr vs E_plan (exploratory), 3 loads, 10 seeds")


STUDIES = {
    "traces": study_traces,
    "confirmatory": study_confirmatory,
    "zero_hab": study_zero_hab,
    "floor": study_floor,
    "mismatch": study_mismatch,
    "neighbor": study_neighbor,
    "disturbance": study_disturbance,
    "timeout": study_timeout,
    "persistent": study_persistent,
    "timed_recovery": study_timed_recovery,
}
# Priority when several studies are scheduled together (decision 23 budget order).
DEFAULT_ORDER = ["traces", "confirmatory", "zero_hab", "floor", "timed_recovery", "mismatch", "neighbor", "disturbance",
                 "timeout", "persistent"]


def _parse_seeds(s: str) -> list:
    out = []
    for part in [p for p in s.split(",") if p.strip()]:
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def cell_dir(root: Path, study: str, cell: str) -> Path:
    return Path(root) / study / cell


def cell_params(cell: Cell, variant: str, seed: int) -> dict:
    extra = {k: v for k, v in cell.extra.items() if not k.startswith("__")}
    if cell.per_seed_extra is not None:
        extra.update(cell.per_seed_extra(int(seed)))
    return rpc.build_params(variant, cell.hab_on, cell.mu, cell.t_end, extra)


def collect_jobs(study: Study, root: Path) -> list:
    jobs = []
    for cell in study.cells:
        if cell.skip_reason:
            continue
        raw = cell_dir(root, study.name, cell.name) / "raw"
        frac = cell.extra.get("__binding_log_fraction")
        for seed in cell.seeds:
            for v in cell.variants:
                params = cell_params(cell, v, seed)
                if frac and v in ("A", "B"):
                    cond = "hab_on" if cell.hab_on else "hab_off"
                    params["stl_binding_log_path"] = str(raw / f"{v}_{cond}_seed_{seed}_binding.jsonl")
                    params["stl_binding_log_fraction"] = float(frac)
                job = rpc.make_job(raw, v, cell.hab_on, seed, params, study=study.name, cell=cell.name)
                job["stage"] = ISOLATED_STAGE if cell.isolated else int(cell.stage)
                job["isolated"] = bool(cell.isolated)
                jobs.append(job)
    return jobs


def order_jobs(jobs: list, study_order: list) -> list:
    """Stage first, then study priority, then seed-major (balanced partial results)."""
    rank = {s: i for i, s in enumerate(study_order)}
    return sorted(jobs, key=lambda j: (j["stage"], rank.get(j["study"], 99), int(j["seed"]), j["cell"],
                                       j["variant"]))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def _load_cell_rows(root: Path, rel: str) -> list:
    d = Path(root) / rel
    return rpc.load_rows(d) if (d / "raw").exists() else []


def cell_rows(root: Path, study: Study, cell: Cell) -> list:
    rows = list(_load_cell_rows(root, f"{study.name}/{cell.name}"))
    for rel, variant, alias in cell.reuse:
        for r in _load_cell_rows(root, rel):
            if r["variant"] == variant and int(r["seed"]) in set(cell.seeds):
                r = dict(r)
                r["variant"] = alias
                rows.append(r)
    return rows


PERSISTENT_WINDOW_METRICS = ["outcome_window0_value_weighted_exposure", "outcome_window1_value_weighted_exposure",
                             "outcome_window0_reactive_miss_fraction", "outcome_window1_reactive_miss_fraction",
                             "outcome_window0_reactive_unfinished_total", "outcome_window1_reactive_unfinished_total"]


def analyze_study(study: Study, root: Path, allow_missing: bool = False, allow_mixed: bool = False) -> list:
    """Paired statistics of every cell of ``study`` (errors on missing seeds or mixed code
    versions unless allowed), the difference-of-differences rows, the exposure vs service
    trade-off of every cell with B5_c, and the study-specific extras (confirmatory family,
    trace export)."""
    out_dir = Path(root) / study.name
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = list(rpc.REPORT_METRICS)
    if study.name == "persistent":
        metrics = PERSISTENT_WINDOW_METRICS + metrics
    all_stats, trade = [], {}
    lines = [f"# Study: {study.name}", "", study.description, "",
             "Paired by seed within each cell; 95% percentile bootstrap over seed pairs (10000 resamples);",
             "percent effect = mean paired difference / reference mean x 100. Exploratory (nominal).",
             "A missing planned seed is an error unless --allow-missing; dropped seeds are listed per row.", ""]
    for cell in study.cells:
        if cell.skip_reason:
            lines += [f"## {cell.name}", "", f"SKIPPED: {cell.skip_reason}", ""]
            continue
        rows = cell_rows(root, study, cell)
        cdir = cell_dir(root, study.name, cell.name)
        if (cdir / "raw").exists():
            _write_csv(rpc.flat_rows(rpc.load_rows(cdir)), cdir / "per_run_metrics.csv")
        hab = "hab_on" if cell.hab_on else "hab_off"
        where = f"{study.name}/{cell.name}"
        miss = {}
        if cell.comparisons:
            miss = rpc.check_missing(rows, cell.comparisons, cell.seeds, hab, allow_missing, where)
        cm = rpc.expand_metrics(metrics, rows, per_robot=study.per_robot_metrics)
        stats = rpc.analyze(rows, None, hab, cell.comparisons, cm, expected_seeds=cell.seeds,
                            allow_missing=allow_missing, allow_mixed=allow_mixed) if cell.comparisons else []
        for cell_pair, ref_pair, label in cell.did:
            stats += rpc.analyze_did(rows, cell_pair, ref_pair, label, hab, cm, expected_seeds=cell.seeds,
                                     allow_missing=allow_missing,
                                     allow_mixed=allow_mixed)
        n_runs = {v: sum(1 for r in rows if r["variant"] == v) for v in sorted({r["variant"] for r in rows})}
        versions = rpc.check_commits(rows, where, allow_mixed=True) if rows else {}
        lines += [f"## {cell.name}", "", f"mu={cell.mu:g}, {hab}, seeds {cell.seeds[0]}-{cell.seeds[-1]}, "
                  f"extra={json.dumps({k: v for k, v in cell.extra.items() if not k.startswith('__')})}",
                  f"runs present: {json.dumps(n_runs)}; code versions: {json.dumps(versions)}", ""]
        if miss:
            lines += [f"MISSING RUNS (partial analysis, --allow-missing): {json.dumps(miss)}", ""]
        if stats:
            lines += rpc.stats_table([dict(s, comparison=s["comparison"]) for s in stats])
        for s in stats:
            all_stats.append(dict(s, study=study.name, cell=cell.name))
        lines.append("")
        if any(r["variant"] == "B5_c" for r in rows):
            trade[cell.name] = rpc.tradeoff(rows, hab, "B5_c", expected_seeds=cell.seeds, allow_mixed=allow_mixed,
                                            allow_missing=allow_missing)
    _write_csv(all_stats, out_dir / "paired_stats.csv")
    (out_dir / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if any(trade.values()):
        rpc.write_tradeoff(trade, out_dir, "tradeoff", f"({study.name})")
    if study.name == "confirmatory":
        _confirmatory_family(study, root, allow_missing, allow_mixed)
    if study.name == "traces":
        export_traces(root)
    return all_stats


def _confirmatory_family(study: Study, root: Path, allow_missing: bool = False, allow_mixed: bool = False) -> None:
    from experiments import analyze_plan_confirmatory as apc
    dirs = {c.name: cell_dir(root, study.name, c.name) for c in study.cells}
    if not all((d / "raw").exists() for d in dirs.values()):
        print("[studies] confirmatory family: some load directories missing; skipped", flush=True)
        return
    apc.run_family(treatment="E_plan", reference="B5_c", dirs=dirs, expected_n=len(EVAL_SEEDS_30),
                   out=Path(root) / study.name / "confirmatory_family", expected_seeds=EVAL_SEEDS_30,
                   allow_missing=allow_missing, allow_mixed=allow_mixed)


# ---------------------------------------------------------------------------
# Compute estimate
# ---------------------------------------------------------------------------
# Wall hours of one 1800 s run, by kind and load (measured; reconciliation round 2026-10-22).
# ORACLE: all candidates on 25% of decisions with 64 scenarios costs +8% wall time and about
# 0 extra memory (simulator agent's measurement), applied as a factor 1.08 to the plan rates
# measured before the all-candidate oracle.
ORACLE_WALL_FACTOR = 1.08
# Default ("12 workers"): an 1800 s heavy E_plan run took about 41 min with a 12-worker
# rollout pool, an overload run about 120 min (12 workers); spare 0.13 h (mean of 20 E_plan
# dev-seed runs under results/testbench, 2026-10-18 code).  Each x 1.08 for the oracle.
# Ordinary runs: mean of 120 runs per load of the B/C/C_gate B4-pipeline variants (2026-10
# harness): spare 0.10 h, heavy 0.13 h, overload 0.18 h.
RUN_HOURS_1800S = {("plan", "spare"): 0.13 * ORACLE_WALL_FACTOR,
                   ("plan", "heavy"): 41.0 / 60.0 * ORACLE_WALL_FACTOR,
                   ("plan", "overload"): 120.0 / 60.0 * ORACLE_WALL_FACTOR,
                   ("ordinary", "spare"): 0.10, ("ordinary", "heavy"): 0.13, ("ordinary", "overload"): 0.18}
# Pessimistic ("pool 2"): a 600 s heavy E_plan run with a 2-worker pool and the oracle on took
# 2897 s, i.e. 3 x 2897 s = 2.41 h per 1800 s heavy run.  Spare and overload scaled by the
# same factor relative to the 12-worker heavy rate (an extrapolation, not a measurement).
_POOL2_HEAVY_H = 3.0 * 2897.0 / 3600.0
_POOL2_FACTOR = _POOL2_HEAVY_H / RUN_HOURS_1800S[("plan", "heavy")]
RUN_HOURS_1800S_POOL2 = {**RUN_HOURS_1800S,
                         ("plan", "spare"): RUN_HOURS_1800S[("plan", "spare")] * _POOL2_FACTOR,
                         ("plan", "heavy"): _POOL2_HEAVY_H,
                         ("plan", "overload"): RUN_HOURS_1800S[("plan", "overload")] * _POOL2_FACTOR}


def _load_name(mu: float) -> str:
    for name, v in LOADS.items():
        if math.isclose(float(mu), v):
            return name
    return f"mu={mu:g}"


def compute_estimate(studies: list, root: Path, run_hours: dict = None, plan_concurrency: int = 2,
                     max_workers: int = 2, pending_only: bool = True) -> dict:
    """Run counts and wall-time estimate of the scheduled jobs.

    Per stage (trace stage, main stages): plan runs share ``plan_concurrency`` slots and
    ordinary runs ``max_workers`` slots, overlapping, so the stage takes the longer of
    plan hours / plan_concurrency and ordinary hours / max_workers.  Isolated runs (timeout
    study) run one at a time after everything else, so their FULL wall time adds.  A run's
    hours scale with T_end / 1800 s.  Unknown rates are reported as run counts (``unpriced``),
    never guessed."""
    rates = dict(RUN_HOURS_1800S if run_hours is None else run_hours)
    jobs = [j for st in studies for j in collect_jobs(st, root)]
    if pending_only:
        jobs = [j for j in jobs if not Path(j["raw_json"]).exists()]
    counts, unpriced, stage_h = {}, {}, {}
    for j in jobs:
        kind = "plan" if rpc.is_plan_job(j["params"]) else "ordinary"
        load = _load_name(j["params"]["mu_true"])
        scale = float(j["params"].get("T_end", 1800.0)) / 1800.0
        key = f"{j['study']}/{kind}/{load}"
        counts[key] = counts.get(key, 0) + 1
        rate = rates.get((kind, load))
        bucket = "isolated" if j.get("isolated") else f"stage{j['stage']}"
        sh = stage_h.setdefault(bucket, {"plan": 0.0, "ordinary": 0.0, "longest": 0.0})
        if rate is None:
            unpriced[f"{kind}/{load}"] = unpriced.get(f"{kind}/{load}", 0.0) + scale   # in 1800 s run units
        else:
            sh[kind] += float(rate) * scale
            sh["longest"] = max(sh["longest"], float(rate) * scale)
    wall = {}
    for bucket, sh in stage_h.items():
        if bucket == "isolated":
            wall[bucket] = sh["plan"] + sh["ordinary"]
        else:   # a stage never ends before its longest single run
            wall[bucket] = max(sh["plan"] / max(1, plan_concurrency), sh["ordinary"] / max(1, max_workers),
                               sh["longest"])
    return {"runs": counts, "n_runs": len(jobs),
            "n_plan_runs": sum(1 for j in jobs if rpc.is_plan_job(j["params"])),
            "priced_wall_hours_by_stage": wall, "priced_wall_hours_total": float(sum(wall.values())),
            "unpriced_run_units_1800s": unpriced, "rates_h_per_1800s_run": {f"{k[0]}/{k[1]}": v for k, v in rates.items()}}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def resolve_overlap(study_arg: str, overlap) -> bool:
    """Overlap is the default for --study all (user decision 2026-10-22), opt-in otherwise."""
    if overlap is not None:
        return bool(overlap)
    return study_arg.strip() == "all"


def build_studies(names: list, args) -> list:
    return [STUDIES[n](args) for n in names]


def schedule(jobs: list) -> list:
    """(stage label, jobs, isolated) in execution order: the trace stage, the other stages in
    order, then the isolated jobs (timeout study) last."""
    out = []
    normal = [j for j in jobs if not j.get("isolated")]
    for stage in sorted({j["stage"] for j in normal}):
        out.append((stage, [j for j in normal if j["stage"] == stage], False))
    iso = [j for j in jobs if j.get("isolated")]
    if iso:
        out.append((ISOLATED_STAGE, iso, True))
    return out


def run_scheduled(jobs: list, args, root: Path) -> None:
    for stage, stage_jobs, isolated in schedule(jobs):
        if isolated:
            # user decision 2026-10-22: isolation = nothing else running, one run at a time
            print(f"[studies] isolated stage: {len(stage_jobs)} jobs, one at a time, no overlap", flush=True)
            res = rpc.execute_jobs(stage_jobs, max_workers=1, plan_concurrency=1, plan_stagger_s=0.0,
                                   min_free_gb=args.min_free_gb, poll_s=args.poll_s, tag="studies-isolated",
                                   overlap=False, retries=args.retries)
        else:
            print(f"[studies] stage {stage}: {len(stage_jobs)} jobs", flush=True)
            res = rpc.execute_jobs(stage_jobs, max_workers=args.max_workers, plan_concurrency=args.plan_concurrency,
                                   plan_stagger_s=args.plan_stagger_s, min_free_gb=args.min_free_gb,
                                   poll_s=args.poll_s, tag="studies", overlap=args.overlap, retries=args.retries)
        if res["failed"]:
            with open(root / "failures.jsonl", "a", encoding="utf-8") as fh:
                for f in res["failed"]:
                    fh.write(json.dumps(f) + "\n")
            if stage == 0:
                print("[studies] stage-0 failures: dependent depleted-start runs will fail", flush=True)
        if stage == TRACE_STAGE:
            export_traces(root)


def main() -> None:
    p = argparse.ArgumentParser(description="Section 6 evaluation studies")
    p.add_argument("--study", required=True, help="comma list of: " + ", ".join(STUDIES) + " (or 'all')")
    p.add_argument("--root", default=str(DEFAULT_ROOT))
    p.add_argument("--binding-log-fraction", type=float, default=None,
                   help="Section 3 binding log fraction for A and B (default 1.0 = every decision)")
    p.add_argument("--max-workers", type=int, default=2)
    p.add_argument("--plan-concurrency", type=int, default=2)
    p.add_argument("--plan-stagger-s", type=float, default=300.0)
    p.add_argument("--overlap", dest="overlap", action="store_true", default=None,
                   help="run ordinary jobs alongside plan jobs (fastest); default for --study all")
    p.add_argument("--no-overlap", dest="overlap", action="store_false",
                   help="ordinary jobs of a stage first, then plan jobs")
    p.add_argument("--min-free-gb", type=float, default=rpc.MIN_FREE_GB)
    p.add_argument("--poll-s", type=float, default=rpc.MEMORY_POLL_S)
    p.add_argument("--retries", type=int, default=rpc.DEFAULT_RETRIES, help="retries of a failed run")
    p.add_argument("--allow-missing", action="store_true",
                   help="report a partial analysis instead of failing on missing seeds (seeds listed)")
    p.add_argument("--allow-mixed-commits", action="store_true",
                   help="compare runs from different code versions (default: refuse)")
    p.add_argument("--estimate", action="store_true", help="print the run counts and compute estimate and exit")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args()

    names = DEFAULT_ORDER if args.study.strip() == "all" else [s.strip() for s in args.study.split(",") if s.strip()]
    args.overlap = resolve_overlap(args.study, args.overlap)
    unknown = [n for n in names if n not in STUDIES]
    if unknown:
        raise SystemExit(f"unknown studies {unknown}; choose from {list(STUDIES)}")
    root = Path(args.root).resolve()
    args.root = str(root)
    studies = build_studies(names, args)
    for st in studies:
        for c in st.cells:
            if c.skip_reason:
                print(f"[studies] {st.name}/{c.name} SKIPPED: {c.skip_reason}", flush=True)
    if args.estimate:
        est = {name: compute_estimate(studies, root, rates, plan_concurrency=args.plan_concurrency,
                                      max_workers=args.max_workers)
               for name, rates in (("12_workers", RUN_HOURS_1800S), ("pool_2", RUN_HOURS_1800S_POOL2))}
        print(json.dumps(est, indent=2))
        return

    if not args.analyze_only:
        jobs = order_jobs([j for st in studies for j in collect_jobs(st, root)], DEFAULT_ORDER)
        if args.dry_run:
            for stage, stage_jobs, isolated in schedule(jobs):
                for j in stage_jobs:
                    state = "done" if Path(j["raw_json"]).exists() else (
                        "plan" if rpc.is_plan_job(j["params"]) else "ordinary")
                    print(f"stage{stage}{' isolated' if isolated else ''} {j['study']}/{j['cell']} {j['system']} "
                          f"seed={j['seed']} {state}")
            print(f"[studies] {len(jobs)} jobs, {sum(1 for j in jobs if not Path(j['raw_json']).exists())} pending")
            return
        run_scheduled(jobs, args, root)
    errors = []
    for st in studies:
        try:
            analyze_study(st, root, args.allow_missing, args.allow_mixed_commits)
            print(f"[studies] analyzed {st.name} -> {root / st.name}", flush=True)
        except (rpc.MissingSeedsError, rpc.MixedCommitsError) as exc:
            errors.append(f"{st.name}: {exc}")
            print(f"[studies] ANALYSIS ERROR {st.name}: {exc}", flush=True)
    if errors:
        raise SystemExit("analysis refused for: " + "; ".join(errors))


if __name__ == "__main__":
    main()
