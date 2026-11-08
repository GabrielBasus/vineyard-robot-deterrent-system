"""
reproduce_acc_submission.py -- Section 7 work package 1: reproduction table of the ACC paper.

Everything runs in the ORIGINAL legacy setup: the ladder paper configuration exactly as the
submission ran it (legacy single random stream, window200 truth deterrence memory, legacy
estimator, no new flags), via run_plan_completion.build_params with LEGACY_VARIANTS.

Two designs, each matching its source in the paper (docs/GB_ACC_2027_v2.pdf):

1. Main ladder (Sec. V-A, Table I, Table IV): A = B4 (B4_res_stl_full_multicue), B1, B5;
   cells spare 2e-5 hab on and off, heavy-spare 1e-4 hab on, high-demand 4e-4 hab on;
   n = 30.  Run on BOTH seed sets (user decision 2026-10-22):
     125-154  the archived ACC seeds; adds a per-seed exact check against
              results/testbench/acc_submission/data/*per_run_metrics.csv;
     300-329  fresh evaluation seeds (reproduction of the summary numbers only).
   Paper numbers and their computation (experiments/plot_acc_results.py):
     Table I (spare, % of B1): mean over seeds of 100 (x_s - mean(B1)) / mean(B1), interval
       = mean +- 1.96 sd / sqrt(n) of those per-seed values (plot_acc_results._ci95; a normal
       interval of per-seed changes relative to the B1 MEAN, not a paired bootstrap):
       hab on B4 -9.3 [-11.1, -7.5], B5 -5.4 [-7.0, -3.9]; hab off B4 +3.2 [+0.9, +5.4],
       B5 -0.0 [-2.5, +2.4].  The paired percentile bootstrap is reported alongside.
     Table IV (B4 - B5 as % of B1 mean, hab on, nominal two-sided Wilcoxon, B4 wins):
       spare -3.9 (p 0.002, 23/30, absolute CI [-2506, -730]), heavy-spare -3.1 (p 0.006,
       22/30), high-demand +4.8 (p < 0.001, 3/30).
2. Joint-sweep cells (Table VII): B1, B3 (B3_res_stl_nohab_multicue) and B4; kappa 0.50,
   hab on, n = 10, seeds 125-134, the joint-sweep parameters (identical to the ladder paper
   configuration; experiments/run_habituation_stl_joint_sweep._base_ladder_args).
   Source: results/testbench/habituation_stl_joint_sweep/mu_{2em05,1em04,4em04}_kappa_0p50/
   per_run_metrics.csv.  Miss rate = 100 (1 - mean reactive_completed_fraction); RT = mean
   reactive_mean_response_time_s; travel = mean B4 travel_distance_total / mean B1:
     miss B1 24.7/26.7/52.4, B3 35.4/46.4/66.3, B4 42.4/47.1/65.8;
     RT B1 80.6/74.8/70.2, B4 99.8/99.1/101.3; travel 1.06/1.45/1.46.
   B3 is run for this table only.  A per-seed exact check against the source is added.

Usage:
  py -3.10 -m experiments.reproduce_acc_submission [--dry-run]
  py -3.10 -m experiments.reproduce_acc_submission --analyze-only
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics as stats
import sys
from pathlib import Path

os.environ.setdefault("DETERRENT_TELEMETRY", "0")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from experiments import run_plan_completion as rpc
from experiments.run_habituation_stl_production_ladder import _write_csv

SYSTEMS = ["B1", "B4", "B5"]
TABLE7_SYSTEMS = ["B1", "B3", "B4"]
SEED_SETS = ("125-154", "300-329")
TABLE7_SEEDS = list(range(125, 135))
# (cell, load name, mu, hab_on)
CELLS = [("spare_hab_on", "spare", 2e-5, True), ("spare_hab_off", "spare", 2e-5, False),
         ("heavy_hab_on", "heavy", 1e-4, True), ("overload_hab_on", "overload", 4e-4, True)]
TABLE7_CELLS = [("joint_spare", "spare", 2e-5, "mu_2em05_kappa_0p50"),
                ("joint_heavy", "heavy", 1e-4, "mu_1em04_kappa_0p50"),
                ("joint_overload", "overload", 4e-4, "mu_4em04_kappa_0p50")]
PAPER_VS_B1 = {  # (cell, system) -> (pct, lo, hi)
    ("spare_hab_on", "B4"): (-9.3, -11.1, -7.5), ("spare_hab_on", "B5"): (-5.4, -7.0, -3.9),
    ("spare_hab_off", "B4"): (3.2, 0.9, 5.4), ("spare_hab_off", "B5"): (-0.0, -2.5, 2.4),
}
PAPER_B4_B5 = {  # cell -> (pct of B1, p, wins)
    "spare_hab_on": (-3.9, "0.002", "23/30"),
    "heavy_hab_on": (-3.1, "0.006", "22/30"),
    "overload_hab_on": (4.8, "< 0.001", "3/30"),
}
PAPER_TABLE_VII = {  # cell -> miss% B1, B3, B4; RT B1, B4; travel B4/B1
    "joint_spare": {"miss_B1": 24.7, "miss_B3": 35.4, "miss_B4": 42.4, "rt_B1": 80.6, "rt_B4": 99.8, "travel": 1.06},
    "joint_heavy": {"miss_B1": 26.7, "miss_B3": 46.4, "miss_B4": 47.1, "rt_B1": 74.8, "rt_B4": 99.1, "travel": 1.45},
    "joint_overload": {"miss_B1": 52.4, "miss_B3": 66.3, "miss_B4": 65.8, "rt_B1": 70.2, "rt_B4": 101.3,
                       "travel": 1.46},
}
ARCHIVE_FILES = {"spare": "ladder_per_run_metrics.csv", "heavy": "ladder_heavy_spare_per_run_metrics.csv",
                 "overload": "ladder_overloaded_per_run_metrics.csv"}
LADDER_NAME = {"B1": "B1_greedy_fixedcue", "B3": "B3_res_stl_nohab_multicue", "B4": "B4_res_stl_full_multicue",
               "B5": "B5_greedy_habcue"}


def find_testbench() -> Path | None:
    """results/testbench holding the archived ACC data (worktrees: search the parents)."""
    for base in [_root, *_root.parents]:
        tb = base / "results" / "testbench"
        if (tb / "acc_submission" / "data").exists():
            return tb
    return None


# ---------------------------------------------------------------- jobs
def seed_set_dir(root: Path, seed_set: str) -> Path:
    return Path(root) / f"seeds_{seed_set.replace('-', '_')}"


def build_jobs(root: Path, seed_sets=SEED_SETS) -> list:
    from experiments.run_plan_studies import _parse_seeds
    jobs = []
    for ss in seed_sets:
        base = seed_set_dir(root, ss)
        for cell, _load, mu, hab_on in CELLS:
            raw = base / cell / "raw"
            for seed in _parse_seeds(ss):
                for s in SYSTEMS:
                    jobs.append(rpc.make_job(raw, s, hab_on, seed, rpc.build_params(s, hab_on, mu, None),
                                             study="acc_reproduction", cell=f"{ss}/{cell}"))
    for cell, _load, mu, _src in TABLE7_CELLS:
        raw = Path(root) / "table_vii" / cell / "raw"
        for seed in TABLE7_SEEDS:
            for s in TABLE7_SYSTEMS:
                jobs.append(rpc.make_job(raw, s, True, seed, rpc.build_params(s, True, mu, None),
                                         study="acc_reproduction", cell=f"table_vii/{cell}"))
    return jobs


# ---------------------------------------------------------------- statistics
def _by_seed(rows, variant, metric):
    out = {}
    for r in rows:
        if r["variant"] == variant:
            try:
                v = float(r.get(metric))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                out[int(r["seed"])] = v
    return out


def _paired(rows, ref, trt, metric):
    a, b = _by_seed(rows, ref, metric), _by_seed(rows, trt, metric)
    seeds = sorted(set(a) & set(b))
    return np.array([a[s] for s in seeds]), np.array([b[s] for s in seeds])


def _boot(d, n=10000, seed=12345):
    if d.size < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    m = d[rng.integers(0, d.size, size=(n, d.size))].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def _mean(rows, variant, metric):
    v = list(_by_seed(rows, variant, metric).values())
    return float(np.mean(v)) if v else float("nan")


def paper_table1_interval(rows, system: str) -> tuple:
    """Table I as computed for the paper (plot_acc_results): per-seed 100 (x - mean B1) / mean B1,
    mean and mean +- 1.96 sd / sqrt(n)."""
    b1 = list(_by_seed(rows, "B1", "value_weighted_exposure").values())
    vals = list(_by_seed(rows, system, "value_weighted_exposure").values())
    if len(b1) < 1 or len(vals) < 2:
        return float("nan"), float("nan"), float("nan"), len(vals)
    ref = stats.mean(b1)
    pct = [(v - ref) / ref * 100 for v in vals]
    m = stats.mean(pct)
    hw = 1.96 * stats.stdev(pct) / math.sqrt(len(pct))
    return m, m - hw, m + hw, len(pct)


def table7_values(rows) -> dict:
    """Table VII quantities from per-run rows with variants B1, B3, B4."""
    out = {}
    for s in TABLE7_SYSTEMS:
        out[f"miss_{s}"] = 100.0 * (1.0 - _mean(rows, s, "reactive_completed_fraction"))
    out["rt_B1"] = _mean(rows, "B1", "reactive_mean_response_time_s")
    out["rt_B4"] = _mean(rows, "B4", "reactive_mean_response_time_s")
    out["travel"] = _mean(rows, "B4", "travel_distance_total") / _mean(rows, "B1", "travel_distance_total")
    return out


def archive_rows(csv_path: Path, systems, hab: str = "hab_on") -> list:
    """Archived per-run rows renamed to the reproduction's variant names."""
    inv = {LADDER_NAME[s]: s for s in systems}
    out = []
    for r in csv.DictReader(Path(csv_path).open(encoding="utf-8", newline="")):
        if r.get("baseline") in inv and r.get("habituation_condition") == hab:
            d = dict(r)
            d["variant"] = inv[r["baseline"]]
            d["seed"] = int(float(r["seed"]))
            out.append(d)
    return out


def _exact_check(lines, table, label, mine_rows, ref_rows, systems, metrics):
    for s in systems:
        for metric in metrics:
            ref = _by_seed(ref_rows, s, metric)
            mine = _by_seed(mine_rows, s, metric)
            common = sorted(set(ref) & set(mine))
            if not common:
                continue
            rel = max(abs(mine[k] - ref[k]) / max(abs(ref[k]), 1e-12) for k in common)
            table.append({"table": "archive_check", "cell": label, "system": s, "metric": metric,
                          "n": len(common), "max_rel_diff": rel})
            lines.append(f"| {label} | {s} | {metric} | {len(common)} | {rel:.3g} | {rel == 0.0} |")


def _load_dir(d: Path) -> list:
    return rpc.load_rows(d) if (Path(d) / "raw").exists() else []


def analyze(root: Path, testbench: Path | None) -> str:
    from scipy.stats import wilcoxon

    root = Path(root)
    table = []
    lines = ["# ACC reproduction (Section 7)", "",
             "Original legacy setup (ladder paper configuration, legacy streams, window200 memory, no new flags).", ""]
    for ss in SEED_SETS:
        base = seed_set_dir(root, ss)
        rows_by_cell = {cell: _load_dir(base / cell) for cell, *_ in CELLS}
        if not any(rows_by_cell.values()):
            continue
        lines += [f"## Seeds {ss}", "", "### Exposure vs B1 (Table I / Sec. V-A)", "",
                  "Paper method: per-seed % change vs the B1 mean, mean +- 1.96 sd/sqrt(n). Also the paired "
                  "percentile bootstrap of the mean paired difference (% of the B1 mean).", "",
                  "| Cell | System | n | Paper-method % [interval] | Paired bootstrap % [CI] | Paper |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for cell, *_ in CELLS:
            rows = rows_by_cell[cell]
            for s in ("B4", "B5"):
                m, lo, hi, n = paper_table1_interval(rows, s)
                a, b = _paired(rows, "B1", s, "value_weighted_exposure")
                if a.size == 0:
                    continue
                d = b - a
                blo, bhi = _boot(d)
                pb = (100 * d.mean() / a.mean(), 100 * blo / a.mean(), 100 * bhi / a.mean())
                paper = PAPER_VS_B1.get((cell, s))
                table.append({"table": "vs_B1", "seeds": ss, "cell": cell, "system": s, "n": n,
                              "pct": m, "lo": lo, "hi": hi, "paired_pct": pb[0], "paired_lo": pb[1],
                              "paired_hi": pb[2], "paper": json.dumps(paper)})
                lines.append(f"| {cell} | {s} | {n} | {m:+.1f} [{lo:+.1f}, {hi:+.1f}] | "
                             f"{pb[0]:+.1f} [{pb[1]:+.1f}, {pb[2]:+.1f}] | "
                             + (f"{paper[0]:+.1f} [{paper[1]:+.1f}, {paper[2]:+.1f}] |" if paper else "- |"))
        lines += ["", "### B4 - B5 (Table IV, hab on)", "",
                  "| Cell | n | Mean diff | Abs 95% CI | % of B1 | p | B4 wins | Paper |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for cell, paper in PAPER_B4_B5.items():
            rows = rows_by_cell[cell]
            a, b = _paired(rows, "B5", "B4", "value_weighted_exposure")
            if a.size == 0:
                continue
            d = b - a
            lo, hi = _boot(d)
            b1 = _mean(rows, "B1", "value_weighted_exposure")
            p = float(wilcoxon(d).pvalue) if d.size >= 2 and np.any(d != 0) else float("nan")
            wins = f"{int(np.sum(d < 0))}/{d.size}"
            pct = 100 * d.mean() / b1
            table.append({"table": "B4_minus_B5", "seeds": ss, "cell": cell, "n": int(d.size),
                          "mean_diff": float(d.mean()), "ci_lo": lo, "ci_hi": hi, "pct_of_B1": pct, "p": p,
                          "wins": wins, "paper": json.dumps(paper)})
            lines.append(f"| {cell} | {d.size} | {d.mean():+,.0f} | [{lo:+,.0f}, {hi:+,.0f}] | {pct:+.1f}% | "
                         f"{p:.4f} | {wins} | {paper[0]:+.1f}%, p {paper[1]}, {paper[2]} |")
        if testbench is not None and ss == "125-154":
            lines += ["", "### Exact per-seed check against the archived ACC per-run data", "",
                      "| Cell | System | Metric | Seeds | Max abs rel. diff | Identical |",
                      "| --- | --- | --- | --- | --- | --- |"]
            for cell, load, _mu, hab_on in CELLS:
                path = testbench / "acc_submission" / "data" / ARCHIVE_FILES[load]
                if path.exists():
                    _exact_check(lines, table, f"{ss}/{cell}", rows_by_cell[cell],
                                 archive_rows(path, SYSTEMS, "hab_on" if hab_on else "hab_off"), SYSTEMS,
                                 ["value_weighted_exposure"])
        lines.append("")
    lines += ["## Table VII (joint-sweep design: B1, B3, B4, kappa 0.50, hab on, seeds 125-134)", "",
              "| Cell | Source | miss B1 | miss B3 | miss B4 | RT B1 | RT B4 | travel B4/B1 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    check_lines = []
    for cell, _load, _mu, src in TABLE7_CELLS:
        rows = _load_dir(root / "table_vii" / cell)
        srcs = [("reproduced", rows), ("paper", None)]
        if testbench is not None:
            p = testbench / "habituation_stl_joint_sweep" / src / "per_run_metrics.csv"
            if p.exists():
                arc = archive_rows(p, TABLE7_SYSTEMS)
                srcs.insert(1, ("archive", arc))
                if rows:
                    _exact_check(check_lines, table, f"table_vii/{cell}", rows, arc, TABLE7_SYSTEMS,
                                 ["value_weighted_exposure", "reactive_completed_fraction",
                                  "reactive_mean_response_time_s", "travel_distance_total"])
        for label, rr in srcs:
            if label == "paper":
                v = PAPER_TABLE_VII[cell]
            elif not rr:
                continue
            else:
                v = table7_values(rr)
                table.append({"table": "table_vii", "cell": cell, "source": label, **v})
            lines.append(f"| {cell} | {label} | {v['miss_B1']:.1f} | {v['miss_B3']:.1f} | {v['miss_B4']:.1f} | "
                         f"{v['rt_B1']:.1f} | {v['rt_B4']:.1f} | {v['travel']:.2f} |")
    if check_lines:
        lines += ["", "### Exact per-seed check against the joint-sweep source", "",
                  "| Cell | System | Metric | Seeds | Max abs rel. diff | Identical |",
                  "| --- | --- | --- | --- | --- | --- |"] + check_lines
    _write_csv(table, root / "reproduction_table.csv")
    text = "\n".join(lines) + "\n"
    root.mkdir(parents=True, exist_ok=True)
    (root / "reproduction_table.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    p = argparse.ArgumentParser(description="ACC reproduction table (Section 7)")
    p.add_argument("--root", default="results/acc_reproduction")
    p.add_argument("--testbench", default=None,
                   help="results/testbench holding acc_submission/ and habituation_stl_joint_sweep/ "
                        "(default: searched from the repository root upward)")
    p.add_argument("--max-workers", type=int, default=2)
    p.add_argument("--min-free-gb", type=float, default=rpc.MIN_FREE_GB)
    p.add_argument("--poll-s", type=float, default=rpc.MEMORY_POLL_S)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--analyze-only", action="store_true")
    p.add_argument("--seed-sets", nargs="+", default=list(SEED_SETS), choices=list(SEED_SETS),
                   help="seed sets to run (Table VII cells always run); analysis covers whatever exists")
    args = p.parse_args()

    root = Path(args.root).resolve()
    tb = Path(args.testbench) if args.testbench else find_testbench()
    jobs = build_jobs(root, seed_sets=tuple(args.seed_sets))
    if args.dry_run:
        pending = [j for j in jobs if not Path(j["raw_json"]).exists()]
        print(f"[repro] {len(jobs)} jobs, {len(pending)} pending; archive {tb}")
        return
    if not args.analyze_only:
        rpc.execute_jobs(jobs, max_workers=args.max_workers, min_free_gb=args.min_free_gb, poll_s=args.poll_s,
                         tag="repro")
    print(analyze(root, tb))


if __name__ == "__main__":
    main()
