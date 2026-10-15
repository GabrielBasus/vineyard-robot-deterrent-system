"""
run_persistent_operation.py -- Plan §6 persistent operation experiment.

The submitted runs last 1800 s from fresh cues with constant demand. This sweep
extends evaluation to:
  * several recovery time constants T_rec (truth and planner share the value),
  * initially fresh (eta = 1.0) and initially depleted (eta = 0.3) cues,
  * a demand step within the run (mu x factor at a fixed time),
and reports the startup window and the later window separately, using the
per-window value-weighted exposure the simulator now records.

Habituation is on in every run. Systems default to B5, A (submitted B4) and the
proposed planner; seeds default to the evaluation set 300-329.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import os

# Batch runs must not append to telemetry_live/ (set before DeterrentSystem is imported).
os.environ.setdefault("DETERRENT_TELEMETRY", "0")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from experiments.run_habituation_stl_production_ladder import _write_csv
from experiments.run_plan_completion import bootstrap_ci, build_params, run_job

T_END_S = 5400.0
STARTUP_S = 900.0
WINDOW_S = 300.0

# name -> extra simulator params
CONDITIONS = {
    "trec600_fresh": {"habituation_T_rec_s": 600.0, "habituation_initial_eta": 1.0},
    "trec600_depleted": {"habituation_T_rec_s": 600.0, "habituation_initial_eta": 0.3},
    "trec1800_fresh": {"habituation_T_rec_s": 1800.0, "habituation_initial_eta": 1.0},
    "trec1800_depleted": {"habituation_T_rec_s": 1800.0, "habituation_initial_eta": 0.3},
    "trec5400_fresh": {"habituation_T_rec_s": 5400.0, "habituation_initial_eta": 1.0},
    "trec5400_depleted": {"habituation_T_rec_s": 5400.0, "habituation_initial_eta": 0.3},
    "trec1800_fresh_step": {"habituation_T_rec_s": 1800.0, "habituation_initial_eta": 1.0,
                            "mu_step_time_s": 2700.0, "mu_step_factor": 2.0},
}


def _window_sums(row, t_lo, t_hi):
    wins = row.get("value_weighted_exposure_windows") or []
    width = float(row.get("exposure_window_s") or WINDOW_S)
    return float(sum(w for k, w in enumerate(wins) if t_lo <= k * width < t_hi))


def analyze(rows, outdir: Path, reference: str, t_end: float) -> None:
    lines = ["# Persistent operation", "",
             f"T_end={t_end:.0f} s, startup window = first {STARTUP_S:.0f} s. Paired differences vs "
             f"{reference}; 95% bootstrap CI over seeds. Negative = less exposure.", ""]
    stats_rows = []
    for cond in CONDITIONS:
        crow = [r for r in rows if r.get("condition") == cond]
        systems = sorted({r["variant"] for r in crow} - {reference})
        if not crow or not systems:
            continue
        lines += [f"## {cond}", "", "| System | Measure | n | Ref mean | Diff | 95% CI | % of ref |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        ref = {r["seed"]: r for r in crow if r["variant"] == reference}
        for sysname in systems:
            trt = {r["seed"]: r for r in crow if r["variant"] == sysname}
            seeds = sorted(set(ref) & set(trt))
            if not seeds:
                continue
            measures = {
                "VWE total": lambda r: float(r["value_weighted_exposure"]),
                "VWE startup": lambda r: _window_sums(r, 0.0, STARTUP_S),
                "VWE later": lambda r: _window_sums(r, STARTUP_S, t_end + 1.0),
                "miss fraction": lambda r: float(r["reactive_miss_fraction"]),
            }
            for mname, fn in measures.items():
                a = np.array([fn(ref[s]) for s in seeds])
                b = np.array([fn(trt[s]) for s in seeds])
                ok = np.isfinite(a) & np.isfinite(b)
                a, b = a[ok], b[ok]
                if a.size == 0:
                    continue
                d = b - a
                lo, hi = bootstrap_ci(d)
                pct = 100.0 * d.mean() / a.mean() if a.mean() else float("nan")
                stats_rows.append({"condition": cond, "system": sysname, "measure": mname, "n": int(d.size),
                                   "ref_mean": float(a.mean()), "mean_diff": float(d.mean()),
                                   "ci_lo": lo, "ci_hi": hi, "pct_of_ref": float(pct)})
                lines.append(f"| {sysname} | {mname} | {d.size} | {a.mean():.4g} | {d.mean():+.4g} | "
                             f"[{lo:+.4g}, {hi:+.4g}] | {pct:+.2f}% |")
        lines.append("")
    _write_csv(stats_rows, outdir / "paired_stats.csv")
    (outdir / "persistent_operation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Plan §6 persistent operation sweep")
    p.add_argument("--outdir", default="results/testbench/persistent_operation")
    p.add_argument("--systems", default="B5,A,E_cue_adm")
    p.add_argument("--reference", default="B5")
    p.add_argument("--conditions", default=",".join(CONDITIONS))
    p.add_argument("--mu", type=float, default=1e-4)
    p.add_argument("--t-end", type=float, default=T_END_S)
    p.add_argument("--seed-start", type=int, default=300)
    p.add_argument("--num-runs", type=int, default=30)
    p.add_argument("--max-workers", type=int, default=1)
    p.add_argument("--analyze-only", action="store_true")
    args = p.parse_args()

    outdir = Path(args.outdir).resolve()
    raw = outdir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    systems = [s for s in args.systems.split(",") if s]
    conds = [c for c in args.conditions.split(",") if c]

    jobs = []
    for seed in range(args.seed_start, args.seed_start + args.num_runs):
        for cond in conds:
            for v in systems:
                name = f"{cond}__{v}"
                if (raw / f"{name}_seed_{seed}.json").exists():
                    continue
                extra = dict(CONDITIONS[cond], exposure_window_s=WINDOW_S)
                jobs.append({"system": name, "variant": v, "habituation_condition": "hab_on",
                             "condition": cond, "seed": seed,
                             "params": build_params(v, True, args.mu, args.t_end, extra)})
    print(f"[persistent] pending jobs={len(jobs)} outdir={outdir}", flush=True)
    if jobs and not args.analyze_only:
        with ProcessPoolExecutor(max_workers=max(1, min(args.max_workers, len(jobs)))) as ex:
            futs = {ex.submit(run_job, j): j for j in jobs}
            for i, fut in enumerate(as_completed(futs), 1):
                job = futs[fut]
                try:
                    row = fut.result()
                except Exception as exc:
                    print(f"[persistent] FAILED {job['system']} seed={job['seed']}: {exc!r}", flush=True)
                    continue
                row["condition"] = job["condition"]
                (raw / f"{job['system']}_seed_{job['seed']}.json").write_text(
                    json.dumps(row, indent=2, allow_nan=True), encoding="utf-8")
                print(f"[persistent] {i}/{len(jobs)} {job['system']} seed={job['seed']} "
                      f"{row['elapsed_s']:.0f}s VWE={row['value_weighted_exposure']:.1f}", flush=True)

    rows = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(raw.glob("*.json"))]
    flat = [{k: v for k, v in r.items() if k != "value_weighted_exposure_windows"} for r in rows]
    _write_csv(flat, outdir / "per_run_metrics.csv")
    (outdir / "manifest.json").write_text(json.dumps(vars(args), indent=2), encoding="utf-8")
    analyze(rows, outdir, args.reference, args.t_end)
    print(f"[persistent] wrote {outdir}", flush=True)


if __name__ == "__main__":
    main()
