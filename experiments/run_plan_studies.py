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
                p in {0.1, 0.3, 0.5} with D = 0, B5_c and E_plan, seeds 300-309 (decision 18).
  timeout       heavy, E_plan with plan_compute_budget_s = 45 vs E_plan without budget,
                dev seeds 200-209 (decision 16).
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
  persistent    production T_rec 1800 s, 5400 s runs, outcome windows [0, 1800) and
                [1800, 5400], {fresh, depleted} x {spare->heavy, heavy->spare} switching at
                2700 s (mu_step_time_s / mu_step_factor); depleted start = cue state at the
                end of an 1800 s B5_c run at the same starting load and seed
                (save_final_hab_state_path, generated first); B5_c, D_plan, E_plan; seeds
                300-309 (decision 22).
  timed_recovery  E_plan_tr vs E_plan (decision 2, exploratory): 3 loads, seeds 300-309,
                thresholds from docs/calibration/timed_recovery_thresholds.json, E_plan
                reference from confirmatory (user decision 2026-10-22).

Section 3 binding log (decision 27): every decision (fraction 1.0, user decision 2026-10-22)
of variants A and B in the confirmatory study is logged to raw/<system>_seed_<seed>_binding.jsonl.
Measured size (heavy 300 s: about 0.59 MB for A and B; overload 600 s: 2.2 MB for A)
projects to about 1-2 GB for 30 seeds x 3 loads x {A, B}, so plain JSONL is kept.

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
    stage: int = 1                   # 0 runs (and finishes) before 1
    skip_reason: Optional[str] = None


@dataclass
class Study:
    name: str
    cells: list
    description: str = ""


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


def study_neighbor(args) -> Study:
    cells = []
    for d in (30.0, 120.0, 300.0):
        cells.append(Cell(name=f"delay_{int(d)}s", mu=LOADS["heavy"], hab_on=True, variants=["B5_c", "E_plan"],
                          seeds=EVAL_SEEDS_10,
                          extra={"planner_hab_mode": "per_robot", "neighbor_delay_s": d, "neighbor_drop_prob": 0.0},
                          comparisons=[_pair("B5_c", "E_plan")]))
    for p in (0.1, 0.3, 0.5):
        cells.append(Cell(name=f"drop_{_tag(p)}", mu=LOADS["heavy"], hab_on=True, variants=["B5_c", "E_plan"],
                          seeds=EVAL_SEEDS_10,
                          extra={"planner_hab_mode": "per_robot", "neighbor_delay_s": 0.0, "neighbor_drop_prob": p},
                          comparisons=[_pair("B5_c", "E_plan")]))
    return Study("neighbor", cells, "per-robot information, delayed or dropped neighbor histories, heavy, 10 seeds")


def study_timeout(args) -> Study:
    ref = ("timeout/no_budget", "E_plan", "E_plan@no_budget")
    cells = [
        Cell(name="no_budget", mu=LOADS["heavy"], hab_on=True, variants=["E_plan"], seeds=DEV_SEEDS_10),
        Cell(name="budget_45s", mu=LOADS["heavy"], hab_on=True, variants=["E_plan"], seeds=DEV_SEEDS_10,
             extra={"plan_compute_budget_s": 45.0}, reuse=[ref],
             comparisons=[_pair("E_plan@no_budget", "E_plan", "E_plan 45 s budget vs no budget")]),
    ]
    return Study("timeout", cells, "45 s wall-clock budget, heavy, dev seeds 200-209")


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
DEFAULT_ORDER = ["confirmatory", "zero_hab", "floor", "timed_recovery", "mismatch", "neighbor", "disturbance",
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
                job["stage"] = int(cell.stage)
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


def analyze_study(study: Study, root: Path) -> list:
    out_dir = Path(root) / study.name
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = list(rpc.REPORT_METRICS)
    if study.name == "persistent":
        metrics = PERSISTENT_WINDOW_METRICS + metrics
    all_stats = []
    lines = [f"# Study: {study.name}", "", study.description, "",
             "Paired by seed within each cell; 95% percentile bootstrap over seed pairs (10000 resamples);",
             "percent effect = mean paired difference / reference mean x 100. Exploratory (nominal).", ""]
    for cell in study.cells:
        if cell.skip_reason:
            lines += [f"## {cell.name}", "", f"SKIPPED: {cell.skip_reason}", ""]
            continue
        rows = cell_rows(root, study, cell)
        cdir = cell_dir(root, study.name, cell.name)
        if (cdir / "raw").exists():
            _write_csv(rpc.flat_rows(rpc.load_rows(cdir)), cdir / "per_run_metrics.csv")
        hab = "hab_on" if cell.hab_on else "hab_off"
        stats = rpc.analyze(rows, None, hab, cell.comparisons, metrics) if cell.comparisons else []
        n_runs = {v: sum(1 for r in rows if r["variant"] == v) for v in sorted({r["variant"] for r in rows})}
        lines += [f"## {cell.name}", "", f"mu={cell.mu:g}, {hab}, seeds {cell.seeds[0]}-{cell.seeds[-1]}, "
                  f"extra={json.dumps({k: v for k, v in cell.extra.items() if not k.startswith('__')})}",
                  f"runs present: {json.dumps(n_runs)}", ""]
        if stats:
            lines += ["| Comparison | Metric | n | Ref mean | Diff | 95% CI | % of ref |",
                      "| --- | --- | --- | --- | --- | --- | --- |"]
        for s in stats:
            s = dict(s, study=study.name, cell=cell.name)
            all_stats.append(s)
            lines.append(f"| {s['comparison']} | {s['metric']} | {s['n']} | {s['ref_mean']:.4g} | "
                         f"{s['mean_diff']:+.4g} | [{s['ci_lo']:+.4g}, {s['ci_hi']:+.4g}] | {s['pct_of_ref']:+.2f}% |")
        lines.append("")
    _write_csv(all_stats, out_dir / "paired_stats.csv")
    (out_dir / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if study.name == "confirmatory":
        _confirmatory_family(study, root)
    return all_stats


def _confirmatory_family(study: Study, root: Path) -> None:
    from experiments import analyze_plan_confirmatory as apc
    dirs = {c.name: cell_dir(root, study.name, c.name) for c in study.cells}
    if not all((d / "raw").exists() for d in dirs.values()):
        print("[studies] confirmatory family: some load directories missing; skipped", flush=True)
        return
    apc.run_family(treatment="E_plan", reference="B5_c", dirs=dirs, expected_n=len(EVAL_SEEDS_30),
                   out=Path(root) / study.name / "confirmatory_family")


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

    if not args.analyze_only:
        jobs = order_jobs([j for st in studies for j in collect_jobs(st, root)], DEFAULT_ORDER)
        if args.dry_run:
            for j in jobs:
                state = "done" if Path(j["raw_json"]).exists() else (
                    "plan" if rpc.is_plan_job(j["params"]) else "ordinary")
                print(f"stage{j['stage']} {j['study']}/{j['cell']} {j['system']} seed={j['seed']} {state}")
            print(f"[studies] {len(jobs)} jobs, {sum(1 for j in jobs if not Path(j['raw_json']).exists())} pending")
            return
        for stage in sorted({j["stage"] for j in jobs}):
            stage_jobs = [j for j in jobs if j["stage"] == stage]
            print(f"[studies] stage {stage}: {len(stage_jobs)} jobs", flush=True)
            res = rpc.execute_jobs(stage_jobs, max_workers=args.max_workers, plan_concurrency=args.plan_concurrency,
                                   plan_stagger_s=args.plan_stagger_s, min_free_gb=args.min_free_gb,
                                   poll_s=args.poll_s, tag="studies", overlap=args.overlap)
            if res["failed"]:
                with open(root / "failures.jsonl", "a", encoding="utf-8") as fh:
                    for f in res["failed"]:
                        fh.write(json.dumps(f) + "\n")
                if stage == 0:
                    print("[studies] stage-0 failures: dependent depleted-start runs will fail", flush=True)
    for st in studies:
        analyze_study(st, root)
        print(f"[studies] analyzed {st.name} -> {root / st.name}", flush=True)


if __name__ == "__main__":
    main()
