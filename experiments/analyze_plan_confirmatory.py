"""
analyze_plan_confirmatory.py -- confirmatory analysis for the improvement plan (Plan §6).

Declared before the faithful-planner evaluation runs (2026-10-14):

Confirmatory family (Holm-adjusted together, familywise alpha 0.05):
  For each load in {spare 2e-5, heavy 1e-4, overload 4e-4}, habituation on, treatment vs B5:
    H1(load): exposure.  Two-sided Wilcoxon signed-rank on paired value_weighted_exposure.
    H2(load): service noninferiority.  H0: mean paired (treatment - B5) reactive_miss_fraction
              >= +0.02 (2 pp).  One-sided Wilcoxon signed-rank on (diff - 0.02), alternative "less".
  Six hypotheses in total. Holm's step-down procedure over the six p-values.
  Noninferiority is additionally reported with the paired percentile bootstrap: the one-sided
  97.5% upper bound (upper end of the two-sided 95% interval) must lie below +0.02.

Everything else (other variants, habituation off, mechanism metrics) is exploratory: nominal
p-values and bootstrap intervals, not multiplicity-adjusted, and not interpreted as confirmatory.

Percent effect = mean paired difference / mean of the reference (B5) x 100.
Pairs: a seed is used only when both systems have a finite value. Missing or failed seeds are
listed explicitly; any comparison with fewer than the expected number of pairs is flagged.

Usage:
  py -3.10 -m experiments.analyze_plan_confirmatory --treatment E_plan \
      --dirs spare=results/testbench/plan_faithful_mu2e5 heavy=... overload=...
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

NI_MARGIN = 0.02
ALPHA = 0.05


def load_rows(d: Path) -> list[dict]:
    raw = d / "raw"
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(raw.glob("*.json"))]


def paired(rows, ref, trt, metric, hab="hab_on"):
    def by_seed(v):
        out = {}
        for r in rows:
            if r.get("variant") == v and r.get("habituation_condition") == hab:
                try:
                    x = float(r.get(metric))
                except (TypeError, ValueError):
                    x = float("nan")
                out[int(r["seed"])] = x
        return out

    a, b = by_seed(ref), by_seed(trt)
    seeds = sorted(set(a) | set(b))
    used = [s for s in seeds if s in a and s in b and math.isfinite(a[s]) and math.isfinite(b[s])]
    missing = [s for s in seeds if s not in used]
    return np.array([a[s] for s in used]), np.array([b[s] for s in used]), used, missing


def bootstrap_ci(d, n_boot=10000, seed=12345):
    if d.size < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, d.size, size=(n_boot, d.size))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def holm(pvals: list[float]) -> list[float]:
    """Holm step-down adjusted p-values (monotone, capped at 1)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def main() -> None:
    p = argparse.ArgumentParser(description="Plan §6 confirmatory analysis")
    p.add_argument("--treatment", required=True)
    p.add_argument("--reference", default="B5")
    p.add_argument("--dirs", nargs="+", required=True, help="load=path entries")
    p.add_argument("--expected-n", type=int, default=30)
    p.add_argument("--out", default="results/testbench/plan_confirmatory_analysis")
    args = p.parse_args()

    tests = []
    for entry in args.dirs:
        load, path = entry.split("=", 1)
        rows = load_rows(Path(path))
        a, b, used, missing = paired(rows, args.reference, args.treatment, "value_weighted_exposure")
        d = b - a
        lo, hi = bootstrap_ci(d)
        p_exp = float(wilcoxon(d).pvalue) if d.size >= 2 and np.any(d != 0) else 1.0
        tests.append({"load": load, "hypothesis": "exposure (two-sided)", "n": int(d.size),
                      "missing_seeds": missing, "mean_diff": float(d.mean()) if d.size else float("nan"),
                      "pct_of_ref": float(100 * d.mean() / a.mean()) if d.size else float("nan"),
                      "ci_lo": lo, "ci_hi": hi, "p": p_exp, "bootstrap_upper_below_margin": ""})
        a, b, used, missing = paired(rows, args.reference, args.treatment, "reactive_miss_fraction")
        d = b - a
        lo, hi = bootstrap_ci(d)
        shifted = d - NI_MARGIN
        p_ni = float(wilcoxon(shifted, alternative="less").pvalue) if d.size >= 2 else 1.0
        tests.append({"load": load, "hypothesis": "service noninferiority (one-sided, margin +2 pp)",
                      "n": int(d.size), "missing_seeds": missing,
                      "mean_diff": float(d.mean()) if d.size else float("nan"),
                      "pct_of_ref": float("nan"), "ci_lo": lo, "ci_hi": hi, "p": p_ni,
                      "bootstrap_upper_below_margin": bool(hi < NI_MARGIN)})

    adj = holm([t["p"] for t in tests])
    for t, pa in zip(tests, adj):
        t["p_holm"] = pa
        t["reject_h0_at_0.05"] = bool(pa < ALPHA)
        t["n_flag"] = "" if t["n"] == args.expected_n else f"n={t['n']} < expected {args.expected_n}"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "confirmatory_tests.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(tests[0].keys()))
        w.writeheader()
        for t in tests:
            w.writerow({k: (json.dumps(v) if isinstance(v, list) else v) for k, v in t.items()})
    lines = [f"# Confirmatory family: {args.treatment} vs {args.reference} (habituation on)", "",
             "Holm-adjusted over all six hypotheses; familywise alpha 0.05. Exposure: two-sided Wilcoxon.",
             "Noninferiority: one-sided Wilcoxon on (diff - 0.02), and paired bootstrap upper 97.5% bound.", "",
             "| Load | Hypothesis | n | Mean diff | 95% CI | % of ref | p | p (Holm) | Reject H0 | Notes |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in tests:
        note = "; ".join(x for x in [t["n_flag"], ("missing seeds " + str(t["missing_seeds"])) if t["missing_seeds"] else ""] if x)
        lines.append(f"| {t['load']} | {t['hypothesis']} | {t['n']} | {t['mean_diff']:+.4g} | "
                     f"[{t['ci_lo']:+.4g}, {t['ci_hi']:+.4g}] | {t['pct_of_ref']:+.2f} | {t['p']:.4g} | "
                     f"{t['p_holm']:.4g} | {t['reject_h0_at_0.05']} | {note} |")
    (out / "confirmatory_tests.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
