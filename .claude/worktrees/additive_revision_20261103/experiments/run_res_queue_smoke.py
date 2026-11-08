"""
Smoke / confirmation test for the res-queue adaptive dispatch policy.

Runs B1, B4-res, and B4-res-queue at two loads:
  mu=2e-5  (spare)      — res-queue should NOT hurt hab-on advantage
  mu=4e-4  (overloaded) — res-queue should recover B1 performance

Usage:
    python -m experiments.run_res_queue_smoke [--num-runs N] [--max-workers W]
"""
import argparse
import csv
import math
import statistics as stats
from pathlib import Path

import experiments.run_habituation_stl_production_ladder as ladder

RESULTS = Path(__file__).resolve().parents[1] / "results" / "testbench"
SYSTEMS = ["B1_greedy_fixedcue", "B4_res_stl_full_multicue", "B4_res_queue_multicue"]


def run_load(mu: float, outdir: Path, num_runs: int, seed_start: int,
             max_workers: int) -> list[dict]:
    args = ladder.parse_args()
    args.mu_true = mu
    args.seed_start = seed_start
    args.num_runs = num_runs
    args.max_workers = max_workers
    args.outdir = str(outdir)
    args.systems = SYSTEMS
    args.duration_s = 1800.0
    rows = ladder.run(args)
    return rows or []


def summarise(rows: list[dict], b1_ref: dict[str, float]) -> None:
    groups: dict[tuple, list[float]] = {}
    for r in rows:
        key = (r.get("baseline", "?"), r.get("habituation_condition", "?"))
        try:
            groups.setdefault(key, []).append(float(r["value_weighted_exposure"]))
        except (KeyError, ValueError):
            pass
    for key in sorted(groups):
        bl, hab = key
        vals = [v for v in groups[key] if math.isfinite(v)]
        if not vals:
            continue
        m   = stats.mean(vals)
        ref = b1_ref.get(hab, float("nan"))
        pct = (m - ref) / ref * 100 if math.isfinite(ref) and ref != 0 else float("nan")
        print(f"  {bl:<40} {hab:>7}  n={len(vals):>2}  mean={m:>10,.0f}  vs_B1={pct:>+7.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-runs", type=int, default=5)
    ap.add_argument("--seed-start", type=int, default=125)
    ap.add_argument("--max-workers", type=int, default=10)
    args = ap.parse_args()

    all_rows: dict[float, list[dict]] = {}

    for mu, tag in ((2e-5, "mu_2em05"), (4e-4, "mu_4em04")):
        print(f"\n{'='*60}\nRunning mu={mu:.0e}\n{'='*60}")
        outdir = RESULTS / "res_queue_smoke" / tag
        outdir.mkdir(parents=True, exist_ok=True)
        rows = run_load(mu, outdir, args.num_runs, args.seed_start, args.max_workers)
        all_rows[mu] = rows

    print("\n" + "=" * 75)
    print(f"RESULTS  (n={args.num_runs} seeds each)")
    print("=" * 75)
    for mu in (2e-5, 4e-4):
        rows = all_rows[mu]
        b1_ref: dict[str, float] = {}
        for hab in ("hab_on", "hab_off"):
            b1_vals = [float(r["value_weighted_exposure"]) for r in rows
                       if r.get("baseline") == "B1_greedy_fixedcue"
                       and r.get("habituation_condition") == hab]
            b1_vals = [v for v in b1_vals if math.isfinite(v)]
            if b1_vals:
                b1_ref[hab] = stats.mean(b1_vals)
        print(f"\nmu={mu:.0e}  B1 refs: "
              f"hab_on={b1_ref.get('hab_on', float('nan')):,.0f}  "
              f"hab_off={b1_ref.get('hab_off', float('nan')):,.0f}")
        summarise(rows, b1_ref)

    # Write flat CSV
    all_flat = [r for rows in all_rows.values() for r in rows]
    if all_flat:
        out_csv = RESULTS / "res_queue_smoke" / "res_queue_smoke_summary.csv"
        fields = list(dict.fromkeys(k for r in all_flat for k in r))
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, restval="")
            w.writeheader()
            w.writerows(all_flat)
        print(f"\nWrote {out_csv}")


if __name__ == "__main__":
    main()
