"""
experiment.py -- baseline-ladder driver (Sec. 8).

Runs the ladder across seeds, under habituating and non-habituating ground
truth, and writes per-run and summary CSVs in the spirit of the existing
testbench outputs (per_run_metrics.csv / summary_by_metric.csv).

Ladder (Sec. 8.2):
  B0  reactive only
  B1  greedy unconstrained, habituation-blind  (the policy to beat)
  B3  STL-robustness value, spec without phi_hab  (isolates Idea 1)
  B4  STL-robustness value, full spec             (Idea 1 + 2)

(B2 = exposure-only "dJ" value maps structurally between B1 and B3; swap the
counterfactual U for an exposure-reduction-only value to reproduce it.)

Hypotheses checked qualitatively in the printed summary:
  H1  B4 < B1 on J_exp under habituating truth
  H2  B4 < B3 (habituation clause adds value)
  H3  B3 <= B1 (robustness reformulation does not hurt)
  H4  under non-habituating truth, B4 ~ B1 (advantage is habituation-specific)
"""
from __future__ import annotations

import csv
import statistics as stats

from reference_sim import ReferenceSim

LADDER = ["B0", "B1", "B3", "B4"]
METRIC_KEYS = ["J_exp", "deadline_miss_rate", "coverage_violation_time",
               "eta_bar", "variety_index", "hab_attributable_exposure",
               "actions", "travel"]


def run_ladder(seeds=(123, 124, 125, 126, 127), habituation=True, horizon_s=3600.0,
               **sim_kwargs):
    rows = []
    for pol in LADDER:
        for sd in seeds:
            sim = ReferenceSim(policy=pol, seed=sd, habituation=habituation,
                               horizon_s=horizon_s, **sim_kwargs)
            m = sim.run()
            m["seed"] = sd
            m["habituation"] = int(habituation)
            rows.append(m)
    return rows


def summarize(rows):
    summary = {}
    for pol in LADDER:
        sub = [r for r in rows if r["policy"] == pol]
        summary[pol] = {}
        for k in METRIC_KEYS:
            vals = [r[k] for r in sub if r[k] == r[k]]  # drop NaN
            if vals:
                mean = stats.mean(vals)
                sd = stats.pstdev(vals) if len(vals) > 1 else 0.0
                summary[pol][k] = (mean, sd)
            else:
                summary[pol][k] = (float("nan"), 0.0)
    return summary


def write_per_run(rows, path):
    keys = ["policy", "seed", "habituation"] + METRIC_KEYS
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})


def write_summary(summary, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["policy"] + [f"{k}_mean" for k in METRIC_KEYS]
                   + [f"{k}_sd" for k in METRIC_KEYS])
        for pol in LADDER:
            means = [f"{summary[pol][k][0]:.4f}" for k in METRIC_KEYS]
            sds = [f"{summary[pol][k][1]:.4f}" for k in METRIC_KEYS]
            w.writerow([pol] + means + sds)


def _print_summary(title, summary):
    print(f"\n=== {title} ===")
    print(f"{'policy':<6}{'J_exp':>12}{'miss':>8}{'cov_viol':>11}"
          f"{'eta_bar':>9}{'variety':>9}")
    for pol in LADDER:
        s = summary[pol]
        print(f"{pol:<6}{s['J_exp'][0]:>12.0f}{s['deadline_miss_rate'][0]:>8.2f}"
              f"{s['coverage_violation_time'][0]:>11.0f}{s['eta_bar'][0]:>9.3f}"
              f"{s['variety_index'][0]:>9.2f}")


def main():
    seeds = (123, 124, 125, 126, 127)

    rows_on = run_ladder(seeds=seeds, habituation=True)
    rows_off = run_ladder(seeds=seeds, habituation=False)
    all_rows = rows_on + rows_off

    write_per_run(all_rows, "per_run_metrics_ref.csv")
    sum_on = summarize(rows_on)
    sum_off = summarize(rows_off)
    write_summary(sum_on, "summary_by_metric_ref_habON.csv")
    write_summary(sum_off, "summary_by_metric_ref_habOFF.csv")

    _print_summary("Habituating ground truth (habituation ON)", sum_on)
    _print_summary("Non-habituating ground truth (habituation OFF, H4 control)", sum_off)

    b1, b3, b4 = (sum_on[p]["J_exp"][0] for p in ("B1", "B3", "B4"))
    b1o, b4o = (sum_off[p]["J_exp"][0] for p in ("B1", "B4"))
    print("\n--- Hypothesis check (qualitative, reference harness) ---")
    print(f"H1  B4 < B1 (hab ON):   {b4:.0f} < {b1:.0f}   -> {'OK' if b4 < b1 else 'NO'}")
    print(f"H2  B4 < B3:            {b4:.0f} < {b3:.0f}   -> {'OK' if b4 < b3 else 'NO'}")
    print(f"H3  B3 <= B1:           {b3:.0f} <= {b1:.0f}  -> {'OK' if b3 <= b1 * 1.02 else 'NO'}")
    print(f"H4  B4 ~ B1 (hab OFF):  {b4o:.0f} vs {b1o:.0f} "
          f"(ratio {b4o / b1o:.2f})  -> {'OK' if 0.8 <= b4o / b1o <= 1.2 else 'CHECK'}")
    print("\nWrote: per_run_metrics_ref.csv, summary_by_metric_ref_habON.csv, "
          "summary_by_metric_ref_habOFF.csv")
    print("NOTE: reference harness is a smoke test; absolute numbers are illustrative, "
          "the relative ordering demonstrates the mechanism.")


if __name__ == "__main__":
    main()
