"""
reproduce_acc_submission.py -- Section 7 work package 1: reproduction table of the ACC paper.

Runs A = B4 (ladder B4_res_stl_full_multicue), B1 and B5 in the ORIGINAL legacy setup:
the ladder paper configuration exactly as the submission ran it (legacy single random
stream, window200 truth deterrence memory, legacy estimator, no new flags), via
run_plan_completion.build_params("B4" / "B1" / "B5") (LEGACY_VARIANTS).  Loads: spare
2e-5 (hab on and off: the paper reports both), heavy-spare 1e-4 and high-demand 4e-4
(hab on).  Seeds: --seeds, default the evaluation seeds 300-329.

NOTE on seeds: the archived ACC per-run data (results/testbench/acc_submission/data) used
seeds 125-154.  Running with --seeds 125-154 additionally gives a per-seed exact check
against the archive (--archive-dir); with 300-329 the table is a reproduction on fresh
seeds, compared only with the paper's summary numbers.

Paper numbers compared (docs/GB_ACC_2027_v2.pdf):
  Sec. V-A / Table I (spare, kappa 0.50, n = 30, % of B1, paired bootstrap 95% CI):
    hab on:  B4 -9.3 [-11.1, -7.5], B5 -5.4 [-7.0, -3.9]
    hab off: B4 +3.2 [+0.9, +5.4],  B5 -0.0 [-2.5, +2.4]
  Table IV (B4 - B5 as % of B1, hab on, nominal two-sided Wilcoxon, B4 wins):
    spare -3.9 (p 0.002, 23/30, absolute 95% CI [-2506, -730]),
    heavy-spare -3.1 (p 0.006, 22/30), high-demand +4.8 (p < 0.001, 3/30)
  Table VII (B1 / B4 reactive miss rate %, response time s, B4/B1 travel):
    spare 24.7 / 42.4, 80.6 / 99.8, 1.06; heavy-spare 26.7 / 47.1, 74.8 / 99.1, 1.45;
    high-demand 52.4 / 65.8, 70.2 / 101.3, 1.46.  Miss rate here = 1 - reactive_completed_
    fraction (the definition in experiments/plot_acc_results.py); the archived 30-seed
    ladder gives different Table VII values, so the paper's Table VII source data set is
    not identified (reported for comparison only).

Usage:
  py -3.10 -m experiments.reproduce_acc_submission [--seeds 300-329] [--dry-run]
  py -3.10 -m experiments.reproduce_acc_submission --seeds 125-154 \
      --archive-dir results/testbench/acc_submission/data
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
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
# (cell, load name, mu, hab_on)
CELLS = [("spare_hab_on", "spare", 2e-5, True), ("spare_hab_off", "spare", 2e-5, False),
         ("heavy_hab_on", "heavy", 1e-4, True), ("overload_hab_on", "overload", 4e-4, True)]
PAPER_VS_B1 = {  # (cell, system) -> (pct, lo, hi)
    ("spare_hab_on", "B4"): (-9.3, -11.1, -7.5), ("spare_hab_on", "B5"): (-5.4, -7.0, -3.9),
    ("spare_hab_off", "B4"): (3.2, 0.9, 5.4), ("spare_hab_off", "B5"): (-0.0, -2.5, 2.4),
}
PAPER_B4_B5 = {  # cell -> (pct of B1, p, wins, abs CI or None)
    "spare_hab_on": (-3.9, "0.002", "23/30", (-2506.0, -730.0)),
    "heavy_hab_on": (-3.1, "0.006", "22/30", None),
    "overload_hab_on": (4.8, "< 0.001", "3/30", None),
}
PAPER_TABLE_VII = {  # cell -> (B1 miss %, B4 miss %, B1 RT, B4 RT, B4/B1 travel)
    "spare_hab_on": (24.7, 42.4, 80.6, 99.8, 1.06),
    "heavy_hab_on": (26.7, 47.1, 74.8, 99.1, 1.45),
    "overload_hab_on": (52.4, 65.8, 70.2, 101.3, 1.46),
}
ARCHIVE_FILES = {"spare": "ladder_per_run_metrics.csv", "heavy": "ladder_heavy_spare_per_run_metrics.csv",
                 "overload": "ladder_overloaded_per_run_metrics.csv"}
LADDER_NAME = {"B1": "B1_greedy_fixedcue", "B4": "B4_res_stl_full_multicue", "B5": "B5_greedy_habcue"}


def build_jobs(root: Path, seeds: list) -> list:
    jobs = []
    for cell, _load, mu, hab_on in CELLS:
        raw = root / cell / "raw"
        for seed in seeds:
            for s in SYSTEMS:
                jobs.append(rpc.make_job(raw, s, hab_on, seed, rpc.build_params(s, hab_on, mu, None),
                                         study="acc_reproduction", cell=cell))
    return jobs


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


def analyze(root: Path, archive_dir: Path | None) -> str:
    from scipy.stats import wilcoxon

    lines = ["# ACC reproduction (Section 7)", "",
             "Original legacy setup (ladder paper configuration, legacy streams, window200 memory, no new",
             "flags). Percentages are of the B1 mean (paired mean difference / B1 mean x 100); 95% CIs by",
             "paired percentile bootstrap over seeds (10000 resamples); p = nominal two-sided Wilcoxon.", ""]
    table = []
    rows_by_cell = {cell: (rpc.load_rows(root / cell) if (root / cell / "raw").exists() else [])
                    for cell, *_ in CELLS}
    lines += ["## Exposure vs B1 (Table I / Sec. V-A)", "",
              "| Cell | System | n | Reproduced % of B1 | 95% CI | Paper % | Paper CI |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for cell, *_ in CELLS:
        rows = rows_by_cell[cell]
        for s in ("B4", "B5"):
            a, b = _paired(rows, "B1", s, "value_weighted_exposure")
            if a.size == 0:
                continue
            d = b - a
            lo, hi = _boot(d)
            pct, plo, phi = 100 * d.mean() / a.mean(), 100 * lo / a.mean(), 100 * hi / a.mean()
            paper = PAPER_VS_B1.get((cell, s))
            table.append({"table": "vs_B1", "cell": cell, "system": s, "n": int(d.size), "pct_of_B1": pct,
                          "ci_lo_pct": plo, "ci_hi_pct": phi,
                          "paper_pct": paper[0] if paper else "", "paper_ci": f"{paper[1]},{paper[2]}" if paper else ""})
            lines.append(f"| {cell} | {s} | {d.size} | {pct:+.1f}% | [{plo:+.1f}, {phi:+.1f}] | "
                         + (f"{paper[0]:+.1f}% | [{paper[1]:+.1f}, {paper[2]:+.1f}] |" if paper else "- | - |"))
    lines += ["", "## B4 - B5 (Table IV, hab on)", "",
              "| Cell | n | Mean diff | Abs 95% CI | % of B1 | p | B4 wins | Paper % | Paper p | Paper wins |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
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
        table.append({"table": "B4_minus_B5", "cell": cell, "n": int(d.size), "mean_diff": float(d.mean()),
                      "ci_lo": lo, "ci_hi": hi, "pct_of_B1": pct, "p": p, "wins": wins,
                      "paper_pct": paper[0], "paper_p": paper[1], "paper_wins": paper[2]})
        lines.append(f"| {cell} | {d.size} | {d.mean():+,.0f} | [{lo:+,.0f}, {hi:+,.0f}] | {pct:+.1f}% | {p:.4f} | "
                     f"{wins} | {paper[0]:+.1f}% | {paper[1]} | {paper[2]} |")
    lines += ["", "## Service (Table VII; paper source data set not identified, comparison only)", "",
              "| Cell | B1 miss % | B4 miss % | B1 RT react (s) | B4 RT react (s) | B1 RT all (s) | B4 RT all (s) | "
              "B4/B1 travel | Paper (B1/B4 miss, B1/B4 RT, travel) |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cell, paper in PAPER_TABLE_VII.items():
        rows = rows_by_cell[cell]
        if not rows:
            continue
        m1 = 100 * (1 - _mean(rows, "B1", "reactive_completed_fraction"))
        m4 = 100 * (1 - _mean(rows, "B4", "reactive_completed_fraction"))
        tr = _mean(rows, "B4", "travel_distance_total") / _mean(rows, "B1", "travel_distance_total")
        vals = [m1, m4, _mean(rows, "B1", "reactive_mean_response_time_s"), _mean(rows, "B4", "reactive_mean_response_time_s"),
                _mean(rows, "B1", "mean_response_time_s"), _mean(rows, "B4", "mean_response_time_s"), tr]
        table.append({"table": "service", "cell": cell, "B1_miss_pct": vals[0], "B4_miss_pct": vals[1],
                      "B1_rt_reactive_s": vals[2], "B4_rt_reactive_s": vals[3], "B1_rt_all_s": vals[4],
                      "B4_rt_all_s": vals[5], "travel_ratio": vals[6], "paper": json.dumps(paper)})
        lines.append(f"| {cell} | " + " | ".join(f"{v:.1f}" for v in vals[:6]) + f" | {vals[6]:.2f} | {paper} |")
    if archive_dir is not None:
        lines += ["", "## Exact per-seed check against the archived ACC per-run data", "",
                  "| Cell | System | Seeds compared | Max abs rel. diff (VWE) | Identical |", "| --- | --- | --- | --- | --- |"]
        for cell, load, _mu, hab_on in CELLS:
            path = Path(archive_dir) / ARCHIVE_FILES[load]
            if not path.exists():
                continue
            arc = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
            cond = "hab_on" if hab_on else "hab_off"
            for s in SYSTEMS:
                ref = {int(float(r["seed"])): float(r["value_weighted_exposure"]) for r in arc
                       if r.get("baseline") == LADDER_NAME[s] and r.get("habituation_condition") == cond}
                mine = _by_seed(rows_by_cell[cell], s, "value_weighted_exposure")
                common = sorted(set(ref) & set(mine))
                if not common:
                    continue
                rel = max(abs(mine[k] - ref[k]) / abs(ref[k]) for k in common)
                table.append({"table": "archive_check", "cell": cell, "system": s, "n": len(common), "max_rel_diff": rel})
                lines.append(f"| {cell} | {s} | {len(common)} | {rel:.3g} | {rel == 0.0} |")
    _write_csv(table, root / "reproduction_table.csv")
    text = "\n".join(lines) + "\n"
    (root / "reproduction_table.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    p = argparse.ArgumentParser(description="ACC reproduction table (Section 7)")
    p.add_argument("--root", default="results/acc_reproduction")
    p.add_argument("--seeds", default="300-329")
    p.add_argument("--archive-dir", default=None,
                   help="results/testbench/acc_submission/data for a per-seed exact check (seeds 125-154)")
    p.add_argument("--max-workers", type=int, default=2)
    p.add_argument("--min-free-gb", type=float, default=rpc.MIN_FREE_GB)
    p.add_argument("--poll-s", type=float, default=rpc.MEMORY_POLL_S)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args()
    from experiments.run_plan_studies import _parse_seeds

    root = Path(args.root).resolve()
    seeds = _parse_seeds(args.seeds)
    jobs = build_jobs(root, seeds)
    if args.dry_run:
        pending = [j for j in jobs if not Path(j["raw_json"]).exists()]
        print(f"[repro] {len(jobs)} jobs, {len(pending)} pending")
        return
    if not args.analyze_only:
        rpc.execute_jobs(jobs, max_workers=args.max_workers, min_free_gb=args.min_free_gb, poll_s=args.poll_s,
                         tag="repro")
    print(analyze(root, Path(args.archive_dir) if args.archive_dir else None))


if __name__ == "__main__":
    main()
